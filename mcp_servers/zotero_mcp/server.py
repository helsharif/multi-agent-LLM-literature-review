import os
import asyncio
import json
from pyzotero import zotero as pyzotero_lib
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

KEYS_FILE = os.path.join(os.path.dirname(__file__), "../../secrets/keys.txt")

app = Server("zotero-mcp")


def load_credentials(keys_path: str = KEYS_FILE) -> dict:
    creds = {}
    with open(keys_path) as f:
        for line in f:
            if line.startswith("ZOTERO_API_KEY="):
                creds["api_key"] = line.split("=", 1)[1].strip()
            elif line.startswith("ZOTERO_USER_ID="):
                creds["user_id"] = line.split("=", 1)[1].strip()
    if "api_key" not in creds:
        raise ValueError("ZOTERO_API_KEY not found in secrets/keys.txt")
    if "user_id" not in creds:
        raise ValueError("ZOTERO_USER_ID not found in secrets/keys.txt")
    return creds


class ZoteroClient:
    def __init__(self, creds: dict, zot=None):
        self.zot = zot or pyzotero_lib.Zotero(creds["user_id"], "user", creds["api_key"])

    def create_collection(self, name: str) -> str:
        result = self.zot.create_collection([{"name": name, "parentCollection": False}])
        return result[0]["key"]

    def get_collection_key_by_name(self, name: str) -> str | None:
        collections = self.zot.collections()
        for c in collections:
            if c["data"]["name"] == name:
                return c["key"]
        return None

    def get_collection_items(self, collection_key: str) -> list[dict]:
        items = self.zot.collection_items(collection_key)
        results = []
        for item in items:
            d = item.get("data", {})
            creators = d.get("creators", [])
            first_author = creators[0].get("lastName", "") if creators else ""
            results.append({
                "title": d.get("title", ""),
                "doi": d.get("DOI", ""),
                "first_author": first_author,
                "year": d.get("date", "")[:4],
                "zotero_key": item.get("key", ""),
            })
        return results

    def search_library_by_doi(self, doi: str) -> dict | None:
        results = self.zot.items(q=doi)
        for item in results:
            if item.get("data", {}).get("DOI", "").lower() == doi.lower():
                return item
        return None

    def add_item(self, paper: dict, collection_key: str) -> str:
        template = self.zot.item_template("journalArticle")
        last_name = paper.get("first_author", "").split(",")[0].strip()
        template["title"] = paper.get("title", "")
        template["DOI"] = paper.get("doi", "")
        template["date"] = paper.get("year", "")
        template["abstractNote"] = paper.get("abstract", "")
        template["collections"] = [collection_key]
        if last_name:
            template["creators"] = [{"creatorType": "author", "lastName": last_name, "firstName": ""}]
        result = self.zot.create_items([template])
        return result[0]["key"]

    def export_bibliography(self, collection_key: str, style: str = "agu") -> str:
        items = self.zot.collection_items(collection_key, format="bib", style=style)
        return items if isinstance(items, str) else json.dumps(items, indent=2)


_client: ZoteroClient | None = None


def get_client() -> ZoteroClient:
    global _client
    if _client is None:
        _client = ZoteroClient(load_credentials())
    return _client


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="create_collection",
            description="Create a new Zotero collection (folder). Returns the collection key.",
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Collection name, e.g. 'Permafrost Carbon — 2026-06-27'"}},
                "required": ["name"],
            },
        ),
        types.Tool(
            name="get_collection_key_by_name",
            description="Look up an existing Zotero collection key by its name. Returns null if not found.",
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        ),
        types.Tool(
            name="get_collection_items",
            description="List all papers in a Zotero collection. Returns title, doi, first_author, year, zotero_key.",
            inputSchema={
                "type": "object",
                "properties": {"collection_key": {"type": "string"}},
                "required": ["collection_key"],
            },
        ),
        types.Tool(
            name="add_item",
            description="Add a verified paper to a Zotero collection. Pass paper metadata and collection_key.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "doi": {"type": "string"},
                    "first_author": {"type": "string", "description": "Last, First format"},
                    "year": {"type": "string"},
                    "abstract": {"type": "string"},
                    "collection_key": {"type": "string"},
                },
                "required": ["title", "doi", "collection_key"],
            },
        ),
        types.Tool(
            name="export_bibliography",
            description="Export AGU-formatted bibliography for all items in a collection.",
            inputSchema={
                "type": "object",
                "properties": {
                    "collection_key": {"type": "string"},
                    "style": {"type": "string", "default": "agu", "description": "CSL style name"},
                },
                "required": ["collection_key"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        client = get_client()
        if name == "create_collection":
            key = client.create_collection(arguments["name"])
            return [types.TextContent(type="text", text=json.dumps({"collection_key": key}))]
        elif name == "get_collection_key_by_name":
            key = client.get_collection_key_by_name(arguments["name"])
            return [types.TextContent(type="text", text=json.dumps({"collection_key": key}))]
        elif name == "get_collection_items":
            items = client.get_collection_items(arguments["collection_key"])
            return [types.TextContent(type="text", text=json.dumps(items, indent=2))]
        elif name == "add_item":
            paper = {k: arguments.get(k, "") for k in ["title", "doi", "first_author", "year", "abstract"]}
            item_key = client.add_item(paper, arguments["collection_key"])
            return [types.TextContent(type="text", text=json.dumps({"item_key": item_key}))]
        elif name == "export_bibliography":
            bib = client.export_bibliography(arguments["collection_key"], arguments.get("style", "agu"))
            return [types.TextContent(type="text", text=bib)]
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
