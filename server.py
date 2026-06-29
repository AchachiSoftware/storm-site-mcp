#!/usr/bin/env python3
import base64
import json
import os
import threading
import time
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN = os.environ["STORM_TOKEN"]
BASE = "https://storm-client.net/api"
BASE_API = "https://api.storm-client.net"
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/app/config"))
HAR_DIR = Path(os.environ.get("HAR_DIR", "/app/har"))
REGISTRY_FILE = CONFIG_DIR / "endpoints.json"
DEFAULT_DEVELOPER_ID = int(os.environ.get("STORM_DEVELOPER_ID", "655"))

# The STORM_TOKEN cookie is read-only: GETs authenticate fine with it, but mutating
# calls return 403. Writes need a JWT obtained by exchanging the cookie (see _get_jwt).
COMMON_HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "referer": "https://storm-client.net/developer",
}
COOKIES = {"token": TOKEN}

mcp = FastMCP("storm-client")


# ── Auth ──────────────────────────────────────────────────────────────────────
_jwt_cache = {"token": None, "exp": 0.0}
_jwt_lock = threading.Lock()


def _decode_jwt_exp(jwt: str) -> float:
    """Best-effort decode of a JWT's `exp` claim (no signature verification)."""
    try:
        payload_b64 = jwt.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(payload.get("exp", 0))
    except (IndexError, ValueError, json.JSONDecodeError):
        return 0.0


def _get_jwt() -> str:
    """
    Exchange the read-only token cookie for a write-capable JWT.

    Cached and reused until ~5 min before expiry, then transparently re-fetched.
    The exchange sends the raw cookie value as the Authorization header (no Bearer).
    """
    with _jwt_lock:
        now = time.time()
        if _jwt_cache["token"] and now < _jwt_cache["exp"] - 300:
            return _jwt_cache["token"]
        resp = requests.post(
            f"{BASE_API}/identity/token",
            headers={"authorization": TOKEN, "accept": "*/*"},
            timeout=15,
        )
        resp.raise_for_status()
        jwt = resp.json()["token"]
        exp = _decode_jwt_exp(jwt) or (now + 168 * 3600)
        _jwt_cache.update(token=jwt, exp=exp)
        return jwt


# ── Helpers ───────────────────────────────────────────────────────────────────
def _api(method: str, path: str, *, params=None, json_body=None) -> dict:
    """
    Call the Storm API. GETs use the read-only token cookie; mutating requests
    auto-exchange that cookie for a JWT and send it as a Bearer token.
    """
    method = method.upper()
    url = path if path.startswith("http") else f"{BASE}{path}"
    headers = dict(COMMON_HEADERS)
    if method == "GET":
        headers["authorization"] = f"Bearer {TOKEN}"
    else:
        headers["authorization"] = f"Bearer {_get_jwt()}"
    resp = requests.request(
        method,
        url,
        headers=headers,
        cookies=COOKIES,
        params=params,
        json=json_body,
        timeout=15,
    )
    return {"status": resp.status_code, "body": resp.text}


def _load_registry() -> dict:
    try:
        return json.loads(REGISTRY_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_registry(registry: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(registry, indent=2))


# ── Plan / price tools ────────────────────────────────────────────────────────
@mcp.tool()
def list_plans() -> str:
    """List all plans in the developer store."""
    all_plans = []
    for page in range(20):
        result = _api("GET", "/shop/plans/my", params={"page": page, "size": 10, "sort": "id,asc"})
        if result["status"] != 200:
            return f"Error {result['status']}: {result['body']}"
        data = json.loads(result["body"])
        all_plans.extend(data["content"])
        if data["last"]:
            break
    return json.dumps(all_plans, indent=2)


@mcp.tool()
def list_prices(plan_id: int) -> str:
    """List all prices for a given plan ID."""
    result = _api("GET", "/shop/prices/my", params={"planId": plan_id})
    return f"Status {result['status']}:\n{result['body']}"


@mcp.tool()
def update_price(price_id: int, discount_percent: int) -> str:
    """Set the promo discount percent (0–100) for a price entry."""
    result = _api(
        "PUT",
        f"/shop/prices/{price_id}",
        json_body={"priceId": price_id, "promoDiscountPercent": discount_percent},
    )
    return f"Status {result['status']}: {result['body']}"


# `priority` is intentionally excluded: the single-field PUT returns 204 but the
# server silently ignores it (verified by round-trip), so plan ordering must be
# changed by some other endpoint, not this partial update.
EDITABLE_PLAN_FIELDS = {"description", "imageUrl", "name", "tags"}


@mcp.tool()
def update_plan_field(plan_id: int, field: str, value: str) -> str:
    """
    Update a single editable field on one of your plans (partial update; expects 204).

    field: one of description, imageUrl, name, tags
    value: the new value as a string. JSON values are parsed automatically, so
           tags accepts a JSON array or a plain comma-separated string, and plain
           text is sent as-is for name/description/imageUrl.

    This is a write, so it auto-exchanges the token cookie for a JWT.
    """
    if field not in EDITABLE_PLAN_FIELDS:
        allowed = ", ".join(sorted(EDITABLE_PLAN_FIELDS))
        return f"Field '{field}' is not editable. Allowed: {allowed}"

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = value

    result = _api("PUT", f"/shop/plans/{plan_id}", json_body={"id": plan_id, field: parsed})
    return f"Status {result['status']}: {result['body'] or '(empty)'}"


def _plan_owner_id(plan: dict):
    """Resolve a plan's owner id across the field names the API has used."""
    for key in ("ownerId", "owner", "developerId", "developer"):
        val = plan.get(key)
        if isinstance(val, dict):
            val = val.get("id")
        if val is not None:
            return val
    return None


@mcp.tool()
def list_my_plans(developer_id: int = DEFAULT_DEVELOPER_ID) -> str:
    """
    Enumerate ALL plans owned by a developer, including hidden ones.

    Needed because /shop/plans/my returns 403 and /shop/plans?ownerId= omits hidden
    plans. This finds the highest plan id, then walks GET /shop/plans/{id} keeping
    those whose owner matches developer_id (default 655).
    """
    probe = _api("GET", "/shop/plans", params={"page": 0, "size": 1, "sort": "id,desc"})
    if probe["status"] != 200:
        return f"Error probing max plan id {probe['status']}: {probe['body']}"
    content = json.loads(probe["body"]).get("content", [])
    if not content:
        return "No plans found in store."
    max_id = content[0]["id"]

    mine = []
    for pid in range(1, max_id + 1):
        result = _api("GET", f"/shop/plans/{pid}")
        if result["status"] != 200:
            continue
        plan = json.loads(result["body"])
        if _plan_owner_id(plan) == developer_id:
            mine.append(plan)
    return json.dumps(mine, indent=2)


# ── Blacklist tools ───────────────────────────────────────────────────────────
def _bl_request(method: str, path: str, params=None) -> tuple:
    """
    Call a blacklist endpoint. These require JWT auth even for GET (the read-only
    token cookie returns 403), so unlike _api they always send the exchanged JWT.
    """
    headers = dict(COMMON_HEADERS)
    headers["authorization"] = f"Bearer {_get_jwt()}"
    resp = requests.request(method, f"{BASE}{path}", headers=headers, cookies=COOKIES, params=params, timeout=15)
    return resp.status_code, resp.text


def _my_plans() -> list:
    """(id, name) for every plan owned by the authenticated developer (JWT-authed)."""
    headers = dict(COMMON_HEADERS)
    headers["authorization"] = f"Bearer {_get_jwt()}"
    plans = []
    for page in range(50):
        resp = requests.get(
            f"{BASE}/shop/plans/my",
            headers=headers,
            cookies=COOKIES,
            params={"page": page, "size": 50, "sort": "id,asc"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        plans.extend((p["id"], p.get("name")) for p in data["content"])
        if data["last"]:
            break
    return plans


@mcp.tool()
def list_plan_blacklist(plan_id: int) -> str:
    """List the users blacklisted from a given plan (id, discordId, username, enabled)."""
    status, body = _bl_request("GET", f"/shop/plans/{plan_id}/blacklist")
    return f"Status {status}:\n{body}"


@mcp.tool()
def blacklist_user(discord_id: str, plan_id: int = 0) -> str:
    """
    Blacklist a user (by Discord ID) from a plan, or from ALL your plans.

    discord_id: the user's Discord ID (snowflake string). Must resolve to a real
                Storm user — an unknown id returns 404.
    plan_id:    a specific plan id, or 0 (default) to apply to every plan you own.

    Adds the user to each plan's blacklist (POST .../blacklist?discordId=...);
    re-adding an existing entry is harmless. This is a write, so it auto-exchanges
    the token cookie for a JWT.
    """
    targets = [(plan_id, None)] if plan_id else _my_plans()
    lines = []
    for pid, name in targets:
        status, body = _bl_request("POST", f"/shop/plans/{pid}/blacklist", params={"discordId": discord_id})
        label = f"plan {pid}" + (f" ({name})" if name else "")
        lines.append(f"{label}: {status}" + ("" if status == 204 else f" {body[:120]}"))
    return "\n".join(lines)


@mcp.tool()
def unblacklist_user(discord_id: str, plan_id: int = 0) -> str:
    """
    Remove a user's blacklist entry (by Discord ID) from a plan, or from ALL your plans.

    plan_id: a specific plan id, or 0 (default) to remove from every plan you own.

    Looks up the blacklist entry id on each plan, then deletes it
    (DELETE .../blacklist/{entryId}). Plans where the user isn't blacklisted are skipped.
    """
    targets = [(plan_id, None)] if plan_id else _my_plans()
    lines = []
    for pid, name in targets:
        status, body = _bl_request("GET", f"/shop/plans/{pid}/blacklist")
        label = f"plan {pid}" + (f" ({name})" if name else "")
        if status != 200:
            lines.append(f"{label}: lookup failed {status} {body[:120]}")
            continue
        match = next((e for e in json.loads(body) if str(e.get("discordId")) == str(discord_id)), None)
        if not match:
            lines.append(f"{label}: not blacklisted, skipped")
            continue
        dstatus, dbody = _bl_request("DELETE", f"/shop/plans/{pid}/blacklist/{match['id']}")
        lines.append(f"{label}: {dstatus}" + ("" if dstatus == 204 else f" {dbody[:120]}"))
    return "\n".join(lines)


# ── Generic / discovery tools ─────────────────────────────────────────────────
@mcp.tool()
def call_endpoint(method: str, path: str, params: str = "", body: str = "") -> str:
    """
    Call any API path directly. Useful for exploring undocumented endpoints.

    method: GET | POST | PUT | DELETE | PATCH
    path:   relative to base URL (e.g. /shop/plans/my) OR a full URL
            (e.g. https://api.storm-client.net/plugin-repos/73)
    params: optional JSON string of query params, e.g. '{"page": 0, "size": 10}'
    body:   optional JSON string of request body
    """
    parsed_params = json.loads(params) if params.strip() else None
    parsed_body = json.loads(body) if body.strip() else None
    result = _api(method, path, params=parsed_params, json_body=parsed_body)
    return f"Status {result['status']}:\n{result['body']}"


@mcp.tool()
def register_endpoint(name: str, method: str, path: str, description: str, example_params: str = "") -> str:
    """
    Save a discovered endpoint to the local registry for future reference.

    name:           short identifier, e.g. 'list_plugins'
    example_params: optional JSON string of typical query params
    """
    registry = _load_registry()
    registry[name] = {
        "method": method.upper(),
        "path": path,
        "description": description,
        "example_params": json.loads(example_params) if example_params.strip() else {},
    }
    _save_registry(registry)
    return f"Registered: {method.upper()} {path} as '{name}'"


@mcp.tool()
def list_registered_endpoints() -> str:
    """Show all endpoints saved in the local registry."""
    registry = _load_registry()
    if not registry:
        return "No endpoints registered yet. Use register_endpoint or import_har to add some."
    return json.dumps(registry, indent=2)


@mcp.tool()
def import_har(filename: str) -> str:
    """
    Import and register API endpoints from a HAR file exported from browser DevTools.

    How to export a HAR:
      DevTools → Network tab → right-click any request → "Save all as HAR with content"

    Place the .har file in the project har/ directory, then call this tool with just
    the filename (e.g. 'storm-client.har'). Only storm-client.net/api requests are kept.
    Duplicate entries are skipped automatically.
    """
    available = {f.name: f for f in HAR_DIR.iterdir() if f.is_file()}
    if filename not in available:
        listed = ", ".join(sorted(available)) or "none"
        return f"File '{filename}' not found in har/ directory. Available: {listed}"
    har_path = available[filename]

    har = json.loads(har_path.read_text())
    registry = _load_registry()

    added, skipped = [], []

    for entry in har["log"]["entries"]:
        url = entry["request"]["url"]
        if "storm-client.net" not in url or "/api/" not in url:
            continue

        method = entry["request"]["method"]

        # Strip base and query string to get clean path
        path = "/" + url.split("/api/", 1)[1].split("?")[0].rstrip("/")
        if not path or path == "/":
            continue

        # Derive a stable name from method + path
        name = f"{method.lower()}_{path.strip('/').replace('/', '_').replace('-', '_')}"

        if name in registry:
            skipped.append(name)
            continue

        qs = entry["request"].get("queryString", [])
        example_params = {q["name"]: q["value"] for q in qs} if qs else {}

        registry[name] = {
            "method": method.upper(),
            "path": path,
            "description": "Discovered via HAR import",
            "example_params": example_params,
        }
        added.append(f"{method} {path}")

    _save_registry(registry)

    lines = [f"Imported {len(added)} new endpoint(s), skipped {len(skipped)} already known."]
    if added:
        lines.append("\nNew endpoints:")
        lines.extend(f"  {e}" for e in added)
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
