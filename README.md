[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=AchachiSoftware_storm-site-mcp&metric=alert_status&token=)](https://sonarcloud.io/summary/new_code?id=AchachiSoftware_storm-site-mcp) \
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=AchachiSoftware_storm-site-mcp&metric=bugs&token=)](https://sonarcloud.io/summary/new_code?id=AchachiSoftware_storm-site-mcp) \
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=AchachiSoftware_storm-site-mcp&metric=code_smells&token=)](https://sonarcloud.io/summary/new_code?id=AchachiSoftware_storm-site-mcp) \
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=AchachiSoftware_storm-site-mcp&metric=coverage&token=)](https://sonarcloud.io/summary/new_code?id=AchachiSoftware_storm-site-mcp) \
[![Duplicated Lines (%)](https://sonarcloud.io/api/project_badges/measure?project=AchachiSoftware_storm-site-mcp&metric=duplicated_lines_density&token=)](https://sonarcloud.io/summary/new_code?id=AchachiSoftware_storm-site-mcp) \
[![Lines of Code](https://sonarcloud.io/api/project_badges/measure?project=AchachiSoftware_storm-site-mcp&metric=ncloc&token=)](https://sonarcloud.io/summary/new_code?id=AchachiSoftware_storm-site-mcp) \
[![Reliability Rating](https://sonarcloud.io/api/project_badges/measure?project=AchachiSoftware_storm-site-mcp&metric=reliability_rating&token=)](https://sonarcloud.io/summary/new_code?id=AchachiSoftware_storm-site-mcp) \
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=AchachiSoftware_storm-site-mcp&metric=security_rating&token=)](https://sonarcloud.io/summary/new_code?id=AchachiSoftware_storm-site-mcp) \
[![Technical Debt](https://sonarcloud.io/api/project_badges/measure?project=AchachiSoftware_storm-site-mcp&metric=sqale_index&token=)](https://sonarcloud.io/summary/new_code?id=AchachiSoftware_storm-site-mcp) \
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=AchachiSoftware_storm-site-mcp&metric=sqale_rating&token=)](https://sonarcloud.io/summary/new_code?id=AchachiSoftware_storm-site-mcp) \
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=AchachiSoftware_storm-site-mcp&metric=vulnerabilities&token=)](https://sonarcloud.io/summary/new_code?id=AchachiSoftware_storm-site-mcp)

# storm-client.net developer MCP

A [Model Context Protocol](https://modelcontextprotocol.io/) server for developers to interact with [Storm-client.net](https://storm-client.net). Lets you manage your plans, prices, plugins, and plugin links through an AI assistant like Claude.

## Prerequisites

- Python 3.12+
- A Storm-client.net developer account
- [Claude Code](https://claude.ai/code) or another MCP-compatible client

## Getting your token

1. Log in to [storm-client.net](https://storm-client.net)
2. Open browser DevTools → **Application** → **Cookies** → `storm-client.net`
3. Copy the value of the `token` cookie — this is your bearer token

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/AchachiSoftware/storm-site-mcp
cd storm-site-mcp

# 2. Create a virtual environment and install dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Create your local config
cp .env.example .env
# Edit .env and paste your token as STORM_TOKEN=<your token>
```

## Configuring Claude Code

Create a `.mcp.json` file in the project root (it's gitignored, so it stays local):

```json
{
  "mcpServers": {
    "storm-client": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/server.py"],
      "env": {
        "STORM_TOKEN": "your_token_here",
        "CONFIG_DIR": "/absolute/path/to/config",
        "HAR_DIR": "/absolute/path/to/har"
      }
    }
  }
}
```

Then start Claude Code from the project directory. Run `/mcp` to confirm the `storm-client` server is connected.

### Docker (alternative)

```bash
docker build -t storm-client-mcp .
docker run -e STORM_TOKEN=your_token_here \
  -v $(pwd)/config:/app/config \
  -v $(pwd)/har:/app/har \
  storm-client-mcp
```

## Available tools

| Tool | Description |
|---|---|
| `list_plans` | List all your plans (paginated automatically) |
| `list_prices` | List prices for a given plan ID |
| `update_price` | Set a promo discount percent (0–100) on a price |
| `call_endpoint` | Call any API path directly — useful for exploration. Accepts a relative path (e.g. `/shop/plans/my`) or a full URL (e.g. `https://api.storm-client.net/plugin-repos`) |
| `register_endpoint` | Save a discovered endpoint to the local registry |
| `list_registered_endpoints` | Show all saved endpoints |
| `import_har` | Import endpoints from a browser HAR export |

## Discovering endpoints via HAR

The Storm site makes API calls to two bases:
- `https://storm-client.net/api/shop/` — plans, prices, subscriptions, plugin links
- `https://api.storm-client.net/` — plugin repos, plugins, changelogs, orders, payouts

To capture API calls the site makes:

1. Open DevTools → **Network** tab
2. Navigate around the developer portal
3. Right-click any request → **Save all as HAR with content**
4. Drop the `.har` file into the `har/` directory
5. Ask Claude to run `import_har` with the filename

## Endpoints registry

Discovered endpoints are stored in `config/endpoints.json`. The repo ships with a set of known endpoints — you can add more via `register_endpoint` or `import_har` and commit them back for others to benefit.
