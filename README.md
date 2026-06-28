# Auto Literature Review

A multi-agent Claude Code workflow that produces grounded, verifiable literature reviews on any research topic. Every citation is checked for existence in Scopus and relevance to the claim it supports. Verified papers are saved to Zotero and the final bibliography is exported in AGU citation style.

## What it does

Given a topic, depth, and output format, the workflow:

1. Decomposes the topic into subtopics and searches Scopus in parallel
2. Synthesizes findings into a structured narrative review with inline AGU citations
3. Verifies every citation — existence (DOI in Scopus) and relevance (abstract supports the claim)
4. Replaces failed citations or flags unsupported claims for manual review
5. Saves all verified papers to a Zotero collection (creates one per topic, or resumes an existing one)
6. Exports a full AGU bibliography from Zotero and assembles the final document

## Prerequisites

- Python 3.12
- [Claude Code](https://claude.ai/code)
- Zotero desktop (local install)
- Elsevier developer account with API keys for Scopus and ScienceDirect

## Setup

**1. Clone and create the virtual environment**

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**2. Add API keys**

Create `secrets/keys.txt` (gitignored):

```
SCOPUS_API_KEY=<your Elsevier API key>
ZOTERO_API_KEY=<your Zotero API key>
ZOTERO_USER_ID=<your Zotero numeric user ID>
```

- Elsevier API key: [dev.elsevier.com](https://dev.elsevier.com) → My API Key
- Zotero API key + user ID: zotero.org/settings/keys → Create new private key (Read/Write access)

**3. Configure Claude Code MCP servers**

In `.claude/settings.local.json`, add the `mcpServers` block with the absolute path to this project:

```json
{
  "mcpServers": {
    "scopus": {
      "command": "<ABSOLUTE_PATH>\\.venv\\Scripts\\python",
      "args": ["<ABSOLUTE_PATH>\\mcp_servers\\scopus_mcp\\server.py"],
      "env": {}
    },
    "zotero": {
      "command": "<ABSOLUTE_PATH>\\.venv\\Scripts\\python",
      "args": ["<ABSOLUTE_PATH>\\mcp_servers\\zotero_mcp\\server.py"],
      "env": {}
    }
  }
}
```

**4. Install AGU citation style in Zotero**

Zotero → Edit → Preferences → Cite → Styles → Get additional styles → search "American Geophysical Union" → Install

**5. Restart Claude Code and verify**

Run `/mcp` — both `scopus` and `zotero` should show as connected.

## Running a literature review

Copy the prompt template from [`prompts/lit_review_runtime_prompt.md`](prompts/lit_review_runtime_prompt.md), fill in your parameters, and paste it into Claude Code:

```
Please run a literature review using the multi-agent workflow defined in CLAUDE.md.

Parameters:
- topic: "permafrost carbon feedbacks under climate change"
- depth: 30 papers
- format: markdown
- zotero_collection: (leave blank to create new)
```

To **resume an existing review** (add new papers to an existing Zotero collection), provide the collection name:

```
- zotero_collection: "Permafrost Carbon Feedbacks — 2026-06-27"
```

## Output

Each review produces:

| File | Description |
|---|---|
| `outputs/<topic>_<date>.<ext>` | Final literature review document |
| `logs/verification_log.md` | Audit trail: papers found, verified, replaced, unsupported claims |
| Zotero collection | All verified papers with full metadata |

The document structure is: Executive Summary → Background & Scope → Thematic Sections → Key Papers Table → Research Gaps → References.

## MCP servers

| Server | File | Tools |
|---|---|---|
| `scopus` | `mcp_servers/scopus_mcp/server.py` | `search_papers`, `get_abstract`, `verify_doi`, `get_full_text` |
| `zotero` | `mcp_servers/zotero_mcp/server.py` | `create_collection`, `get_collection_key_by_name`, `get_collection_items`, `add_item`, `export_bibliography` |

`get_full_text` uses the ScienceDirect API (same Elsevier API key as Scopus). Full text access requires institutional subscription; a 403 response means the paper is paywalled.

## Running tests

```bash
.venv\Scripts\activate
pytest mcp_servers/scopus_mcp/tests/ -v
pytest mcp_servers/zotero_mcp/tests/ -v
```

## Project structure

```
├── CLAUDE.md                          # Agent workflow instructions (read by Claude Code)
├── README.md                          # This file
├── requirements.txt                   # Shared Python dependencies
├── secrets/keys.txt                   # API keys (gitignored)
├── mcp_servers/
│   ├── scopus_mcp/server.py           # Scopus + ScienceDirect MCP server
│   └── zotero_mcp/server.py           # Zotero MCP server
├── prompts/
│   └── lit_review_runtime_prompt.md   # Copy-paste prompt template
├── outputs/                           # Generated literature reviews (gitignored)
├── logs/
│   └── verification_log.md            # Citation audit trail
└── docs/superpowers/
    ├── specs/                         # Design specification
    └── plans/                         # Implementation plan
```
