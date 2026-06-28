# Design Spec: Multi-Agent Automated Literature Review
**Date:** 2026-06-27  
**Project:** 2026_p012 Claude Code Auto Lit Review  
**Status:** Draft — awaiting user approval

---

## 1. Purpose

Build a multi-agent Claude Code workflow that accepts a user-defined topic (and optional depth/format parameters) and produces a grounded, verifiable literature review briefing. Citations are verified for existence and relevance, managed through Zotero, and formatted in AGU citation style.

---

## 2. Architecture

### Agent Roles

| Agent | Responsibility |
|---|---|
| **Orchestrator** | Accepts user input, decomposes topic into subtopics, coordinates all other agents, assembles final output |
| **Search Agent(s)** | Parallel instances — each queries Scopus for one subtopic, returns structured paper metadata |
| **Synthesis Agent** | Merges search results, identifies themes, drafts the narrative review with inline citations |
| **Critic Agent** | Pass 1: verifies each DOI exists in Scopus. Pass 2: fetches abstract and checks it supports the specific claim made |
| **Re-search Agent** | Handles citations flagged by Critic — finds replacement papers or marks claim as "unsupported (needs manual review)" |
| **Zotero Agent** | Creates or resumes a named Zotero Collection, saves verified papers (deduplicating against existing items), exports AGU bibliography |
| **Formatter Agent** | Assembles final document in user-chosen format (Markdown, DOCX, or PDF) |

### Data Flow

```
User Input (topic, depth, format)
        ↓
  Orchestrator Agent
  ├── [parallel] Search Agent × N  ──→  paper metadata (title, authors, year, DOI, abstract snippet)
  ├── Synthesis Agent               ──→  draft review with inline citations
  ├── Critic Agent                  ──→  verified ✓ / flagged ✗ citation list
  ├── Re-search Agent               ──→  replacements for flagged citations
  ├── Zotero Agent                  ──→  library saved + AGU bibliography exported
  └── Formatter Agent               ──→  final document
```

---

## 3. MCP Servers

### 3a. Zotero MCP
- **What it does:** Wraps Zotero's built-in local HTTP API (port 23119) to add/retrieve/export citations
- **Prerequisites:** Enable local API in Zotero → Edit → Preferences → Advanced → Allow other applications to communicate with Zotero
- **MCP package:** `zotero-mcp` (open source, no Better BibTeX required)
- **Tools exposed:** `create_collection`, `get_collection_items`, `add_item`, `search_library`, `export_bibliography`
- **Registration:** `.claude/settings.local.json` under `mcpServers`

### 3b. Scopus MCP (custom)
- **What it does:** Lightweight Python wrapper around the Elsevier Scopus REST API
- **API key location:** `secrets/keys.txt` → `SCOPUS_API_KEY=<value>`
- **Tools exposed:**
  - `search_papers(query, limit)` — full-text search, returns metadata array
  - `get_abstract(doi)` — fetches abstract for a specific DOI
  - `verify_doi(doi)` — confirms DOI resolves to a real Scopus record
- **Implementation:** `mcp_servers/scopus_mcp/server.py` (Python, `mcp` SDK + `requests`)
- **Registration:** `.claude/settings.local.json` under `mcpServers`

---

## 4. Output Document Structure

Every literature review will follow this structure (section depth scales with topic complexity):

1. **Executive Summary** — 1–2 paragraphs; key findings and significance
2. **Background & Scope** — topic definition, date range searched, number of papers reviewed, Scopus query strings used
3. **Thematic Sections** (3–6 sections) — narrative synthesis organized by theme, not by paper; inline AGU citations `(Author et al., 2023)`
4. **Key Papers Table** — title, first author, year, DOI, one-sentence contribution
5. **Research Gaps & Open Questions** — what the literature does not yet resolve
6. **References** — full AGU-formatted bibliography exported from Zotero

---

## 5. Citation Verification Protocol

For every citation in the draft:

1. **Existence check:** `verify_doi(doi)` against Scopus — must return a valid record
2. **Relevance check:** `get_abstract(doi)` → Critic Agent reads abstract and evaluates whether it supports the specific claim it is cited for
3. **Outcome:**
   - Both pass → citation marked `✓ verified`
   - Fails existence → Re-search Agent finds replacement or claim is dropped
   - Fails relevance → Re-search Agent finds better-matched paper; original is flagged in a `verification_log.md` for user review

---

## 6. Runtime Parameters (User Specifies Each Run)

| Parameter | Description | Example |
|---|---|---|
| `topic` | The subject of the literature review | "permafrost carbon feedbacks under climate change" |
| `depth` | Number of papers to target OR qualitative scope | `30` or `"focused"` / `"broad"` |
| `format` | Output file format | `"markdown"`, `"docx"`, `"pdf"` |
| `citation_style` | Override default | default: AGU; override at runtime if needed |
| `zotero_collection` | Resume an existing Zotero collection by name (optional) | `"Permafrost Carbon Feedbacks — 2026-06-27"`; if omitted, creates new collection named `<topic> — YYYY-MM-DD` |

---

## 7. Project File Structure

```
2026_p012 Claude Code Auto Lit Review/
├── CLAUDE.md                          # Standing instructions for Claude Code
├── secrets/
│   └── keys.txt                       # SCOPUS_API_KEY=...
├── mcp_servers/
│   └── scopus_mcp/
│       ├── server.py                  # Custom Scopus MCP server
│       └── requirements.txt
├── prompts/
│   └── lit_review_runtime_prompt.md   # Runtime prompt template
├── outputs/                           # Generated literature reviews
├── logs/
│   └── verification_log.md            # Citation verification audit trail
├── docs/
│   └── superpowers/specs/
│       └── 2026-06-27-auto-lit-review-design.md
└── .claude/
    └── settings.local.json            # MCP server registrations
```

---

## 8. Deliverables (Implementation Targets)

1. `CLAUDE.md` — project instructions, agent role definitions, MCP setup guide
2. `mcp_servers/scopus_mcp/server.py` — custom Scopus MCP with 3 tools
3. `.claude/settings.local.json` — registers both MCP servers
4. `prompts/lit_review_runtime_prompt.md` — copy-paste runtime trigger prompt
5. `logs/verification_log.md` — template for citation audit trail

---

## 9. Out of Scope (v1)

- Web scraping full PDF text (abstracts only via Scopus API)
- Automatic submission to journals
- GUI or web interface
- Support for databases other than Scopus
