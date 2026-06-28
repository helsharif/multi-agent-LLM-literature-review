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
- `get_abstract(doi)` — fetch full abstract for a DOI; returns {doi, title, abstract}
- `verify_doi(doi)` — returns {exists: true/false}

### Zotero MCP (`zotero` server)
- `create_collection(name)` — creates a new Zotero collection; returns {collection_key}
- `get_collection_key_by_name(name)` — look up existing collection by name; returns {collection_key} or null
- `get_collection_items(collection_key)` — list papers already in a collection; returns [{title, doi, first_author, year, zotero_key}]
- `add_item(title, doi, first_author, year, abstract, collection_key)` — add a paper to Zotero; returns {item_key}
- `export_bibliography(collection_key, style)` — export bibliography (default style: "agu"); returns bibliography string

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
- Append a summary entry to logs/verification_log.md with: date, topic, papers found,
  papers verified, papers replaced, unsupported claims count, output file path

Return the path to the saved output file.
```

## Citation Style

Default: **AGU (American Geophysical Union)**
Reference: https://www.agu.org/publications/authors/journals/grammar-style-guide

Inline format: (Author et al., Year) for 3+ authors; (Author & Author, Year) for 2; (Author, Year) for 1.
Bibliography: AGU style as exported by Zotero (`style="agu"` in `export_bibliography`).

**Note on AGU style in Zotero:** The AGU CSL style must be installed in Zotero desktop. If `export_bibliography` returns an error mentioning an unknown style, open Zotero → Edit → Preferences → Cite → Styles, click "Get additional styles", search for "American Geophysical Union" and install it, then retry.

## Output File Naming

`outputs/<topic-as-kebab-case>_<YYYY-MM-DD>.<ext>`

Example: `outputs/permafrost-carbon-feedbacks_2026-06-27.md`

## API Keys

All keys are in `secrets/keys.txt` (gitignored — never commit this file):
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
4. Update `.claude/settings.local.json` with absolute paths to this project root
5. Restart Claude Code — run `/mcp` to confirm both `scopus` and `zotero` servers show as connected

## Keeping README.md Current

Update `README.md` whenever significant changes are made to this project — new MCP tools, new agents, new runtime parameters, changed setup steps, or new output formats. The README is the entry point for anyone setting up this project fresh.
