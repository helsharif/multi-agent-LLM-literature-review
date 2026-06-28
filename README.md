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
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code/overview) authenticated with your **Claude Pro or Max subscription** (`npm install -g @anthropic-ai/claude-code`, then `claude` to sign in)
  — the web app uses the `claude --print` command to run AI steps; **no Anthropic API key required**
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

Zotero → Edit → Settings → Cite → Styles → Get additional styles → search "American Geophysical Union" → Install

**5. Restart the Claude Code CLI and verify**

> **Important:** these are local stdio MCP servers — they only work with the **Claude Code CLI** (`claude` in a terminal), not the Claude Code web app (claude.ai/code). The web app uses cloud-hosted connectors and cannot launch local Python processes.

Open a terminal in this project directory and run `claude`. Once inside the CLI, type `/mcp` — both `scopus` and `zotero` should show as connected.

## Running a literature review

### Option A — Web app (FastAPI + Next.js)

The easiest way to run a review. Opens a browser UI where you fill in a form and watch the workflow run live.

**Start both servers with one command** from the project root:

```bash
.venv\Scripts\activate
npm run dev
```

This uses `concurrently` to run the FastAPI backend (port 8000) and the Next.js frontend (port 3000) side-by-side in the same terminal, with colour-coded output for each.

**Open `http://localhost:3000` in your browser.**

Fill in the form:
- **Topic** — describe your research question in detail
- **Search depth** — number of papers to retrieve (recommend 20–30)
- **Download format** — Markdown, Word, or PDF
- **Zotero collection** *(optional)* — leave blank to auto-generate a name

Click **Generate Literature Review** and watch each step complete in real time. When done, the review renders inline and a download button appears.

> **PDF and DOCX notes:**
> - DOCX requires `pip install python-docx` (already in `requirements.txt`)
> - PDF requires `pip install weasyprint markdown` plus system Cairo/Pango libraries.
>   On Windows these are usually present if Visual C++ Redistributable is installed.
>   If PDF fails, switch to Markdown or DOCX in the download format picker.

---

### Option B — Claude Code CLI (original workflow)

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

> **Note:** The CLI workflow requires both MCP servers to be connected (`/mcp` shows `scopus` and `zotero` as connected). The web app does not use MCP — it calls the APIs directly.

## Output

Each review produces:

| File                           | Description                                                       |
| ------------------------------ | ----------------------------------------------------------------- |
| `outputs/<topic>_<date>.<ext>` | Final literature review document                                  |
| `logs/verification_log.md`     | Audit trail: papers found, verified, replaced, unsupported claims |
| Zotero collection              | All verified papers with full metadata                            |

The document structure is: Executive Summary → Background & Scope → Thematic Sections → Key Papers Table → Research Gaps → References.

## MCP servers

| Server   | File                               | Tools                                                                                                        |
| -------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `scopus` | `mcp_servers/scopus_mcp/server.py` | `search_papers`, `get_abstract`, `verify_doi`, `get_full_text`                                               |
| `zotero` | `mcp_servers/zotero_mcp/server.py` | `create_collection`, `get_collection_key_by_name`, `get_collection_items`, `add_item`, `export_bibliography` |

`get_full_text` uses the ScienceDirect API (same Elsevier API key as Scopus). A 403 response means the specific article is not covered by your institutional subscription, even if your key generally includes full text access.

## Running tests

```bash
.venv\Scripts\activate
pytest mcp_servers/scopus_mcp/tests/ -v
pytest mcp_servers/zotero_mcp/tests/ -v
```

## Project structure

```
├── package.json                       # Root-level: `npm run dev` starts both servers via concurrently
├── CLAUDE.md                          # Agent workflow instructions (read by Claude Code)
├── README.md                          # This file
├── requirements.txt                   # Python dependencies (backend + MCP servers)
├── secrets/keys.txt                   # API keys (gitignored)
├── api/
│   ├── main.py                        # FastAPI app — SSE /api/review, /api/download
│   ├── workflow.py                    # Python-orchestrated workflow; uses `claude --print` for AI steps
│   └── convert.py                     # Markdown → DOCX (python-docx) / PDF (weasyprint)
├── frontend/
│   ├── app/page.tsx                   # Main page — form, SSE consumer, state machine
│   ├── components/ReviewForm.tsx      # Topic, depth counter, format picker, Zotero input
│   ├── components/ProgressPanel.tsx   # Live workflow progress display
│   ├── components/ReviewOutput.tsx    # Rendered review + download button
│   └── next.config.ts                 # Proxies /api/* → localhost:8000
├── mcp_servers/
│   ├── scopus_mcp/server.py           # Scopus + ScienceDirect MCP server
│   └── zotero_mcp/server.py           # Zotero MCP server
├── prompts/
│   └── lit_review_runtime_prompt.md   # Copy-paste prompt template (CLI mode)
├── outputs/                           # Generated literature reviews (gitignored)
├── logs/
│   └── verification_log.md            # Citation audit trail
└── docs/superpowers/
    ├── specs/                         # Design specification
    └── plans/                         # Implementation plan
```
