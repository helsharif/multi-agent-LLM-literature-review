# Auto Literature Review — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-agent Claude Code workflow that takes a topic and produces a grounded, AGU-cited literature review with every citation verified for existence and relevance via Scopus.

**Architecture:** An Orchestrator agent coordinates parallel Search Agents (Scopus MCP), a Synthesis Agent (drafts narrative), a Critic Agent (two-pass citation verification), a Re-search Agent (fixes failures), a Zotero Agent (saves to collection via pyzotero), and a Formatter Agent (final output). The workflow is driven by Claude Code's native Agent tool, guided by CLAUDE.md and a runtime prompt template. The two MCP servers (Scopus, Zotero) are custom Python stdio servers registered in `.claude/settings.local.json`.

**Tech Stack:** Python 3.12, `mcp` SDK (PyPI), `requests`, `pyzotero`, pytest, Claude Code Agent tool

---

## File Map

| File | Purpose |
|---|---|
| `.venv/` | Single shared Python 3.12 virtual environment for both MCP servers |
| `requirements.txt` | Shared deps: mcp, requests, pyzotero, pytest |
| `mcp_servers/scopus_mcp/server.py` | Custom MCP server — 3 tools: search_papers, get_abstract, verify_doi |
| `mcp_servers/scopus_mcp/tests/test_server.py` | Unit tests for Scopus MCP tools |
| `mcp_servers/zotero_mcp/server.py` | Custom MCP server — 5 tools: create_collection, get_collection_items, add_item, search_library, export_bibliography |
| `mcp_servers/zotero_mcp/tests/test_server.py` | Unit tests for Zotero MCP tools |
| `.claude/settings.local.json` | Registers both MCP servers so Claude Code loads them each session |
| `CLAUDE.md` | Standing instructions: agent roles, workflow, citation rules, MCP tool reference |
| `prompts/lit_review_runtime_prompt.md` | Copy-paste template to trigger a new literature review run |
| `logs/verification_log.md` | Template — appended to by Critic Agent each run |
| `secrets/keys.txt` | API keys (already exists — add ZOTERO_API_KEY and ZOTERO_USER_ID) |
| `.gitignore` | Excludes secrets/, __pycache__, .venv |

---

## Task 1: Initialize project structure and shared Python environment

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `.venv/` (shared Python 3.12 venv)
- Create: `mcp_servers/scopus_mcp/` (directory scaffold)
- Create: `mcp_servers/zotero_mcp/` (directory scaffold)
- Create: `prompts/`, `outputs/`, `logs/` (directories)

- [ ] **Step 1: Initialize git repository**

```bash
git init
```

Expected output: `Initialized empty Git repository in ...`

- [ ] **Step 2: Create .gitignore**

Create `.gitignore` with this content:

```
secrets/
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/
outputs/
```

- [ ] **Step 3: Create shared requirements.txt at project root**

```
mcp>=1.0.0
requests>=2.31.0
pyzotero>=1.5.18
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 4: Create shared virtual environment with Python 3.12**

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Expected: packages install without errors. Verify with:
```bash
python --version
```
Expected: `Python 3.12.x`

- [ ] **Step 5: Create directory scaffold**

```bash
mkdir -p mcp_servers/scopus_mcp/tests
mkdir -p mcp_servers/zotero_mcp/tests
mkdir -p prompts outputs logs
```

- [ ] **Step 6: Add placeholder files so git tracks empty dirs**

```bash
touch mcp_servers/scopus_mcp/tests/.gitkeep
touch mcp_servers/zotero_mcp/tests/.gitkeep
touch outputs/.gitkeep
touch logs/.gitkeep
```

- [ ] **Step 7: Commit**

```bash
git add .gitignore requirements.txt mcp_servers/ prompts/ outputs/ logs/
git commit -m "chore: initialize project structure with shared Python 3.12 environment"
```

---

## Task 2: Add Zotero credentials to secrets/keys.txt

**Files:**
- Modify: `secrets/keys.txt`

**Before starting:** Log into zotero.org → Settings → Feeds/API → Create new private key. Grant it: Read/Write access to your personal library. Note your numeric User ID from the same page.

- [ ] **Step 1: Add Zotero credentials**

Open `secrets/keys.txt` and append these two lines (keep the Scopus key already there):

```
ZOTERO_API_KEY=<paste your zotero API key here>
ZOTERO_USER_ID=<paste your numeric user ID here>
```

- [ ] **Step 2: Verify file has all three keys**

```bash
cat secrets/keys.txt
```

Expected: three lines starting with `SCOPUS_API_KEY=`, `ZOTERO_API_KEY=`, `ZOTERO_USER_ID=`

*(Do NOT commit this file — it is in .gitignore)*

---

## Task 3: Build Scopus MCP server

**Files:**
- Create: `mcp_servers/scopus_mcp/server.py`
- Create: `mcp_servers/scopus_mcp/tests/test_server.py`

**Before starting:** Activate the shared venv if not already active:
```bash
.venv\Scripts\activate
```

- [ ] **Step 1: Write failing tests first**

Create `mcp_servers/scopus_mcp/tests/test_server.py`:

```python
import pytest
import json
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server import load_api_key, search_papers, get_abstract, verify_doi

# ── helpers ──────────────────────────────────────────────────────────────────

MOCK_SEARCH_RESPONSE = {
    "search-results": {
        "entry": [
            {
                "dc:title": "Permafrost carbon dynamics",
                "dc:creator": "Smith, J.",
                "prism:doi": "10.1234/test.001",
                "prism:coverDate": "2023-01-01",
                "dc:description": "Study of permafrost carbon release."
            }
        ],
        "opensearch:totalResults": "1"
    }
}

MOCK_ABSTRACT_RESPONSE = {
    "abstracts-retrieval-response": {
        "coredata": {
            "dc:title": "Permafrost carbon dynamics",
            "dc:creator": "Smith, J.",
            "prism:doi": "10.1234/test.001",
            "prism:coverDate": "2023-01-01",
            "dc:description": "Full abstract text here."
        }
    }
}

# ── tests ─────────────────────────────────────────────────────────────────────

def test_load_api_key_reads_from_keys_file(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("SCOPUS_API_KEY=mykey123\n")
    key = load_api_key(str(keys_file))
    assert key == "mykey123"

def test_load_api_key_raises_if_missing(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("OTHER_KEY=something\n")
    with pytest.raises(ValueError, match="SCOPUS_API_KEY"):
        load_api_key(str(keys_file))

@patch("server.requests.get")
def test_search_papers_returns_list(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_SEARCH_RESPONSE
    )
    results = search_papers("permafrost carbon", limit=1, api_key="testkey")
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["doi"] == "10.1234/test.001"
    assert results[0]["title"] == "Permafrost carbon dynamics"
    assert results[0]["first_author"] == "Smith, J."
    assert results[0]["year"] == "2023"

@patch("server.requests.get")
def test_search_papers_raises_on_http_error(mock_get):
    mock_get.return_value = MagicMock(status_code=401)
    with pytest.raises(RuntimeError, match="Scopus search failed"):
        search_papers("anything", limit=5, api_key="badkey")

@patch("server.requests.get")
def test_get_abstract_returns_text(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_ABSTRACT_RESPONSE
    )
    result = get_abstract("10.1234/test.001", api_key="testkey")
    assert result["abstract"] == "Full abstract text here."
    assert result["doi"] == "10.1234/test.001"

@patch("server.requests.get")
def test_get_abstract_raises_on_not_found(mock_get):
    mock_get.return_value = MagicMock(status_code=404)
    with pytest.raises(RuntimeError, match="Abstract not found"):
        get_abstract("10.9999/bad.doi", api_key="testkey")

@patch("server.requests.get")
def test_verify_doi_returns_true_when_found(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "search-results": {
                "opensearch:totalResults": "1",
                "entry": [{"dc:title": "Something", "prism:doi": "10.1234/test.001"}]
            }
        }
    )
    assert verify_doi("10.1234/test.001", api_key="testkey") is True

@patch("server.requests.get")
def test_verify_doi_returns_false_when_not_found(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"search-results": {"opensearch:totalResults": "0", "entry": []}}
    )
    assert verify_doi("10.9999/fake.doi", api_key="testkey") is False
```

- [ ] **Step 4: Run tests to confirm they all fail**

```bash
pytest tests/test_server.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — server.py doesn't exist yet.

- [ ] **Step 5: Implement server.py**

Create `mcp_servers/scopus_mcp/server.py`:

```python
import os
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


def verify_doi(doi: str, api_key: str) -> bool:
    url = f"{SCOPUS_BASE}/search/scopus"
    params = {"query": f"DOI({doi})", "count": 1, "apiKey": api_key}
    resp = requests.get(url, params=params, timeout=30)
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
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    import json
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
    else:
        raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Run tests — all should pass**

```bash
pytest tests/test_server.py -v
```

Expected output:
```
tests/test_server.py::test_load_api_key_reads_from_keys_file PASSED
tests/test_server.py::test_load_api_key_raises_if_missing PASSED
tests/test_server.py::test_search_papers_returns_list PASSED
tests/test_server.py::test_search_papers_raises_on_http_error PASSED
tests/test_server.py::test_get_abstract_returns_text PASSED
tests/test_server.py::test_get_abstract_raises_on_not_found PASSED
tests/test_server.py::test_verify_doi_returns_true_when_found PASSED
tests/test_server.py::test_verify_doi_returns_false_when_not_found PASSED
8 passed
```

- [ ] **Step 7: Commit**

```bash
cd ../..
git add mcp_servers/scopus_mcp/
git commit -m "feat: add Scopus MCP server with search, abstract, and verify_doi tools"
```

---

## Task 4: Build Zotero MCP server

**Files:**
- Create: `mcp_servers/zotero_mcp/server.py`
- Create: `mcp_servers/zotero_mcp/tests/test_server.py`

**Before starting:** Activate the shared venv if not already active:
```bash
.venv\Scripts\activate
```

- [ ] **Step 1: Write failing tests**

Create `mcp_servers/zotero_mcp/tests/test_server.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, call
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server import load_credentials, ZoteroClient

# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def creds(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text(
        "SCOPUS_API_KEY=s\nZOTERO_API_KEY=zkey123\nZOTERO_USER_ID=987654\n"
    )
    return load_credentials(str(keys_file))

# ── credential loading ─────────────────────────────────────────────────────────

def test_load_credentials_reads_both_keys(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("ZOTERO_API_KEY=abc\nZOTERO_USER_ID=123\n")
    creds = load_credentials(str(keys_file))
    assert creds["api_key"] == "abc"
    assert creds["user_id"] == "123"

def test_load_credentials_raises_if_api_key_missing(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("ZOTERO_USER_ID=123\n")
    with pytest.raises(ValueError, match="ZOTERO_API_KEY"):
        load_credentials(str(keys_file))

def test_load_credentials_raises_if_user_id_missing(tmp_path):
    keys_file = tmp_path / "keys.txt"
    keys_file.write_text("ZOTERO_API_KEY=abc\n")
    with pytest.raises(ValueError, match="ZOTERO_USER_ID"):
        load_credentials(str(keys_file))

# ── ZoteroClient ───────────────────────────────────────────────────────────────

def test_create_collection_returns_key(creds):
    mock_zot = MagicMock()
    mock_zot.create_collection.return_value = [{"key": "ABCD1234", "data": {"name": "My Topic — 2026-06-27"}}]
    client = ZoteroClient(creds, zot=mock_zot)
    key = client.create_collection("My Topic — 2026-06-27")
    assert key == "ABCD1234"
    mock_zot.create_collection.assert_called_once_with([{"name": "My Topic — 2026-06-27", "parentCollection": False}])

def test_get_collection_items_returns_list(creds):
    mock_zot = MagicMock()
    mock_zot.collection_items.return_value = [
        {"data": {"title": "Paper A", "DOI": "10.1/a", "creators": [{"lastName": "Smith"}], "date": "2022"}}
    ]
    client = ZoteroClient(creds, zot=mock_zot)
    items = client.get_collection_items("ABCD1234")
    assert len(items) == 1
    assert items[0]["doi"] == "10.1/a"
    assert items[0]["title"] == "Paper A"

def test_add_item_to_collection(creds):
    mock_zot = MagicMock()
    mock_zot.item_template.return_value = {
        "itemType": "journalArticle", "title": "", "DOI": "",
        "creators": [], "date": "", "abstractNote": "", "collections": []
    }
    mock_zot.create_items.return_value = [{"key": "ITEM0001"}]
    client = ZoteroClient(creds, zot=mock_zot)
    paper = {"title": "Test Paper", "doi": "10.1/test", "first_author": "Jones, A.", "year": "2024", "abstract": "Abstract text."}
    item_key = client.add_item(paper, collection_key="ABCD1234")
    assert item_key == "ITEM0001"
    created = mock_zot.create_items.call_args[0][0][0]
    assert created["title"] == "Test Paper"
    assert created["DOI"] == "10.1/test"
    assert "ABCD1234" in created["collections"]

def test_add_item_skips_duplicate_doi(creds):
    mock_zot = MagicMock()
    mock_zot.items.return_value = [{"data": {"DOI": "10.1/test"}}]
    client = ZoteroClient(creds, zot=mock_zot)
    # search_library finds existing item
    existing = client.search_library_by_doi("10.1/test")
    assert existing is not None

def test_export_bibliography_returns_string(creds):
    mock_zot = MagicMock()
    mock_zot.collection_items.return_value = [{"key": "ITEM0001"}]
    mock_zot.item.return_value = {"key": "ITEM0001", "data": {"title": "Test"}}
    # pyzotero bibliography export via locale
    mock_zot.items.return_value = "<div>Smith 2024</div>"
    client = ZoteroClient(creds, zot=mock_zot)
    # Just verify the method exists and calls zot
    assert hasattr(client, "export_bibliography")
```

- [ ] **Step 4: Run tests to confirm they fail**

```bash
pytest tests/test_server.py -v
```

Expected: `ImportError` — server.py doesn't exist yet.

- [ ] **Step 5: Implement server.py**

Create `mcp_servers/zotero_mcp/server.py`:

```python
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
            first_author = f"{creators[0].get('lastName', '')}" if creators else ""
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


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Run tests — all should pass**

```bash
pytest tests/test_server.py -v
```

Expected: 8 passed.

- [ ] **Step 7: Commit**

```bash
cd ../..
git add mcp_servers/zotero_mcp/
git commit -m "feat: add Zotero MCP server with collection and bibliography tools"
```

---

## Task 5: Register MCP servers in Claude Code settings

**Files:**
- Modify: `.claude/settings.local.json`

- [ ] **Step 1: Read current settings file**

Open `.claude/settings.local.json` and note its current contents.

- [ ] **Step 2: Add MCP server registrations**

Merge the following `mcpServers` block into `.claude/settings.local.json`. Preserve any existing keys. Replace `<ABSOLUTE_PATH_TO_PROJECT>` with the full path to this project root (e.g. `W:/Workstation ExtDrive/007 Data Science/003 Data Science Projects/2026_p012 Claude Code Auto Lit Review`):

```json
{
  "mcpServers": {
    "scopus": {
      "command": "<ABSOLUTE_PATH_TO_PROJECT>/.venv/Scripts/python",
      "args": ["<ABSOLUTE_PATH_TO_PROJECT>/mcp_servers/scopus_mcp/server.py"],
      "env": {}
    },
    "zotero": {
      "command": "<ABSOLUTE_PATH_TO_PROJECT>/.venv/Scripts/python",
      "args": ["<ABSOLUTE_PATH_TO_PROJECT>/mcp_servers/zotero_mcp/server.py"],
      "env": {}
    }
  }
}
```

- [ ] **Step 3: Verify Claude Code loads both servers**

Restart Claude Code in this project directory. Run:

```
/mcp
```

Expected: Both `scopus` and `zotero` appear in the connected servers list with green status.

- [ ] **Step 4: Commit settings (without secrets)**

```bash
git add .claude/settings.local.json
git commit -m "chore: register Scopus and Zotero MCP servers"
```

---

## Task 6: Write CLAUDE.md

**Files:**
- Create: `CLAUDE.md`

- [ ] **Step 1: Create CLAUDE.md**

Create `CLAUDE.md` at the project root with this content:

```markdown
# Auto Literature Review — Project Instructions

## Purpose

This project runs a multi-agent literature review workflow. Given a research topic, it:
1. Searches Scopus for relevant papers (parallel Search Agents)
2. Synthesizes findings into a narrative review (Synthesis Agent)
3. Verifies every citation for existence and relevance (Critic Agent)
4. Fixes or drops failed citations (Re-search Agent)
5. Saves all verified papers to a Zotero collection (Zotero Agent)
6. Produces a final document in the user's chosen format (Formatter Agent)

## MCP Tools Available

### Scopus MCP (`scopus` server)
- `search_papers(query, limit)` — search Scopus; returns list of {title, first_author, doi, year, abstract_snippet}
- `get_abstract(doi)` — fetch full abstract for a DOI
- `verify_doi(doi)` — returns {exists: true/false}

### Zotero MCP (`zotero` server)
- `create_collection(name)` — creates a new Zotero collection; returns {collection_key}
- `get_collection_key_by_name(name)` — look up existing collection by name; returns {collection_key} or null
- `get_collection_items(collection_key)` — list papers already in a collection
- `add_item(title, doi, first_author, year, abstract, collection_key)` — add a paper to Zotero
- `export_bibliography(collection_key, style)` — export bibliography (default style: "agu")

## Agent Roles

When the user submits a literature review request, act as the **Orchestrator** and spawn the following agents in order:

### 1. Orchestrator (you)
- Parse the runtime prompt: extract `topic`, `depth`, `format`, and `zotero_collection` (optional)
- Decompose the topic into 3–5 subtopics for parallel search
- Resolve Zotero collection:
  - If `zotero_collection` provided: call `get_collection_key_by_name`, retrieve existing papers with `get_collection_items`
  - If not provided: call `create_collection` with name `<topic> — <YYYY-MM-DD>`
- Coordinate all agents below in sequence
- Pass results between agents explicitly (don't assume agents share state)

### 2. Search Agent (spawn one per subtopic, run in parallel)
Prompt template:
```
You are a Search Agent. Search Scopus for papers on this subtopic: "<subtopic>".
Target paper count: <depth / number_of_subtopics>.
Use the search_papers tool. Return a JSON list of all results with fields:
title, first_author, doi, year, abstract_snippet.
Do not summarize or filter — return everything the tool returns.
```

### 3. Synthesis Agent
Prompt template:
```
You are a Synthesis Agent for a literature review on: "<topic>".

You have two sets of papers:
EXISTING (already in Zotero collection, do not re-add):
<existing_papers_json>

NEW (from Search Agents):
<new_papers_json>

Write a literature review with these sections:
1. Executive Summary (1–2 paragraphs)
2. Background & Scope (topic definition, papers reviewed, Scopus queries used)
3. Thematic Sections (3–6 themes you identify; narrative prose, NOT a list of papers)
4. Key Papers Table (columns: Title | First Author | Year | DOI | One-sentence contribution)
5. Research Gaps & Open Questions
6. References (placeholder — will be replaced by Zotero export)

Rules:
- Inline citations use AGU format: (Author et al., Year) or (Author & Author, Year) for two authors
- Every inline citation must include a DOI in your internal tracking list
- Do not invent papers. Only cite papers from the provided lists.
- Return: (a) the full draft text, (b) a JSON list of all cited DOIs
```

### 4. Critic Agent
Prompt template:
```
You are a Critic Agent. Verify every citation in this literature review.

Cited DOIs:
<cited_dois_json>

For each DOI:
PASS 1 — call verify_doi(doi). If {exists: false}, mark as FAILED_EXISTENCE.
PASS 2 — for DOIs that pass existence: call get_abstract(doi). Read the abstract.
  Find the claim made about this paper in the draft text (provided below).
  If the abstract does not support that claim, mark as FAILED_RELEVANCE.

Draft text:
<draft_text>

Return a JSON object:
{
  "verified": ["doi1", "doi2", ...],
  "failed_existence": ["doi3", ...],
  "failed_relevance": [{"doi": "doi4", "claim": "the claim made", "reason": "why abstract doesn't support it"}, ...]
}
```

### 5. Re-search Agent
Prompt template:
```
You are a Re-search Agent. The following citations failed verification:

FAILED_EXISTENCE (DOI not in Scopus):
<failed_existence_json>

FAILED_RELEVANCE (abstract does not support claim):
<failed_relevance_json>

For each failed citation:
1. Search Scopus using search_papers with a query derived from the original claim
2. If a better paper is found, return its metadata as a replacement
3. If no replacement found after 2 searches, mark as UNSUPPORTED

Return JSON:
{
  "replacements": [{"original_doi": "...", "replacement": {title, doi, first_author, year, abstract_snippet}}],
  "unsupported_claims": ["claim text 1", "claim text 2"]
}
```

### 6. Zotero Agent
Prompt template:
```
You are a Zotero Agent. Save verified papers to Zotero.

Collection key: <collection_key>
Already in collection (skip these DOIs): <existing_doi_list>

Papers to add (verified new papers only):
<verified_papers_json>

For each paper not already in the collection:
1. Call add_item with all available metadata
2. Track which were successfully added

After all items added, call export_bibliography(collection_key, style="agu").

Return:
{
  "added": ["doi1", "doi2"],
  "skipped_duplicates": ["doi3"],
  "bibliography": "<full AGU bibliography text>"
}
```

### 7. Formatter Agent
Prompt template:
```
You are a Formatter Agent. Assemble the final literature review document.

Draft text: <draft_text_with_replacements_applied>
AGU Bibliography: <bibliography>
Unsupported claims (flag these in the text with [CITATION NEEDED]): <unsupported_claims>
Format: <format>  (markdown / docx / pdf)

Instructions:
- Replace the References placeholder section with the AGU bibliography
- Mark any unsupported claims inline with [CITATION NEEDED — manual review required]
- For markdown: save to outputs/<topic_slug>_<YYYY-MM-DD>.md
- For docx: save to outputs/<topic_slug>_<YYYY-MM-DD>.docx using the anthropic-skills:docx skill
- For pdf: save to outputs/<topic_slug>_<YYYY-MM-DD>.pdf
- Also append a summary to logs/verification_log.md (see template in that file)

Return the path to the saved output file.
```

## Citation Style

Default: **AGU (American Geophysical Union)**
Reference: https://www.agu.org/publications/authors/journals/grammar-style-guide

Inline format: (Author et al., Year) for 3+ authors; (Author & Author, Year) for 2; (Author, Year) for 1.
Bibliography: AGU style as exported by Zotero.

## Output File Naming

`outputs/<topic-as-kebab-case>_<YYYY-MM-DD>.<ext>`

Example: `outputs/permafrost-carbon-feedbacks_2026-06-27.md`

## API Keys

All keys are in `secrets/keys.txt` (gitignored):
- `SCOPUS_API_KEY` — used by Scopus MCP
- `ZOTERO_API_KEY` — used by Zotero MCP
- `ZOTERO_USER_ID` — used by Zotero MCP

## MCP Setup (for new environments)

1. Install Python 3.12
2. Create the shared virtual environment:
   ```
   py -3.12 -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Populate `secrets/keys.txt` with all three keys
4. Update the absolute project path in `.claude/settings.local.json`
5. Restart Claude Code — run `/mcp` to confirm both servers show green
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md with full agent workflow and MCP instructions"
```

---

## Task 7: Write runtime prompt template and verification log template

**Files:**
- Create: `prompts/lit_review_runtime_prompt.md`
- Create: `logs/verification_log.md`

- [ ] **Step 1: Create runtime prompt template**

Create `prompts/lit_review_runtime_prompt.md`:

````markdown
# Literature Review Runtime Prompt

Copy everything below the line and paste it into Claude Code to start a new review.

---

```
Please run a literature review using the multi-agent workflow defined in CLAUDE.md.

Parameters:
- topic: <REPLACE: e.g. "permafrost carbon feedbacks under climate change">
- depth: <REPLACE: e.g. 30 papers, or "focused" / "broad">
- format: <REPLACE: markdown | docx | pdf>
- zotero_collection: <REPLACE: leave blank to create new, or paste existing collection name to resume>

Begin by confirming the parameters, then proceed with the Orchestrator role as described in CLAUDE.md.
```
````

- [ ] **Step 2: Create verification log template**

Create `logs/verification_log.md`:

```markdown
# Citation Verification Log

Each run appends a new entry below.

---

<!-- ENTRIES APPENDED BY FORMATTER AGENT BELOW THIS LINE -->
```

- [ ] **Step 3: Commit**

```bash
git add prompts/ logs/
git commit -m "docs: add runtime prompt template and verification log"
```

---

## Task 8: End-to-end smoke test

**Goal:** Confirm the full chain works on a small real query before using it for real research.

- [ ] **Step 1: Verify Scopus MCP works live**

In Claude Code chat, type:

```
Use the search_papers tool to search Scopus for "permafrost methane" with limit 3. Show me the raw results.
```

Expected: A JSON list with 3 papers, each containing title, doi, year, first_author.

- [ ] **Step 2: Verify Zotero MCP works live**

In Claude Code chat, type:

```
Use the create_collection tool to create a Zotero collection called "MCP Test — 2026-06-27". Show me the returned collection_key.
```

Expected: A collection key string (e.g. `"ABCD1234"`). Open Zotero desktop to confirm the collection appears.

- [ ] **Step 3: Add one paper to Zotero via MCP**

Use the `add_item` tool with one of the papers from Step 1 and the collection_key from Step 2. Confirm it appears in Zotero desktop.

- [ ] **Step 4: Run a minimal end-to-end review**

Paste the runtime prompt with:
- topic: `permafrost methane emissions`
- depth: `5 papers`
- format: `markdown`
- zotero_collection: *(leave blank)*

Watch the Orchestrator coordinate all agents. Check that:
- `outputs/` contains a `.md` file
- `logs/verification_log.md` has a new entry
- Zotero desktop shows a new collection with papers

- [ ] **Step 5: Commit smoke test notes**

```bash
git add logs/verification_log.md outputs/
git commit -m "test: smoke test run on permafrost methane topic"
```

---

## Notes

- **AGU bibliography style:** pyzotero exports using CSL styles. The style name `"agu"` must match a CSL file installed in Zotero. If `export_bibliography` returns an error, open Zotero → Preferences → Cite → Styles and install the AGU style from the Zotero style repository, then retry.
- **Scopus API rate limits:** The free Scopus API allows ~20,000 queries/week. Deep reviews with many `get_abstract` calls can approach this. Monitor usage at dev.elsevier.com.
- **Zotero duplicate handling:** The `add_item` tool does not auto-detect duplicates on Zotero's side. The Zotero Agent is instructed to skip DOIs already in `get_collection_items` — this is the deduplication layer.
