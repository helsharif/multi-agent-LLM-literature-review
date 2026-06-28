# Auto Literature Review

A local FastAPI and Next.js app for producing Scopus-grounded literature reviews with Zotero bibliography management. The workflow searches Scopus, drafts a structured review with a selectable LLM backend, verifies cited DOIs, saves verified papers to Zotero, exports an AGU bibliography, and writes the final review to `outputs/`.

## What It Does

Given a topic, search depth, output format, optional Zotero collection, and LLM backend, the app:

1. Creates or resumes a Zotero collection.
2. Uses the selected LLM to create a concise Zotero collection title when no collection name is provided.
3. Uses the selected LLM to decompose the topic into Scopus search subtopics.
4. Searches Scopus for relevant papers and deduplicates by DOI.
5. Uses the selected LLM to synthesize a narrative literature review.
6. Parses the review's `CITED_DOIS` marker and verifies DOI existence in Scopus.
7. Saves verified new papers to Zotero.
8. Exports an AGU bibliography from Zotero.
9. Saves the final Markdown review and supports DOCX/PDF download conversion.

## Prerequisites

- Python 3.12
- Node.js and npm
- Zotero desktop
- Elsevier developer API key for Scopus and ScienceDirect
- Zotero API key and numeric user ID
- Claude Code CLI, only if using the Claude backend
- OpenRouter API key, only if using OpenRouter-backed models

## Setup

**1. Create the Python environment**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**2. Install JavaScript dependencies**

From the project root:

```powershell
npm install
npm --prefix frontend install
```

**3. Add secrets**

Create `secrets/keys.txt`:

```text
SCOPUS_API_KEY=<your Elsevier API key>
ZOTERO_API_KEY=<your Zotero API key>
ZOTERO_USER_ID=<your Zotero numeric user ID>
OPENROUTER_API_KEY=<your OpenRouter API key, optional unless using OpenRouter backends>
```

`secrets/keys.txt` is gitignored. Do not commit it.

**4. Install AGU citation style in Zotero**

In Zotero: Edit -> Settings -> Cite -> Styles -> Get additional styles, then search for and install `American Geophysical Union`.

## Running The Web App

From the project root:

```powershell
.venv\Scripts\activate
npm run dev
```

This starts:

- FastAPI backend on `http://127.0.0.1:8000`
- Next.js frontend on `http://localhost:3000`
- A browser opener that waits for the frontend and opens it automatically
- A short terminal help message with the shutdown instruction

To stop the app, press `Ctrl+C` in the terminal running `npm run dev`.

If the browser does not open automatically, go to [http://localhost:3000](http://localhost:3000).

## Web App Inputs

- **Topic**: detailed research question or review scope.
- **Search depth**: total target papers to retrieve across generated subtopics.
- **LLM backend**: model/provider used for title generation, subtopic planning, and synthesis.
- **Download format**: Markdown, DOCX, or PDF.
- **Zotero collection**: optional. If provided, the app resumes or creates that exact collection name. If blank, the selected LLM generates a concise title.

## LLM Backends

| UI label | Backend ID | Notes |
| --- | --- | --- |
| Claude Code | `claude` | Uses local `claude -p`. Requires Claude Code CLI authentication. |
| OpenRouter Free Router (auto) | `openrouter_free` | Uses `openrouter/free`. Adds routing hints requesting a free text model with large context, long-form synthesis, citation discipline, and structured DOI output. |
| Gemini 2.5 Flash (OpenRouter paid) | `gemini_flash` | Uses OpenRouter model `google/gemini-2.5-flash`. Currently paid on OpenRouter. |
| Qwen3 Coder 480B A35B (free) | `qwen3_coder_free` | Uses OpenRouter model `qwen/qwen3-coder:free`. |
| NVIDIA Nemotron 3 Ultra (free) | `nemotron_ultra_free` | Uses OpenRouter model `nvidia/nemotron-3-ultra-550b-a55b:free`. |
| NVIDIA Nemotron 3 Super (free) | `nemotron_super_free` | Uses OpenRouter model `nvidia/nemotron-3-super-120b-a12b:free`. |

When `openrouter_free` is selected, final review metadata records both:

- that `openrouter/free` was selected
- the model OpenRouter reports it assigned to the synthesis call

Example:

```markdown
- **LLM backend:** OpenRouter Free Router (auto) (selected: openrouter/free; assigned: qwen/qwen3-coder:free)
```

Free OpenRouter routes can hit upstream provider capacity limits. If you see `ResourceExhausted`, `rate limit`, or `Retry after`, wait briefly or choose another backend.

## Output

The app always saves the canonical review as Markdown:

```text
outputs/<brief-topic-slug>_<YYYY-MM-DD>_<llm-code>.md
```

Example:

```text
outputs/sebou-basin-climate-and-water-risk_2026-06-28_orfree.md
```

The in-browser download button can convert that Markdown to:

- Markdown (`.md`)
- Word (`.docx`)
- PDF (`.pdf`)

Downloaded DOCX and PDF files use the same base name, for example `sebou-basin-climate-and-water-risk_2026-06-28_orfree.pdf`.

The final document includes:

- title and metadata
- executive summary
- background and scope
- thematic sections
- key papers table
- research gaps and open questions
- AGU bibliography exported from Zotero

Metadata includes date, original topic, LLM backend, papers reviewed, DOI verification count, replacements, unsupported claims, and Zotero collection key.

## Troubleshooting

**OpenRouter Free shows no OpenRouter activity**

If the app immediately fails with a `422` error mentioning that `openrouter_free` is not allowed, an old FastAPI process is still running. Stop the app with `Ctrl+C`. If needed, stop stale listeners on ports `8000` and `3000`, then run `npm run dev` again.

**Claude session limit**

If Claude fails with `Claude Code session limit reached`, wait until the reset time shown by Claude or rerun with an OpenRouter backend.

**OpenRouter capacity errors**

Free models can be temporarily overloaded by their upstream provider. Rerun after a short wait or choose another backend.

**No progress appears**

Restart `npm run dev` and hard refresh the browser. The frontend now reports non-stream API errors instead of silently spinning.

**PDF export fails**

PDF conversion uses `weasyprint` and `markdown`. If system PDF dependencies are missing on Windows, use Markdown or DOCX.

## Claude Code CLI Workflow

The web app does not require MCP. It calls Scopus and Zotero directly from Python.

The original Claude Code CLI workflow is still documented in `CLAUDE.md` and `prompts/lit_review_runtime_prompt.md`. That mode uses the local MCP server definitions in `.mcp.json`.

To verify MCP servers for the CLI workflow, run Claude Code in this project and use:

```text
/mcp
```

Both `scopus` and `zotero` should be connected.

## MCP Servers

| Server | File | Tools |
| --- | --- | --- |
| `scopus` | `mcp_servers/scopus_mcp/server.py` | `search_papers`, `get_abstract`, `verify_doi`, `get_full_text` |
| `zotero` | `mcp_servers/zotero_mcp/server.py` | `create_collection`, `get_collection_key_by_name`, `get_collection_items`, `add_item`, `export_bibliography` |

`get_full_text` uses the ScienceDirect API. A 403 response usually means the specific article is not covered by your institutional subscription.

## Tests And Checks

```powershell
.venv\Scripts\activate
pytest mcp_servers/scopus_mcp/tests/ -v
pytest mcp_servers/zotero_mcp/tests/ -v
python -m py_compile api\workflow.py api\main.py
npm --prefix frontend run build
```

## Project Structure

```text
├── package.json                       # Root dev script starts API, frontend, browser opener, and help message
├── CLAUDE.md                          # Original Claude Code workflow instructions
├── AGENTS.md                          # Codex/project instructions
├── README.md                          # This file
├── requirements.txt                   # Python dependencies
├── secrets/keys.txt                   # API keys, gitignored
├── .mcp.json                          # MCP server definitions for Claude Code CLI workflow
├── api/
│   ├── main.py                        # FastAPI app, SSE /api/review, /api/download
│   ├── workflow.py                    # Python workflow and selectable LLM backends
│   └── convert.py                     # Markdown to DOCX/PDF conversion
├── frontend/
│   ├── app/page.tsx                   # Main UI and SSE consumer
│   ├── components/ReviewForm.tsx      # Review form and backend selector
│   ├── components/ProgressPanel.tsx   # Live workflow progress
│   ├── components/ReviewOutput.tsx    # Rendered review and download controls
│   └── next.config.mjs                # Proxies /api/* to 127.0.0.1:8000
├── mcp_servers/
│   ├── scopus_mcp/server.py           # Scopus and ScienceDirect MCP server
│   └── zotero_mcp/server.py           # Zotero MCP server
├── prompts/
│   └── lit_review_runtime_prompt.md   # CLI workflow prompt template
├── scripts/
│   ├── dev-instructions.js            # Prints localhost and Ctrl+C shutdown help
│   └── open-dev-browser.js            # Waits for localhost:3000 and opens the browser
├── outputs/                           # Generated Markdown reviews, gitignored
├── logs/                              # Reserved for workflow logs
└── docs/                              # Design notes and plans
```
