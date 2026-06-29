"""Literature review workflow — Python-orchestrated with selectable LLM backends.

All Scopus / Zotero calls are made directly in Python (no Anthropic SDK needed).
The selected LLM backend is used for three text-generation steps:
  0. Zotero collection title generation (falls back locally if unavailable)
  1. Subtopic decomposition  (~5-15 s)
  2. Literature review synthesis  (~1-4 min)
"""
import asyncio
import html as _html
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import AsyncGenerator

import requests

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.scopus_mcp.server import (
    search_papers as _search_papers,
    get_abstract as _get_abstract,
    verify_doi as _verify_doi,
    load_api_key as _load_scopus_key,
)
from mcp_servers.zotero_mcp.server import ZoteroClient, load_credentials as _load_zotero_creds
from api.retrieval import (
    classify_record,
    dedupe_records,
    normalize_doi,
    run_source_safely,
    search_crossref,
    search_data_gov,
    search_openalex,
    search_osti,
    search_semantic_scholar,
    search_serpapi_trusted,
    trusted_url_is_verifiable,
    verify_crossref_doi,
)

OUTPUTS_DIR = PROJECT_ROOT / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)


@dataclass
class ReviewParams:
    topic: str
    depth: int
    format: str
    zotero_collection: str | None
    llm_backend: str = "claude"
    source_categories: list[str] | None = None


@dataclass
class LlmResult:
    text: str
    assigned_model: str | None = None


LLM_BACKENDS: dict[str, dict[str, str]] = {
    "claude": {
        "label": "Claude Code",
        "kind": "claude",
        "model": "claude-cli",
    },
    "gemini_flash": {
        "label": "Gemini 2.5 Flash (OpenRouter paid)",
        "kind": "openrouter",
        "model": "google/gemini-2.5-flash",
    },
    "qwen3_coder_free": {
        "label": "Qwen3 Coder 480B A35B (free)",
        "kind": "openrouter",
        "model": "qwen/qwen3-coder:free",
    },
    "openrouter_free": {
        "label": "OpenRouter Free Router (auto)",
        "kind": "openrouter",
        "model": "openrouter/free",
        "router_hints": "true",
    },
    "nemotron_ultra_free": {
        "label": "NVIDIA Nemotron 3 Ultra (free)",
        "kind": "openrouter",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    },
    "nemotron_super_free": {
        "label": "NVIDIA Nemotron 3 Super (free)",
        "kind": "openrouter",
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
    },
}


class LlmBackendError(RuntimeError):
    """Raised when the selected LLM backend cannot produce a usable response."""


def _backend_config(backend: str) -> dict[str, str]:
    if backend not in LLM_BACKENDS:
        allowed = ", ".join(LLM_BACKENDS)
        raise LlmBackendError(f"Unknown LLM backend '{backend}'. Choose one of: {allowed}.")
    return LLM_BACKENDS[backend]


def _llm_backend_label(backend: str) -> str:
    return _backend_config(backend)["label"]


def _validate_llm_backend_ready(backend: str) -> None:
    config = _backend_config(backend)
    if config["kind"] == "openrouter":
        _load_openrouter_api_key()


# ---------------------------------------------------------------------------
# LLM backends
# ---------------------------------------------------------------------------

class ClaudeCliError(RuntimeError):
    """Raised when the Claude CLI exits before producing a usable response."""

    def __init__(self, message: str, *, returncode: int | None = None, stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _clip_for_error(text: str, limit: int = 800) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}... [truncated]"


def _claude_failure_message(returncode: int, stdout: str, stderr: str) -> str:
    stdout = _clip_for_error(stdout)
    stderr = _clip_for_error(stderr)
    combined = "\n".join(part for part in (stdout, stderr) if part).lower()

    if "session limit" in combined or "usage limit" in combined:
        detail = stdout or stderr or "Claude Code reported a session/usage limit."
        return (
            f"Claude Code session limit reached: {detail} "
            "Wait until the reset time shown by Claude, then rerun the review."
        )
    if "login" in combined or "not authenticated" in combined or "authentication" in combined:
        detail = stdout or stderr or "Claude Code is not authenticated."
        return f"Claude Code authentication failed: {detail} Run `claude` in this project terminal and sign in."

    details = []
    if stderr:
        details.append(f"stderr: {stderr}")
    if stdout:
        details.append(f"stdout: {stdout}")
    if not details:
        details.append("no stdout/stderr captured")
    return f"claude -p exited {returncode}. " + " | ".join(details)

def _run_claude_sync(prompt: str, timeout: int = 360) -> str:
    """Run claude non-interactively with the prompt piped via stdin.

    Why stdin instead of passing the prompt as a -p argument:
    - The prompt contains embedded double-quotes (the user's topic is quoted).
    - cmd.exe terminates arguments at unescaped quotes, so `cmd /c claude -p "..."`
      mangles anything after the first embedded " in the prompt.
    - Piping via stdin bypasses the shell entirely — no quoting, no length limits.

    `claude -p` with no positional argument reads from stdin and exits after printing.
    Calling the resolved Claude executable directly avoids an extra shell layer and
    preserves stdout/stderr separately for useful diagnostics.
    """
    claude_exe = shutil.which("claude")
    if not claude_exe:
        raise ClaudeCliError("Claude Code CLI not found on PATH. Install it, then restart the terminal.")

    result = subprocess.run(
        [claude_exe, "-p"],              # no prompt arg — reads from stdin
        input=prompt,                     # piped to stdin; subprocess closes it (EOF)
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(PROJECT_ROOT),
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ClaudeCliError(
            _claude_failure_message(result.returncode, result.stdout, result.stderr),
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    out = result.stdout.strip()
    if not out:
        raise ClaudeCliError(
            f"claude -p produced empty output. stderr: {_clip_for_error(result.stderr, 300)}",
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    # Strip any ★ Insight blocks that the explanatory-mode session hook may have
    # injected into the subprocess output — they must never appear in review docs.
    out = re.sub(
        r"`★ Insight\s*─+`.*?`─+`",
        "",
        out,
        flags=re.DOTALL,
    ).strip()
    return out


def _load_openrouter_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key

    secrets_path = PROJECT_ROOT / "secrets" / "keys.txt"
    if secrets_path.exists():
        for line in secrets_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "OPENROUTER_API_KEY":
                key = value.strip()
                if key:
                    return key

    raise LlmBackendError(
        "OPENROUTER_API_KEY is required for OpenRouter-backed LLM backends. "
        "Add it to secrets/keys.txt or set it in the environment, then restart `npm run dev`."
    )


def _openrouter_error_detail(payload: dict | None, fallback: str) -> str:
    if not isinstance(payload, dict):
        return _clip_for_error(fallback, 1000)

    error = payload.get("error")
    if not isinstance(error, dict):
        return _clip_for_error(fallback, 1000)

    message = str(error.get("message") or "").strip()
    code = error.get("code")
    metadata = error.get("metadata")
    retry_after = metadata.get("retry_after_seconds") if isinstance(metadata, dict) else None

    detail = message or _clip_for_error(fallback, 1000)
    if code:
        detail = f"{detail} (provider code: {code})"
    if retry_after:
        detail += f" Retry after about {retry_after} seconds."

    lowered = detail.lower()
    if "resourceexhausted" in lowered or "rate-limit" in lowered or "rate limit" in lowered:
        detail += " This is an upstream capacity/rate limit; wait briefly or rerun with another LLM backend."

    return detail


def _with_openrouter_free_router_hints(prompt: str) -> str:
    return (
        "OpenRouter free-router selection hints:\n"
        "- Route this request to a free text LLM suitable for long-context academic literature review.\n"
        "- Prefer a model with a large context window, ideally 64k tokens or more, because the prompt may contain many paper metadata records and abstracts.\n"
        "- Prefer strong instruction following, long-form synthesis, citation discipline, and ability to emit a final machine-readable DOI array.\n"
        "- No image understanding, audio, web browsing, tool calling, or code execution is needed.\n"
        "- The response should be prose plus clearly delimited structured text when requested; do not choose a tiny chat-only model if a larger free model is available.\n\n"
        f"{prompt}"
    )


def _run_openrouter_sync(
    prompt: str,
    model: str,
    timeout: int = 360,
    max_tokens: int = 12000,
    *,
    router_hints: bool = False,
) -> LlmResult:
    api_key = _load_openrouter_api_key()
    request_prompt = _with_openrouter_free_router_hints(prompt) if router_hints else prompt
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "Auto Literature Review",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": request_prompt}],
                "temperature": 0.2,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise LlmBackendError(f"OpenRouter request failed for {model}: {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if response.status_code >= 400:
        detail = _openrouter_error_detail(payload, response.text)
        raise LlmBackendError(f"OpenRouter model {model} failed with HTTP {response.status_code}: {detail}")

    if isinstance(payload, dict) and "error" in payload:
        detail = _openrouter_error_detail(payload, response.text)
        raise LlmBackendError(f"OpenRouter model {model} failed: {detail}")

    try:
        message = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmBackendError(
            f"OpenRouter model {model} returned an unexpected response: {_clip_for_error(response.text, 1000)}"
        ) from exc

    if isinstance(message, list):
        message = "\n".join(part.get("text", "") for part in message if isinstance(part, dict))
    out = str(message).strip()
    if not out:
        raise LlmBackendError(f"OpenRouter model {model} produced empty output.")
    assigned_model = str(payload.get("model") or "").strip() if isinstance(payload, dict) else ""
    return LlmResult(text=out, assigned_model=assigned_model or None)


def _run_llm_result_sync(prompt: str, backend: str, timeout: int = 360, max_tokens: int = 12000) -> LlmResult:
    config = _backend_config(backend)
    if config["kind"] == "claude":
        return LlmResult(text=_run_claude_sync(prompt, timeout), assigned_model=config["model"])
    if config["kind"] == "openrouter":
        return _run_openrouter_sync(
            prompt,
            config["model"],
            timeout,
            max_tokens,
            router_hints=config.get("router_hints") == "true",
        )
    raise LlmBackendError(f"Unsupported LLM backend kind: {config['kind']}")


def _run_llm_sync(prompt: str, backend: str, timeout: int = 360, max_tokens: int = 12000) -> str:
    return _run_llm_result_sync(prompt, backend, timeout, max_tokens).text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _brief_topic_fallback(topic: str) -> str:
    """Regex-only fallback title when Claude is unavailable."""
    text = topic.strip().split("\n")[0]
    for sep in (".", "!", "?"):
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


def _clean_collection_title(raw: str) -> str:
    """Normalize an LLM-generated Zotero collection title."""
    text = raw.strip()
    text = re.sub(r"^```(?:text)?|```$", "", text, flags=re.IGNORECASE).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        text = lines[0]
    text = re.sub(r"^(?:title|collection title)\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().strip('"').strip("'").strip()
    text = re.sub(r"[\s.。:;,-]+$", "", text).strip()
    text = re.sub(r"\s+", " ", text)

    nullish = {"none", "null", "n/a", "na", "not applicable", "untitled", "no title"}
    banned_prefix = re.compile(
        r"^(?:give|review|background|overview|provide|write|explain|literature review)\b",
        re.IGNORECASE,
    )
    if not text or text.lower() in nullish or banned_prefix.search(text):
        return ""

    words = text.split()
    if len(words) > 9:
        text = " ".join(words[:9])
    if len(text) > 50:
        cut = text[:50].rstrip()
        last_sp = cut.rfind(" ")
        text = cut[:last_sp].strip() if last_sp > 20 else cut
    return text


async def _generate_collection_title(topic: str, backend: str, timeout: int = 30) -> str:
    """Ask the selected LLM to synthesise a coherent ≤50-char Zotero title.

    Falls back to the regex approach if the LLM fails or times out so that
    Zotero setup is never blocked by this step.
    """
    prompt = (
        "Create a concise Zotero collection title for a literature review.\n\n"
        f"User topic:\n{topic}\n\n"
        "Synthesize the user's request into a coherent academic collection name. "
        "Do not copy the prompt wording, do not start with verbs like Give/Review/Background, "
        "and do not make a clipped fragment from the first words. Capture the main place, "
        "system, and research angle when possible.\n\n"
        "Requirements:\n"
        "- Maximum 50 characters, strictly\n"
        "- Title Case\n"
        "- 3-7 words preferred\n"
        "- No quotes, colons, trailing punctuation, or filler words\n"
        "- Return ONLY the title text\n\n"
        "Good examples:\n"
        "- Sebou Basin Climate And Water Risk\n"
        "- Permafrost Carbon Feedbacks\n"
        "- Urban Heat And Flood Adaptation\n\n"
        "Title:"
    )
    task = asyncio.ensure_future(asyncio.to_thread(_run_llm_sync, prompt, backend, timeout, 80))
    await asyncio.wait({task}, timeout=timeout + 5)
    if task.done() and not task.exception():
        title = _clean_collection_title(task.result())
        if title:
            return title
    # Fallback — never raise
    return _brief_topic_fallback(topic)


def _topic_slug(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug[:60]


def _filename_slug(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) <= max_len:
        return slug or "literature-review"
    cut = slug[:max_len].rstrip("-")
    last_dash = cut.rfind("-")
    return cut[:last_dash].strip("-") if last_dash > 20 else cut


def _collection_topic_for_filename(collection_name: str, fallback_topic: str) -> str:
    text = collection_name.strip()
    text = re.sub(r"^\d{4}-\d{2}\s+", "", text).strip()
    return text or _brief_topic_fallback(fallback_topic)


def _llm_backend_filename_code(backend: str) -> str:
    codes = {
        "claude": "claude",
        "openrouter_free": "orfree",
        "gemini_flash": "gemini",
        "qwen3_coder_free": "qwen3",
        "nemotron_ultra_free": "nem3ultra",
        "nemotron_super_free": "nem3super",
    }
    return codes.get(backend, re.sub(r"[^a-z0-9]+", "", backend.lower())[:16] or "llm")


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


def _assemble(
    draft: str,
    bibliography: str,
    *,
    topic: str,
    today: str,
    n_papers: int,
    n_verified: int,
    n_replaced: int,
    n_unsupported: int,
    zotero_name: str,
    collection_key: str,
    llm_backend_label: str,
    n_direct: int = 0,
    n_adjacent: int = 0,
    n_transfer: int = 0,
    n_url_verified: int = 0,
) -> str:
    metadata = (
        f"- **Date:** {today}\n"
        f"- **Topic:** {topic}\n"
        f"- **LLM backend:** {llm_backend_label}\n"
        f"- **Papers reviewed:** {n_papers}\n"
        f"- **Papers verified (DOI existence):** {n_verified} / {n_papers}\n"
        f"- **Trusted official no-DOI sources accepted:** {n_url_verified}\n"
        f"- **Direct evidence sources:** {n_direct}\n"
        f"- **Adjacent/background sources:** {n_adjacent}\n"
        f"- **Transfer-only sources excluded:** {n_transfer}\n"
        f"- **Papers replaced:** {n_replaced}\n"
        f"- **Unsupported claims:** {n_unsupported}\n"
        f"- **Zotero collection:** {zotero_name} (key: {collection_key})"
    )
    body = draft.replace("[REFERENCES PLACEHOLDER]", f"## References\n\n{bibliography}")
    # Insert metadata after the first heading line (the title)
    lines = body.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("#"):
            insert_at = i + 1
            break
    lines.insert(insert_at, f"\n{metadata}\n\n---\n")
    return "".join(lines)


def _extract_cited_dois(raw_synth: str) -> tuple[str, list[str]]:
    """Split review text from a trailing CITED_DOIS marker.

    Smaller models often add markdown emphasis around the marker, e.g.
    `**CITED_DOIS**: [...]`; accept those variants so the marker does not leak
    into the final References section and verification still runs.
    """
    marker = re.search(
        r"(?im)^\s*(?:\*\*)?\s*CITED[_\s-]*DOIS\s*(?:\*\*)?\s*:\s*(\[.*?\])\s*$",
        raw_synth,
        flags=re.DOTALL,
    )
    if not marker:
        return raw_synth.strip(), []

    draft = raw_synth[: marker.start()].strip()
    try:
        parsed = json.loads(marker.group(1))
        cited_dois = [str(doi).strip() for doi in parsed if str(doi).strip()]
    except Exception:
        cited_dois = []
    return draft, cited_dois


def _fallback_query_plan(topic: str) -> dict:
    return {
        "direct_queries": [
            topic,
            f'("{topic}" OR "lead service line") AND ("machine learning" OR predictive OR inventory OR replacement)',
            '"lead service line" AND ("machine learning" OR "predictive model" OR inventory OR prioritization)',
            '"lead service line" AND (Flint OR Pittsburgh OR Denver OR "New Jersey")',
        ],
        "adjacent_queries": [
            '"positive unlabeled learning" AND (infrastructure OR utility OR pipe OR environmental)',
            '"spatial cross validation" AND ("machine learning" OR "risk prediction")',
            'equity AND ("water infrastructure" OR "drinking water" OR "lead exposure")',
        ],
        "official_queries": [
            '"lead service line" "predictive modeling"',
            '"lead service line" inventory prioritization',
            '"lead service line" replacement verification utility report',
        ],
        "seed_titles": [
            "Active Remediation: The Search for Lead Pipes in Flint, Michigan",
            "A Data Science Approach to Understanding Residential Water Contamination in Flint",
            "Lead Service Line Identification: A Review of Strategies and Approaches",
            "Predicting Lead Water Service Lines in the Pittsburgh Water and Sewer Authority Service Area",
        ],
    }


def _coerce_query_plan(raw: str, topic: str) -> dict:
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise ValueError("No JSON object found")
        parsed = json.loads(m.group())
    except Exception:
        return _fallback_query_plan(topic)

    fallback = _fallback_query_plan(topic)
    plan = {}
    for key in ("direct_queries", "adjacent_queries", "official_queries", "seed_titles"):
        values = parsed.get(key)
        if not isinstance(values, list):
            values = fallback[key]
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        plan[key] = cleaned[:6] or fallback[key]
    return plan


def _enrich_scopus_record(record: dict, query: str) -> dict:
    out = dict(record)
    out.setdefault("source", "Scopus")
    out.setdefault("source_type", "peer-reviewed article")
    out.setdefault("evidence_tier", "Tier 1")
    out.setdefault("retrieval_query", query)
    out["doi"] = normalize_doi(out.get("doi"))
    return out


def _evidence_counts(records: list[dict]) -> dict[str, int]:
    return {
        "direct": sum(1 for r in records if r.get("relevance_bucket") == "direct"),
        "adjacent": sum(1 for r in records if r.get("relevance_bucket") == "adjacent"),
        "transfer_only": sum(1 for r in records if r.get("relevance_bucket") == "transfer_only"),
    }


def _source_summary(records: list[dict]) -> str:
    counts: dict[str, int] = {}
    for record in records:
        source = record.get("source", "Unknown")
        bucket = record.get("relevance_bucket", "unclassified")
        key = f"{source} / {bucket}"
        counts[key] = counts.get(key, 0) + 1
    return ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))


def _selected_source_categories(params: ReviewParams) -> set[str]:
    allowed = {"scholarly", "official", "trusted_web"}
    selected = {str(value).strip() for value in (params.source_categories or [])}
    selected = selected & allowed
    return selected or {"scholarly", "official"}


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
    try:
        llm_label = _llm_backend_label(params.llm_backend)
        _validate_llm_backend_ready(params.llm_backend)
        yield st("llm_setup", f"LLM backend selected: {llm_label}")
    except Exception as exc:
        yield {"type": "error", "message": f"LLM setup failed: {exc}"}
        return

    # ── Step 1: Zotero collection ───────────────────────────────────────────
    yield st("zotero_setup", "get_collection_key_by_name / create_collection…")
    try:
        if params.zotero_collection:
            key = zotero.get_collection_key_by_name(params.zotero_collection)
            if key:
                collection_key = key
                collection_name = params.zotero_collection
                existing_papers = zotero.get_collection_items(collection_key)
                yield st(
                    "zotero_setup",
                    f"Resuming existing collection '{collection_name}' "
                    f"— {len(existing_papers)} papers already in Zotero",
                )
            else:
                collection_key = zotero.create_collection(params.zotero_collection)
                collection_name = params.zotero_collection
                existing_papers = []
                yield st("zotero_setup", f"Created new collection: '{collection_name}'")
        else:
            yield hb("zotero_setup", "Generating collection title…")
            short_title = await _generate_collection_title(params.topic, params.llm_backend)
            collection_name = f"{yyyy_mm} {short_title}"
            collection_key = zotero.create_collection(collection_name)
            existing_papers = []
            yield st("zotero_setup", f"Auto-created collection: '{collection_name}'")
    except Exception as exc:
        yield {"type": "error", "message": f"Zotero setup failed: {exc}"}
        return

    existing_dois = {p["doi"].lower() for p in existing_papers if p.get("doi")}

    # ── Step 2: Evidence-aware query planning ───────────────────────────────
    decompose_prompt = f"""Create a retrieval query plan for a rigorous literature review.

Topic:
"{params.topic}"

Return ONLY a JSON object with these keys:
- direct_queries: 3-5 scholarly search queries for sources directly studying the topic
- adjacent_queries: 2-4 scholarly queries for background or methods, clearly secondary
- official_queries: 3-5 official/government/utility/professional-society web queries
- seed_titles: 2-5 known direct seed papers/reports when applicable

Rules:
- Prefer exact domain language from the topic over generic method transfer.
- For lead service line topics, include "lead service line", "predictive model", "inventory",
  "Flint", "Pittsburgh", "Denver", and "New Jersey" where useful.
- Do not include unrelated transfer-only domains unless the topic explicitly asks for them.
"""
    yield st("decompose", f"{llm_label} running — planning direct, adjacent, and official searches...")
    _task = asyncio.ensure_future(asyncio.to_thread(_run_llm_sync, decompose_prompt, params.llm_backend, 120, 1000))
    _beats = 0
    while not _task.done():
        done_set, _ = await asyncio.wait({_task}, timeout=5.0)
        if not done_set:
            _beats += 1
            yield hb("decompose", f"{llm_label} active — waiting for subtopics ({_beats * 5}s)")

    try:
        raw = _task.result()
        query_plan = _coerce_query_plan(raw, params.topic)
    except Exception as exc:
        print(f"[workflow] decompose error: {repr(exc)}", flush=True)
        query_plan = _fallback_query_plan(params.topic)

    direct_queries = query_plan["direct_queries"]
    adjacent_queries = query_plan["adjacent_queries"]
    official_queries = query_plan["official_queries"]
    seed_titles = query_plan["seed_titles"]
    selected_sources = _selected_source_categories(params)
    selected_labels = {
        "scholarly": "scholarly literature",
        "official": "official reports & data",
        "trusted_web": "trusted web context",
    }
    yield st(
        "decompose",
        "Done — "
        f"{len(direct_queries)} direct, {len(adjacent_queries)} adjacent, "
        f"{len(official_queries)} official, {len(seed_titles)} seed queries",
    )
    yield st(
        "decompose",
        "Source categories selected: "
        + ", ".join(selected_labels[key] for key in ("scholarly", "official", "trusted_web") if key in selected_sources),
    )

    # ── Step 3: Multi-source retrieval ─────────────────────────────────────
    scholarly_queries = direct_queries + seed_titles
    adjacent_limit = max(1, min(4, params.depth // 8))
    scholarly_limit = max(2, params.depth // max(1, len(scholarly_queries) * 3))
    official_limit = max(2, min(6, params.depth // max(1, len(official_queries))))
    all_papers: list[dict] = [
        classify_record(
            {
                **p,
                "source": "Zotero existing",
                "source_type": "existing Zotero item",
                "evidence_tier": "Tier 1" if p.get("doi") else "Tier 3",
                "retrieval_query": "existing Zotero collection",
            },
            params.topic,
        )
        for p in existing_papers
    ]

    if "scholarly" in selected_sources:
        for i, query in enumerate(scholarly_queries, 1):
            yield st("search", f'Direct scholarly search ({i}/{len(scholarly_queries)}): "{query[:75]}"')
            try:
                results = await asyncio.to_thread(
                    _search_papers, query, scholarly_limit, scopus_key
                )
                all_papers.extend(classify_record(_enrich_scopus_record(p, query), params.topic) for p in results)
                yield st("search", f"  Scopus -> {len(results)} records")
            except Exception as exc:
                yield st("search", f"  Scopus failed: {exc}")

            for source_name, fn in (
                ("OpenAlex", search_openalex),
                ("Semantic Scholar", search_semantic_scholar),
                ("Crossref", search_crossref),
            ):
                records, error = await asyncio.to_thread(run_source_safely, source_name, fn, query, scholarly_limit)
                if records:
                    all_papers.extend(classify_record(record, params.topic) for record in records)
                yield st("search", f"  {source_name} -> {len(records)} records" + (f" ({error})" if error else ""))

        for i, query in enumerate(adjacent_queries, 1):
            yield st("search", f'Adjacent methods/background search ({i}/{len(adjacent_queries)}): "{query[:75]}"')
            for source_name, fn in (
                ("Scopus", lambda q, limit: [_enrich_scopus_record(p, q) for p in _search_papers(q, limit, scopus_key)]),
                ("OpenAlex", search_openalex),
                ("Semantic Scholar", search_semantic_scholar),
            ):
                records, error = await asyncio.to_thread(run_source_safely, source_name, fn, query, adjacent_limit)
                if records:
                    all_papers.extend(classify_record(record, params.topic) for record in records)
                yield st("search", f"  {source_name} -> {len(records)} records" + (f" ({error})" if error else ""))
    else:
        yield st("search", "Skipped scholarly indexes by user selection")

    if "official" in selected_sources or "trusted_web" in selected_sources:
        for i, query in enumerate(official_queries, 1):
            yield st("search", f'Official/trusted-document search ({i}/{len(official_queries)}): "{query[:75]}"')
            source_fns = []
            if "official" in selected_sources:
                source_fns.extend((("Data.gov", search_data_gov), ("OSTI", search_osti)))
            if "official" in selected_sources or "trusted_web" in selected_sources:
                source_fns.append(("SerpAPI trusted web", search_serpapi_trusted))
            for source_name, fn in source_fns:
                records, error = await asyncio.to_thread(run_source_safely, source_name, fn, query, official_limit)
                if records:
                    all_papers.extend(classify_record(record, params.topic) for record in records)
                yield st("search", f"  {source_name} -> {len(records)} records" + (f" ({error})" if error else ""))
    else:
        yield st("search", "Skipped official/trusted web retrieval by user selection")

    all_papers = dedupe_records(all_papers)
    evidence_counts = _evidence_counts(all_papers)
    direct_sources = [p for p in all_papers if p.get("relevance_bucket") == "direct"]
    adjacent_sources = [p for p in all_papers if p.get("relevance_bucket") == "adjacent"]
    transfer_sources = [p for p in all_papers if p.get("relevance_bucket") == "transfer_only"]
    synthesis_sources = [
        p for p in all_papers
        if p.get("relevance_bucket") in {"direct", "adjacent"}
        and p.get("citation_role") != "exclude from synthesis"
    ]
    if not synthesis_sources:
        synthesis_sources = direct_sources + adjacent_sources

    yield st(
        "classify",
        "Evidence governance complete — "
        f"{evidence_counts['direct']} direct, {evidence_counts['adjacent']} adjacent, "
        f"{evidence_counts['transfer_only']} transfer-only excluded",
    )
    summary = _source_summary(all_papers)
    if summary:
        yield st("classify", f"Source mix: {summary[:240]}")

    # ── Step 4: Synthesis ───────────────────────────────────────────────────
    minimum_direct_sources = 5 if params.depth >= 15 else 3
    low_direct_warning = len(direct_sources) < minimum_direct_sources
    synth_prompt = f"""You are writing an academic literature review on:
"{params.topic}"

Evidence-governed source set (use ONLY these; do not invent citations):
{json.dumps(synthesis_sources, indent=2)}

Excluded transfer-only sources (do NOT cite these in main findings):
{json.dumps(transfer_sources[:20], indent=2)}

Scopus/OpenAlex/Semantic Scholar/Crossref/official-document queries used:
{json.dumps(query_plan, indent=2)}

Evidence governance:
- Every source has source_type, evidence_tier, relevance_bucket, and citation_role.
- Direct evidence studies the topic itself or its applied implementation.
- Adjacent evidence may support background, methods, or gaps only.
- Transfer-only evidence must not be used as proof that an approach works for the target topic.
- Tier 1 = peer-reviewed journal/systematic review/major conference proceeding.
- Tier 2 = government scientific report, regulator guidance, federal/state technical report, or official utility evaluation.
- Tier 3 = university/professional-society/consultant technical report.
- Tier 4 = trustworthy context only; do not use for technical effectiveness claims.
- Direct source count: {len(direct_sources)}. Minimum direct sources for a full evidence synthesis: {minimum_direct_sources}.
- If direct evidence is below the minimum, explicitly state that direct evidence is limited and keep the review honest instead of padding with transferable domains.
- Official reports and utility documents without DOIs may be cited by title/organization/year when their url/source is supplied.

Write a complete literature review with these sections:
1. Executive Summary (1-2 paragraphs)
2. Background & Scope (topic definition, papers reviewed, sources and queries used)
3. Evidence Base & Governance (direct/adjacent/transfer-only counts; source tier interpretation)
4. Thematic Sections (3-6 themes, narrative prose — NOT a bullet list of papers)
5. Key Sources Table (columns: Title | First Author/Organization | Year | DOI/URL | Source Type | Evidence Tier | Relevance | One-sentence contribution)
6. Research Gaps & Open Questions
7. Excluded Transfer-Only Sources (brief table with reason excluded; omit if none)
8. [REFERENCES PLACEHOLDER]

Citation rules:
- AGU inline format: (Author et al., Year) for 3+ authors; (Author & Author, Year) for 2; (Author, Year) for 1
- Only cite sources from the evidence-governed source set above
- Cite direct evidence for findings about the target topic
- Label adjacent evidence as background or methodological context
- Do not cite transfer-only sources except in the excluded table

After the review text, on its own line, write:
CITED_DOIS: ["doi1", "doi2", ...]

Write the complete review now:"""

    yield st("synthesize", f"{llm_label} running — synthesizing {len(synthesis_sources)} governed sources...")
    _stask = asyncio.ensure_future(asyncio.to_thread(_run_llm_result_sync, synth_prompt, params.llm_backend, 360, 12000))
    _sbeats = 0
    while not _stask.done():
        done_set, _ = await asyncio.wait({_stask}, timeout=5.0)
        if not done_set:
            _sbeats += 1
            yield hb("synthesize",
                     f"{llm_label} active — writing review ({_sbeats * 5}s / ~1-3 min)")

    try:
        synth_result = _stask.result()
        raw_synth = synth_result.text
    except Exception as exc:
        print(f"[workflow] synthesis error: {repr(exc)}", flush=True)
        yield {"type": "error", "message": f"Synthesis failed: {exc}"}
        return

    metadata_llm_label = llm_label
    if params.llm_backend == "openrouter_free":
        assigned_model = synth_result.assigned_model or "not reported by OpenRouter"
        metadata_llm_label = f"{llm_label} (selected: openrouter/free; assigned: {assigned_model})"
        yield st("synthesize", f"OpenRouter Free Router assigned synthesis to: {assigned_model}")

    draft, cited_dois = _extract_cited_dois(raw_synth)

    yield st("synthesize",
             f"Done — draft complete, {len(cited_dois)} inline citations identified")

    # ── Step 5a: Critic — DOI / official URL existence (Pass 1) ────────────
    yield st("verify", f"Critic Pass 1 — checking {len(cited_dois)} cited DOIs in Scopus/Crossref…")
    verified_dois: list[str] = []
    failed_dois:   list[str] = []

    papers_by_doi = {p["doi"].lower(): p for p in all_papers if p.get("doi")}

    for doi in cited_dois:
        doi = normalize_doi(doi)
        yield st("verify", f"  verify_doi → {doi}")
        try:
            exists = await asyncio.to_thread(_verify_doi, doi, scopus_key)
            if exists:
                verified_dois.append(doi)
                yield st("verify", f"    ✓ exists in Scopus")
            else:
                crossref_exists = await asyncio.to_thread(verify_crossref_doi, doi)
                if crossref_exists:
                    verified_dois.append(doi)
                    yield st("verify", f"    ✓ exists in Crossref (not indexed by Scopus)")
                else:
                    failed_dois.append(doi)
                    yield st("verify", f"    ✗ DOI not found in Scopus or Crossref — flagged FAILED_EXISTENCE")
        except Exception as exc:
            try:
                crossref_exists = await asyncio.to_thread(verify_crossref_doi, doi)
            except Exception:
                crossref_exists = False
            if crossref_exists:
                verified_dois.append(doi)
                yield st("verify", f"    ✓ Scopus error, but Crossref verifies DOI")
            else:
                failed_dois.append(doi)
                yield st("verify", f"    ✗ verify error: {exc}")

    verified_url_sources = [
        p for p in synthesis_sources
        if not p.get("doi") and trusted_url_is_verifiable(p)
    ]
    if verified_url_sources:
        yield st("verify", f"  Trusted official URLs accepted for {len(verified_url_sources)} no-DOI sources")

    yield st("verify",
             f"Pass 1 complete — {len(verified_dois)} DOIs verified, "
             f"{len(verified_url_sources)} official no-DOI sources accepted, {len(failed_dois)} not found")

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
    # Include replacement papers and verified official no-DOI sources in the save list.
    replacement_papers = list(replacements.values())
    existing_urls = {p.get("url", "").lower() for p in existing_papers if p.get("url")}
    all_verified_papers = [
        papers_by_doi[doi.lower()]
        for doi in verified_dois
        if doi.lower() in papers_by_doi and doi.lower() not in existing_dois
    ] + [p for p in replacement_papers if p.get("doi", "").lower() not in existing_dois]
    all_verified_papers.extend(
        p for p in verified_url_sources
        if p.get("url", "").lower() not in existing_urls
    )

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
    n_papers_total  = len(synthesis_sources)
    n_verified_dois = len(verified_dois)
    n_replaced      = len(replacements)
    n_unsupported   = len([d for d in failed_dois if d not in replacements])
    final_markdown = _assemble(
        draft,
        bibliography,
        topic=params.topic,
        today=today,
        n_papers=n_papers_total,
        n_verified=n_verified_dois,
        n_replaced=n_replaced,
        n_unsupported=n_unsupported,
        n_direct=evidence_counts["direct"],
        n_adjacent=evidence_counts["adjacent"],
        n_transfer=evidence_counts["transfer_only"],
        n_url_verified=len(verified_url_sources),
        zotero_name=collection_name,
        collection_key=collection_key,
        llm_backend_label=metadata_llm_label,
    )

    filename_topic = _collection_topic_for_filename(collection_name, params.topic)
    slug = _filename_slug(filename_topic)
    backend_code = _llm_backend_filename_code(params.llm_backend)
    filename = f"{slug}_{today}_{backend_code}"
    out_path = OUTPUTS_DIR / f"{filename}.md"
    out_path.write_text(final_markdown, encoding="utf-8")

    yield st("saving",
             f"✓ Saved → outputs/{filename}.md  "
             f"({n_verified_dois} verified citations, {n_unsupported} flagged)")
    yield {"type": "result", "markdown": final_markdown, "filename": filename}
