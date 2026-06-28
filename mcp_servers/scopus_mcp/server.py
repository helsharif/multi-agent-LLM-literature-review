import os
import json
import asyncio
import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

SCOPUS_BASE = "https://api.elsevier.com/content"
KEYS_FILE = os.path.join(os.path.dirname(__file__), "../../secrets/keys.txt")

app = Server("scopus-mcp")


def load_api_key(keys_path: str = KEYS_FILE) -> str:
    with open(keys_path) as f:
        for line in f:
            if line.startswith("SCOPUS_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise ValueError("SCOPUS_API_KEY not found in secrets/keys.txt")


def search_papers(query: str, limit: int, api_key: str) -> list[dict]:
    url = f"{SCOPUS_BASE}/search/scopus"
    params = {
        "query": query,
        "count": limit,
        "apiKey": api_key,
        "field": "dc:title,dc:creator,prism:doi,prism:coverDate,dc:description",
    }
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Scopus search failed: HTTP {resp.status_code}")
    entries = resp.json().get("search-results", {}).get("entry", [])
    results = []
    for e in entries:
        date = e.get("prism:coverDate", "")
        results.append({
            "title": e.get("dc:title", ""),
            "first_author": e.get("dc:creator", ""),
            "doi": e.get("prism:doi", ""),
            "year": date[:4] if date else "",
            "abstract_snippet": e.get("dc:description", ""),
        })
    return results


def get_abstract(doi: str, api_key: str) -> dict:
    url = f"{SCOPUS_BASE}/abstract/doi/{doi}"
    resp = requests.get(url, params={"apiKey": api_key}, timeout=30)
    if resp.status_code == 404:
        raise RuntimeError(f"Abstract not found for DOI: {doi}")
    if resp.status_code != 200:
        raise RuntimeError(f"Scopus abstract fetch failed: HTTP {resp.status_code}")
    core = (
        resp.json()
        .get("abstracts-retrieval-response", {})
        .get("coredata", {})
    )
    return {
        "doi": core.get("prism:doi", doi),
        "title": core.get("dc:title", ""),
        "abstract": core.get("dc:description", ""),
    }


def get_full_text(doi: str, api_key: str) -> dict:
    url = f"https://api.elsevier.com/content/article/doi/{doi}"
    headers = {"Accept": "text/plain", "X-ELS-APIKey": api_key}
    resp = requests.get(url, headers=headers, timeout=60)
    if resp.status_code == 404:
        raise RuntimeError(f"Full text not found for DOI: {doi}")
    if resp.status_code == 403:
        raise RuntimeError(f"Full text access denied for DOI: {doi} — institutional subscription required")
    if resp.status_code >= 500:
        raise RuntimeError(f"ScienceDirect server error: HTTP {resp.status_code}")
    if resp.status_code != 200:
        raise RuntimeError(f"ScienceDirect full text fetch failed: HTTP {resp.status_code}")
    return {"doi": doi, "full_text": resp.text}


def verify_doi(doi: str, api_key: str) -> bool:
    url = f"{SCOPUS_BASE}/search/scopus"
    params = {"query": f"DOI({doi})", "count": 1, "apiKey": api_key}
    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code >= 500:
        raise RuntimeError(f"Scopus server error during DOI verification: HTTP {resp.status_code}")
    if resp.status_code != 200:
        return False
    total = resp.json().get("search-results", {}).get("opensearch:totalResults", "0")
    return int(total) > 0


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_papers",
            description="Search Scopus for papers matching a query. Returns title, first_author, doi, year, abstract_snippet.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Scopus search query string"},
                    "limit": {"type": "integer", "description": "Max papers to return", "default": 20},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_abstract",
            description="Fetch the full abstract for a paper by DOI.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doi": {"type": "string", "description": "Paper DOI"},
                },
                "required": ["doi"],
            },
        ),
        types.Tool(
            name="verify_doi",
            description="Confirm a DOI resolves to a real Scopus record. Returns true/false.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doi": {"type": "string", "description": "Paper DOI to verify"},
                },
                "required": ["doi"],
            },
        ),
        types.Tool(
            name="get_full_text",
            description="Fetch the full text of an article via ScienceDirect (same API key as Scopus). Returns plain text. Raises if access is denied (institutional subscription required) or article not found.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doi": {"type": "string", "description": "Paper DOI"},
                },
                "required": ["doi"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        api_key = load_api_key()
        if name == "search_papers":
            result = search_papers(arguments["query"], arguments.get("limit", 20), api_key)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        elif name == "get_abstract":
            result = get_abstract(arguments["doi"], api_key)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        elif name == "verify_doi":
            result = verify_doi(arguments["doi"], api_key)
            return [types.TextContent(type="text", text=json.dumps({"exists": result}))]
        elif name == "get_full_text":
            result = get_full_text(arguments["doi"], api_key)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
