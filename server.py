#!/usr/bin/env python3
import json
import os
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

HEADERS = {
    "authorization": f"Bearer {TOKEN}",
    "accept": "*/*",
    "content-type": "application/json",
    "referer": "https://storm-client.net/developer",
}
COOKIES = {"token": TOKEN}

mcp = FastMCP("storm-client")


# ── Helpers ───────────────────────────────────────────────────────────────────
def _api(method: str, path: str, *, params=None, json_body=None) -> dict:
    url = path if path.startswith("http") else f"{BASE}{path}"
    resp = requests.request(
        method.upper(),
        url,
        headers=HEADERS,
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
    har_path = HAR_DIR / Path(filename).name
    if not har_path.exists():
        return f"File not found: {har_path}\nDrop the HAR file into the project har/ directory first."

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
