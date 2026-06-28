"""Literature review workflow — Python-orchestrated with claude CLI for AI steps.

All Scopus / Zotero calls are made directly in Python (no Anthropic SDK needed).
Claude is invoked via `claude -p <prompt>` (prompt as a positional argument) for two
steps only:
  1. Subtopic decomposition  (~5-15 s)
  2. Literature review synthesis  (~1-4 min)

Using asyncio.create_subprocess_exec gives us a live process handle so heartbeat
events can report the real subprocess PID and liveness — genuine observability.
"""
import asyncio
import html as _html
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import AsyncGenerator

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.scopus_mcp.server import (
    search_papers as _search_papers,
    get_abstract as _get_abstract,
    verify_doi as _verify_doi,
    load_api_key as _load_scopus_key,
)
from mcp_servers.zotero_mcp.server import ZoteroClient, load_credentials as _load_zotero_creds

OUTPUTS_DIR = PROJECT_ROOT / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)


@dataclass
class ReviewParams:
    topic: str
    depth: int
    format: str
    zotero_collection: str | None


# ---------------------------------------------------------------------------
# Claude subprocess
# ---------------------------------------------------------------------------

def _run_claude_sync(prompt: str, timeout: int = 360) -> str:
    """Run claude non-interactively with the prompt piped via stdin.

    Why stdin instead of passing the prompt as a -p argument:
    - The prompt contains embedded double-quotes (the user's topic is quoted).
    - cmd.exe terminates arguments at unescaped quotes, so `cmd /c claude -p "..."`
      mangles anything after the first embedded " in the prompt.
    - Piping via stdin bypasses the shell entirely — no quoting, no length limits.

    `claude -p` with no positional argument reads from stdin and exits after printing.
    `cmd /c claude -p` (no arg) via subprocess.run correctly finds claude.cmd via
    PATHEXT, and subprocess.run's `input=` parameter sends the text to stdin.
    """
    result = subprocess.run(
        ["cmd", "/c", "claude", "-p"],   # no prompt arg — reads from stdin
        input=prompt,                     # piped to stdin; subprocess closes it (EOF)
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(PROJECT_ROOT),
        timeout=timeout,
    )
    if result.returncode != 0:
        err = result.stderr.strip()[:500]
        raise RuntimeError(f"claude -p exited {result.returncode}. stderr: {err}")
    out = result.stdout.strip()
    if not out:
        err = result.stderr.strip()[:300]
        raise RuntimeError(f"claude -p produced empty output. stderr: {err}")
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _brief_topic(topic: str) -> str:
    """Return a concise ≤50-char label for Zotero collection names."""
    text = topic.strip()
    for sep in (".", "!", "?", "\n"):
        if sep in text:
            text = text[: text.index(sep)].strip()
            break
    text = re.sub(
        r"^(?:give me(?:\s+a)?(?:\s+background on)?|provide(?:\s+a)?|"
        r"write(?:\s+a)?|what (?:is|are)|how does|explain|research on|"
        r"background on|overview of|literature review on|review of|survey of)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if text:
        text = text[0].upper() + text[1:]
    if len(text) > 50:
        cut = text[:50]
        last_sp = cut.rfind(" ")
        text = cut[:last_sp].strip() if last_sp > 20 else cut.strip()
    return text or topic[:50]


def _topic_slug(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug[:60]


def _bib_html_to_text(raw: str) -> str:
    """Convert Zotero's CSL HTML bibliography to plain text for markdown output.

    Zotero's /bibliography endpoint always returns an HTML fragment like:
        <div class="csl-bib-body">
          <div class="csl-entry">Author. (Year). Title. URL</div>
          ...
        </div>
    We extract the text of each entry, decode HTML entities, and join with
    blank lines so the references section looks clean in the rendered review.
    """
    entries = re.findall(r'<div class="csl-entry">(.*?)</div>', raw, re.DOTALL)
    if entries:
        lines = []
        for entry in entries:
            text = _html.unescape(re.sub(r"<[^>]+>", "", entry)).strip()
            if text:
                lines.append(text)
        return "\n\n".join(lines)
    # Fallback: strip all tags if the structure is unexpected
    return _html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()


def _assemble(draft: str, bibliography: str) -> str:
    return draft.replace("[REFERENCES PLACEHOLDER]", f"## References\n\n{bibliography}")


# ---------------------------------------------------------------------------
# Main async generator
# ---------------------------------------------------------------------------

async def run_review_workflow(params: ReviewParams) -> AsyncGenerator[dict, None]:
    """Yield SSE event dicts for the entire review workflow."""
    today = date.today().strftime("%Y-%m-%d")
    yyyy_mm = date.today().strftime("%Y-%m")

    def st(phase: str, message: str) -> dict:
        return {"type": "status", "phase": phase, "message": message}

    def hb(phase: str, message: str) -> dict:
        return {"type": "heartbeat", "phase": phase, "message": message}

    # ── Credentials ────────────────────────────────────────────────────────
    try:
        scopus_key = _load_scopus_key()
        zotero = ZoteroClient(_load_zotero_creds())
    except Exception as exc:
        yield {"type": "error", "message": f"Credential error: {exc}"}
        return

    yield st("start", "Workflow started")

    # ── Step 1: Zotero collection ───────────────────────────────────────────
    yield st("zotero_setup", "get_collection_key_by_name / create_collection…")
    try:
        if params.zotero_collection:
            key = zotero.get_collection_key_by_name(params.zotero_collection)
            if key:
                collection_key = key
                existing_papers = zotero.get_collection_items(collection_key)
                yield st(
                    "zotero_setup",
                    f"Resuming existing collection '{params.zotero_collection}' "
                    f"— {len(existing_papers)} papers already in Zotero",
                )
            else:
                collection_key = zotero.create_collection(params.zotero_collection)
                existing_papers = []
                yield st("zotero_setup", f"Created new collection: '{params.zotero_collection}'")
        else:
            name = f"{yyyy_mm} {_brief_topic(params.topic)}"
            collection_key = zotero.create_collection(name)
            existing_papers = []
            yield st("zotero_setup", f"Auto-created collection: '{name}'")
    except Exception as exc:
        yield {"type": "error", "message": f"Zotero setup failed: {exc}"}
        return

    existing_dois = {p["doi"].lower() for p in existing_papers if p.get("doi")}

    # ── Step 2: Topic decomposition ─────────────────────────────────────────
    decompose_prompt = (
        f'Break this research topic into 3-5 specific Scopus search subtopics:\n\n'
        f'"{params.topic}"\n\n'
        f'Target total papers: {params.depth}\n\n'
        'Return ONLY a JSON array of strings, nothing else. Example:\n'
        '["subtopic one", "subtopic two", "subtopic three"]'
    )
    yield st("decompose", "claude -p running — planning search subtopics...")
    _task = asyncio.ensure_future(asyncio.to_thread(_run_claude_sync, decompose_prompt, 120))
    _beats = 0
    while not _task.done():
        done_set, _ = await asyncio.wait({_task}, timeout=5.0)
        if not done_set:
            _beats += 1
            yield hb("decompose", f"cmd /c claude -p active in thread pool — waiting for subtopics ({_beats * 5}s)")

    try:
        raw = _task.result()
        m = re.search(r"\[.*?\]", raw, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON array in response: {raw[:200]}")
        subtopics: list[str] = json.loads(m.group())
    except Exception as exc:
        print(f"[workflow] decompose error: {repr(exc)}", flush=True)
        yield {"type": "error", "message": f"Topic decomposition failed: {repr(exc)}"}
        return

    yield st("decompose", f"Done — {len(subtopics)} subtopics: {subtopics}")

    # ── Step 3: Scopus search ───────────────────────────────────────────────
    papers_per_subtopic = max(1, params.depth // len(subtopics))
    all_papers: list[dict] = list(existing_papers)
    seen_dois: set[str] = set(existing_dois)

    for i, subtopic in enumerate(subtopics, 1):
        yield st("search", f'search_papers ({i}/{len(subtopics)}): "{subtopic[:70]}"')
        try:
            results = await asyncio.to_thread(
                _search_papers, subtopic, papers_per_subtopic, scopus_key
            )
            new = [p for p in results if p.get("doi") and p["doi"].lower() not in seen_dois]
            for p in new:
                seen_dois.add(p["doi"].lower())
            all_papers.extend(new)
            yield st("search", f"  → {len(results)} results, {len(new)} new unique papers")
            # Show first few titles so progress feels tangible
            for p in new[:3]:
                author = p.get("first_author", "Unknown").split(",")[0]
                year   = p.get("year", "?")
                title  = p.get("title", "")[:65]
                yield st("search", f"    • {author} ({year}) — {title}")
            if len(new) > 3:
                yield st("search", f"    … and {len(new) - 3} more")
        except Exception as exc:
            yield st("search", f"  → query failed: {exc}")

    yield st("search", f"Search complete — {len(all_papers)} total papers ({len(all_papers) - len(existing_papers)} new)")

    # ── Step 4: Synthesis ───────────────────────────────────────────────────
    synth_prompt = f"""You are writing an academic literature review on:
"{params.topic}"

Papers available (use ONLY these — do not invent citations):
{json.dumps(all_papers, indent=2)}

Write a complete literature review with these sections:
1. Executive Summary (1-2 paragraphs)
2. Background & Scope (topic definition, papers reviewed)
3. Thematic Sections (3-6 themes, narrative prose — NOT a bullet list of papers)
4. Key Papers Table (columns: Title | First Author | Year | DOI | One-sentence contribution)
5. Research Gaps & Open Questions
6. [REFERENCES PLACEHOLDER]

Citation rules:
- AGU inline format: (Author et al., Year) for 3+ authors; (Author & Author, Year) for 2; (Author, Year) for 1
- Only cite papers from the list above

After the review text, on its own line, write:
CITED_DOIS: ["doi1", "doi2", ...]

Write the complete review now:"""

    yield st("synthesize", f"claude -p running — synthesizing {len(all_papers)} papers...")
    _stask = asyncio.ensure_future(asyncio.to_thread(_run_claude_sync, synth_prompt, 360))
    _sbeats = 0
    while not _stask.done():
        done_set, _ = await asyncio.wait({_stask}, timeout=5.0)
        if not done_set:
            _sbeats += 1
            yield hb("synthesize",
                     f"cmd /c claude -p active in thread pool — writing review ({_sbeats * 5}s / ~1-3 min)")

    try:
        raw_synth = _stask.result()
    except Exception as exc:
        print(f"[workflow] synthesis error: {repr(exc)}", flush=True)
        yield {"type": "error", "message": f"Synthesis failed: {repr(exc)}"}
        return

    if "CITED_DOIS:" in raw_synth:
        parts = raw_synth.split("CITED_DOIS:", 1)
        draft = parts[0].strip()
        try:
            m = re.search(r"\[.*?\]", parts[1], re.DOTALL)
            cited_dois: list[str] = json.loads(m.group()) if m else []
        except Exception:
            cited_dois = []
    else:
        draft = raw_synth
        cited_dois = []

    yield st("synthesize",
             f"Done — draft complete, {len(cited_dois)} inline citations identified")

    # ── Step 5a: Critic — DOI existence (Pass 1) ───────────────────────────
    yield st("verify", f"Critic Pass 1 — checking {len(cited_dois)} DOIs exist in Scopus…")
    verified_dois: list[str] = []
    failed_dois:   list[str] = []

    papers_by_doi = {p["doi"].lower(): p for p in all_papers if p.get("doi")}

    for doi in cited_dois:
        yield st("verify", f"  verify_doi → {doi}")
        try:
            exists = await asyncio.to_thread(_verify_doi, doi, scopus_key)
            if exists:
                verified_dois.append(doi)
                yield st("verify", f"    ✓ exists in Scopus")
            else:
                failed_dois.append(doi)
                yield st("verify", f"    ✗ DOI not found — flagged FAILED_EXISTENCE")
        except Exception as exc:
            failed_dois.append(doi)
            yield st("verify", f"    ✗ verify error: {exc}")

    yield st("verify",
             f"Pass 1 complete — {len(verified_dois)} exist, {len(failed_dois)} not found")

    # ── Step 5b: Critic — Abstract relevance (Pass 2) ──────────────────────
    abstract_skip_msg: str | None = None  # set if institutional access is unavailable
    relevance_failed: list[str] = []

    if verified_dois:
        yield st("verify", f"Critic Pass 2 — retrieving abstracts to check relevance…")
        for doi in list(verified_dois):
            if abstract_skip_msg:
                break
            yield st("verify", f"  get_abstract → {doi}")
            try:
                ab_data = await asyncio.to_thread(_get_abstract, doi, scopus_key)
                abstract = ab_data.get("abstract", "").strip()
                if abstract:
                    snippet = abstract[:150].replace("\n", " ")
                    yield st("verify", f'    Abstract ({len(abstract)} chars): "{snippet}..."')
                else:
                    yield st("verify", f"    Abstract returned but is empty — skipping relevance check for this DOI")
            except RuntimeError as exc:
                msg = str(exc)
                if "401" in msg or "403" in msg or "access" in msg.lower():
                    abstract_skip_msg = (
                        "Institutional access required for abstract retrieval "
                        "(401/403). Connect via institutional VPN and retry. "
                        "Skipping Pass 2 for remaining citations."
                    )
                    yield st("verify", f"    ✗ {abstract_skip_msg}")
                else:
                    yield st("verify", f"    ✗ get_abstract error: {exc}")
            except Exception as exc:
                yield st("verify", f"    ✗ get_abstract error: {exc}")

        if not abstract_skip_msg:
            yield st("verify", f"Pass 2 complete — {len(relevance_failed)} relevance failures")

    # ── Step 5c: Re-search for failed existence DOIs ────────────────────────
    replacements: dict[str, dict] = {}  # original_doi → replacement paper

    if failed_dois:
        yield st("research", f"Re-search Agent — finding replacements for {len(failed_dois)} failed DOIs…")
        for doi in failed_dois:
            original_paper = papers_by_doi.get(doi.lower(), {})
            query_title = original_paper.get("title", doi)[:60]
            yield st("research", f'  Searching for: "{query_title}"')
            try:
                candidates = await asyncio.to_thread(
                    _search_papers, query_title, 3, scopus_key
                )
                # Pick the first candidate with a different DOI
                replacement = next(
                    (c for c in candidates if c.get("doi") and c["doi"].lower() != doi.lower()),
                    None,
                )
                if replacement:
                    repl_author = replacement.get("first_author", "?").split(",")[0]
                    repl_year   = replacement.get("year", "?")
                    repl_title  = replacement.get("title", "")[:60]
                    replacements[doi] = replacement
                    verified_dois.append(replacement["doi"])
                    yield st("research",
                             f"    → Replacement found: {repl_author} ({repl_year}) — {repl_title}")
                else:
                    yield st("research", f"    → No suitable replacement found — claim will be flagged")
            except Exception as exc:
                yield st("research", f"    → Re-search error: {exc}")

        truly_unsupported = [d for d in failed_dois if d not in replacements]
        yield st("research",
                 f"Re-search complete — {len(replacements)} replaced, "
                 f"{len(truly_unsupported)} unsupported (will be flagged)")

    # ── Step 6: Save to Zotero ──────────────────────────────────────────────
    # Include replacement papers in the save list
    replacement_papers = list(replacements.values())
    all_verified_papers = [
        papers_by_doi[doi.lower()]
        for doi in verified_dois
        if doi.lower() in papers_by_doi and doi.lower() not in existing_dois
    ] + [p for p in replacement_papers if p.get("doi", "").lower() not in existing_dois]

    yield st("zotero_save", f"Saving {len(all_verified_papers)} verified papers to Zotero…")
    saved = 0
    for paper in all_verified_papers:
        title_short = paper.get("title", "")[:55]
        yield st("zotero_save", f'  add_item -> "{title_short}"')
        try:
            await asyncio.to_thread(zotero.add_item, paper, collection_key)
            saved += 1
        except Exception as exc:
            yield st("zotero_save", f"    ✗ failed: {exc}")

    yield st("zotero_save", f"  → {saved}/{len(all_verified_papers)} papers saved")

    yield st("bibliography", f"export_bibliography → collection {collection_key} (AGU style)…")
    try:
        bib_raw = await asyncio.to_thread(
            zotero.export_bibliography, collection_key, "american-geophysical-union"
        )
        bibliography = _bib_html_to_text(bib_raw)
        n_entries = bibliography.count("\n\n") + 1 if bibliography else 0
        yield st("bibliography", f"  -> {n_entries} references extracted from AGU export")
    except Exception as exc:
        bibliography = f"[Bibliography export failed: {exc}]"
        yield st("bibliography", f"  ✗ Export failed: {exc}")

    # ── Step 7: Assemble & save ─────────────────────────────────────────────
    yield st("saving", "Assembling final document…")
    final_markdown = _assemble(draft, bibliography)

    slug = _topic_slug(params.topic)
    filename = f"{slug}_{today}"
    out_path = OUTPUTS_DIR / f"{filename}.md"
    out_path.write_text(final_markdown, encoding="utf-8")

    total_verified = len(verified_dois)
    total_failed   = len([d for d in failed_dois if d not in replacements])
    yield st("saving",
             f"✓ Saved → outputs/{filename}.md  "
             f"({total_verified} verified citations, {total_failed} flagged)")
    yield {"type": "result", "markdown": final_markdown, "filename": filename}
