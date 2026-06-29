"""Multi-source retrieval and evidence governance helpers.

The workflow deliberately keeps this layer lightweight and cheap:
- scholarly APIs use public endpoints where possible
- SerpAPI is optional and constrained to trusted domains
- every candidate is normalized with source_type, evidence_tier, and
  relevance_bucket before the synthesis prompt sees it
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests

PROJECT_ROOT = Path(__file__).parent.parent
KEYS_FILE = PROJECT_ROOT / "secrets" / "keys.txt"

DIRECT_LSL_TERMS = (
    "lead service line",
    "lead service lines",
    "lead water line",
    "lead water lines",
    "lead pipe",
    "lead pipes",
    "lsl",
    "service line inventory",
    "service line inventories",
)

DIRECT_ACTION_TERMS = (
    "machine learning",
    "predictive",
    "prediction",
    "model",
    "inventory",
    "identification",
    "classification",
    "prioritization",
    "prioritize",
    "replacement",
    "excavation",
    "verification",
)

ADJACENT_TERMS = (
    "drinking water",
    "lead exposure",
    "water contamination",
    "corrosion",
    "water quality",
    "environmental justice",
    "geospatial",
    "infrastructure",
    "positive unlabeled",
    "spatial cross validation",
)

TRUSTED_WEB_DOMAINS = (
    "epa.gov",
    "usgs.gov",
    "cdc.gov",
    "nih.gov",
    "data.gov",
    "govinfo.gov",
    "federalregister.gov",
    "nj.gov",
    "michigan.gov",
    "pa.gov",
    "colorado.gov",
    "pgh2o.com",
    "denverwater.org",
    "awwa.org",
    "awwa-water.org",
)


def load_keys(keys_path: Path = KEYS_FILE) -> dict[str, str]:
    keys: dict[str, str] = {}
    if not keys_path.exists():
        return keys
    for line in keys_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        keys[name.strip()] = value.strip()
    return keys


def optional_key(*names: str) -> str:
    keys = load_keys()
    for name in names:
        value = keys.get(name, "")
        if value:
            return value
    return ""


def normalize_doi(doi: str | None) -> str:
    if not doi:
        return ""
    doi = doi.strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.rstrip(".,; ").lower()


def normalize_title(title: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _safe_get_json(url: str, *, params: dict, headers: dict | None = None, timeout: int = 30) -> dict:
    response = requests.get(url, params=params, headers=headers or {}, timeout=timeout)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    return response.json()


def _first_author_from_openalex(authorships: list[dict]) -> str:
    if not authorships:
        return ""
    name = authorships[0].get("author", {}).get("display_name", "")
    if not name:
        return ""
    parts = name.split()
    return f"{parts[-1]}, {' '.join(parts[:-1])}".strip(", ")


def search_openalex(query: str, limit: int) -> list[dict]:
    params = {
        "search": query,
        "per-page": max(1, min(limit, 50)),
        "select": "id,doi,title,display_name,publication_year,abstract_inverted_index,authorships,primary_location,type,cited_by_count,referenced_works",
    }
    email = optional_key("OPENALEX_EMAIL")
    if email:
        params["mailto"] = email
    payload = _safe_get_json("https://api.openalex.org/works", params=params)
    records = []
    for item in payload.get("results", []):
        doi = normalize_doi(item.get("doi"))
        title = item.get("title") or item.get("display_name") or ""
        abstract = _abstract_from_inverted_index(item.get("abstract_inverted_index"))
        records.append(
            {
                "title": title,
                "first_author": _first_author_from_openalex(item.get("authorships") or []),
                "doi": doi,
                "year": str(item.get("publication_year") or ""),
                "abstract_snippet": abstract[:900],
                "abstract": abstract,
                "url": item.get("id", ""),
                "source": "OpenAlex",
                "source_type": _source_type_from_openalex(item),
                "evidence_tier": "Tier 1",
                "retrieval_query": query,
                "citation_count": item.get("cited_by_count", 0),
            }
        )
    return records


def _abstract_from_inverted_index(index: dict | None) -> str:
    if not index:
        return ""
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        for position in positions:
            words.append((int(position), word))
    return " ".join(word for _, word in sorted(words))


def _source_type_from_openalex(item: dict) -> str:
    work_type = str(item.get("type") or "").lower()
    source = (
        (item.get("primary_location") or {})
        .get("source", {})
        .get("type", "")
    )
    if "proceed" in work_type or "conference" in str(source).lower():
        return "conference proceeding"
    if "book" in work_type:
        return "book chapter"
    return "peer-reviewed article"


def search_semantic_scholar(query: str, limit: int) -> list[dict]:
    params = {
        "query": query,
        "limit": max(1, min(limit, 20)),
        "fields": "title,abstract,year,authors,externalIds,url,venue,publicationTypes,citationCount",
    }
    headers = {}
    api_key = optional_key("SEMANTIC_SCHOLAR_S2_API_KEY", "SEMANTIC_SCHOLAR_API_KEY", "S2_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    payload = _safe_get_json(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params=params,
        headers=headers,
    )
    records = []
    for item in payload.get("data", []):
        authors = item.get("authors") or []
        first_author = ""
        if authors:
            name = authors[0].get("name", "")
            parts = name.split()
            first_author = f"{parts[-1]}, {' '.join(parts[:-1])}".strip(", ")
        doi = normalize_doi((item.get("externalIds") or {}).get("DOI"))
        records.append(
            {
                "title": item.get("title", ""),
                "first_author": first_author,
                "doi": doi,
                "year": str(item.get("year") or ""),
                "abstract_snippet": (item.get("abstract") or "")[:900],
                "abstract": item.get("abstract") or "",
                "url": item.get("url", ""),
                "source": "Semantic Scholar",
                "source_type": _source_type_from_semantic(item),
                "evidence_tier": "Tier 1",
                "retrieval_query": query,
                "citation_count": item.get("citationCount", 0),
            }
        )
    return records


def _source_type_from_semantic(item: dict) -> str:
    pub_types = " ".join(item.get("publicationTypes") or []).lower()
    venue = str(item.get("venue") or "").lower()
    if "conference" in pub_types or "conference" in venue or "proceedings" in venue:
        return "conference proceeding"
    return "peer-reviewed article"


def search_crossref(query: str, limit: int) -> list[dict]:
    params = {"query.bibliographic": query, "rows": max(1, min(limit, 20))}
    payload = _safe_get_json("https://api.crossref.org/works", params=params)
    records = []
    for item in payload.get("message", {}).get("items", []):
        title = (item.get("title") or [""])[0]
        year_parts = item.get("published-print") or item.get("published-online") or item.get("issued") or {}
        year = ""
        if year_parts.get("date-parts"):
            year = str(year_parts["date-parts"][0][0])
        authors = item.get("author") or []
        first_author = ""
        if authors:
            first = authors[0]
            family = first.get("family", "")
            given = first.get("given", "")
            first_author = f"{family}, {given}".strip(", ")
        records.append(
            {
                "title": title,
                "first_author": first_author,
                "doi": normalize_doi(item.get("DOI")),
                "year": year,
                "abstract_snippet": _strip_tags(item.get("abstract", ""))[:900],
                "abstract": _strip_tags(item.get("abstract", "")),
                "url": item.get("URL", ""),
                "source": "Crossref",
                "source_type": _source_type_from_crossref(item.get("type", "")),
                "evidence_tier": "Tier 1",
                "retrieval_query": query,
            }
        )
    return records


def verify_crossref_doi(doi: str) -> bool:
    doi = normalize_doi(doi)
    if not doi:
        return False
    response = requests.get(f"https://api.crossref.org/works/{doi}", timeout=30)
    return response.status_code == 200


def _source_type_from_crossref(work_type: str) -> str:
    text = work_type.lower()
    if "proceed" in text:
        return "conference proceeding"
    if "report" in text:
        return "technical report"
    if "book" in text:
        return "book chapter"
    return "peer-reviewed article"


def search_serpapi_trusted(query: str, limit: int) -> list[dict]:
    api_key = optional_key("SERPAPI_API_KEY", "SERP_API_KEY")
    if not api_key:
        return []
    trusted_filter = " OR ".join(f"site:{domain}" for domain in TRUSTED_WEB_DOMAINS)
    params = {
        "engine": "google",
        "api_key": api_key,
        "q": f"({trusted_filter}) {query}",
        "num": max(1, min(limit, 10)),
    }
    payload = _safe_get_json("https://serpapi.com/search.json", params=params, timeout=45)
    records = []
    for item in payload.get("organic_results", []):
        url = item.get("link", "")
        if not _is_trusted_url(url):
            continue
        records.append(
            {
                "title": item.get("title", ""),
                "first_author": _domain_label(url),
                "doi": "",
                "year": "",
                "abstract_snippet": item.get("snippet", ""),
                "abstract": item.get("snippet", ""),
                "url": url,
                "source": "SerpAPI trusted web",
                "source_type": _source_type_from_url(url),
                "evidence_tier": _tier_from_url(url),
                "retrieval_query": query,
            }
        )
    return records


def search_data_gov(query: str, limit: int) -> list[dict]:
    payload = _safe_get_json(
        "https://catalog.data.gov/api/3/action/package_search",
        params={"q": query, "rows": max(1, min(limit, 20))},
    )
    records = []
    for item in payload.get("result", {}).get("results", []):
        records.append(
            {
                "title": item.get("title", ""),
                "first_author": item.get("organization", {}).get("title", "Data.gov"),
                "doi": "",
                "year": "",
                "abstract_snippet": _strip_tags(item.get("notes", ""))[:900],
                "abstract": _strip_tags(item.get("notes", "")),
                "url": item.get("url") or f"https://catalog.data.gov/dataset/{item.get('name', '')}",
                "source": "Data.gov",
                "source_type": "government dataset/catalog record",
                "evidence_tier": "Tier 2",
                "retrieval_query": query,
            }
        )
    return records


def search_osti(query: str, limit: int) -> list[dict]:
    payload = _safe_get_json(
        "https://www.osti.gov/api/v1/records",
        params={"q": query, "rows": max(1, min(limit, 20)), "format": "json"},
    )
    items = payload if isinstance(payload, list) else payload.get("records", [])
    records = []
    for item in items:
        doi = normalize_doi(item.get("doi"))
        records.append(
            {
                "title": item.get("title", ""),
                "first_author": _first_author_from_osti(item),
                "doi": doi,
                "year": str(item.get("publication_date", "")[:4]),
                "abstract_snippet": _strip_tags(item.get("description", ""))[:900],
                "abstract": _strip_tags(item.get("description", "")),
                "url": item.get("osti_id") and f"https://www.osti.gov/biblio/{item.get('osti_id')}" or "",
                "source": "OSTI",
                "source_type": _source_type_from_osti(item),
                "evidence_tier": "Tier 2" if not doi else "Tier 1",
                "retrieval_query": query,
            }
        )
    return records


def _first_author_from_osti(item: dict) -> str:
    authors = item.get("authors") or []
    if isinstance(authors, list) and authors:
        if isinstance(authors[0], dict):
            return authors[0].get("name", "")
        return str(authors[0])
    return ""


def _source_type_from_osti(item: dict) -> str:
    product_type = str(item.get("product_type") or item.get("resource_type") or "").lower()
    if "conference" in product_type:
        return "conference proceeding"
    if "report" in product_type:
        return "government technical report"
    return "government scientific record"


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _is_trusted_url(url: str) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    if host.endswith(".gov"):
        return True
    return any(host == domain or host.endswith(f".{domain}") for domain in TRUSTED_WEB_DOMAINS)


def _domain_label(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    return host or "Official source"


def _source_type_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.endswith(".gov") or ".gov" in host or "epa.gov" in host or "usgs.gov" in host:
        return "government technical report or guidance"
    if "awwa" in host:
        return "professional society report"
    if "water" in host or "pgh2o" in host:
        return "official utility document"
    return "trusted web document"


def _tier_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.endswith(".gov") or ".gov" in host or "epa.gov" in host or "usgs.gov" in host:
        return "Tier 2"
    if "awwa" in host or "water" in host or "pgh2o" in host:
        return "Tier 3"
    return "Tier 4"


def classify_record(record: dict, topic: str = "") -> dict:
    text = " ".join(
        str(record.get(key, ""))
        for key in ("title", "abstract_snippet", "abstract", "retrieval_query", "source_type")
    ).lower()

    direct_lsl = any(term in text for term in DIRECT_LSL_TERMS)
    direct_action = any(term in text for term in DIRECT_ACTION_TERMS)
    adjacent = any(term in text for term in ADJACENT_TERMS)

    if direct_lsl and direct_action:
        bucket = "direct"
    elif direct_lsl or adjacent:
        bucket = "adjacent"
    else:
        bucket = "transfer_only"

    source_type = record.get("source_type", "")
    tier = record.get("evidence_tier", "")
    if not tier:
        if source_type in {"peer-reviewed article", "conference proceeding"}:
            tier = "Tier 1"
        elif "government" in source_type or "utility" in source_type:
            tier = "Tier 2"
        elif "professional" in source_type or "technical report" in source_type:
            tier = "Tier 3"
        else:
            tier = "Tier 4"

    out = dict(record)
    out["doi"] = normalize_doi(out.get("doi"))
    out["relevance_bucket"] = bucket
    out["evidence_tier"] = tier
    out["citation_role"] = _citation_role(bucket, tier)
    return out


def _citation_role(bucket: str, tier: str) -> str:
    if bucket == "direct" and tier in {"Tier 1", "Tier 2", "Tier 3"}:
        return "core evidence"
    if bucket == "adjacent" and tier in {"Tier 1", "Tier 2", "Tier 3"}:
        return "background or methods only"
    if tier == "Tier 4":
        return "context only"
    return "exclude from synthesis"


def dedupe_records(records: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for record in records:
        doi = normalize_doi(record.get("doi"))
        title_key = normalize_title(record.get("title"))
        year = str(record.get("year") or "")
        key = f"doi:{doi}" if doi else f"title:{title_key}:{year}"
        if not title_key or key in seen:
            continue
        seen.add(key)
        clean = dict(record)
        clean["doi"] = doi
        deduped.append(clean)
    return deduped


def trusted_url_is_verifiable(record: dict) -> bool:
    url = record.get("url", "")
    return bool(url and _is_trusted_url(url) and record.get("evidence_tier") in {"Tier 2", "Tier 3", "Tier 4"})


def run_source_safely(
    source_name: str,
    search_fn: Callable[[str, int], list[dict]],
    query: str,
    limit: int,
) -> tuple[list[dict], str | None]:
    try:
        return search_fn(query, limit), None
    except Exception as exc:
        return [], f"{source_name} failed for '{query[:80]}': {exc}"
