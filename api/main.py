"""FastAPI entry point for the Auto Literature Review app."""
import json
import re
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from api.workflow import LLM_BACKENDS, ReviewParams, run_review_workflow

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"

app = FastAPI(title="Auto Literature Review API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReviewRequest(BaseModel):
    topic: str = Field(..., min_length=5)
    depth: int = Field(20, ge=5, le=100)
    format: str = Field("md", pattern="^(md|docx|pdf)$")
    zotero_collection: str = Field("")
    llm_backend: str = Field("claude", pattern=f"^({'|'.join(LLM_BACKENDS.keys())})$")
    source_categories: list[str] = Field(default_factory=lambda: ["scholarly", "official"])


@app.post("/api/review")
async def review(req: ReviewRequest) -> StreamingResponse:
    print(
        f"[api] /api/review topic_len={len(req.topic)} depth={req.depth} "
        f"format={req.format} llm_backend={req.llm_backend}",
        flush=True,
    )
    params = ReviewParams(
        topic=req.topic,
        depth=req.depth,
        format=req.format,
        zotero_collection=req.zotero_collection.strip() or None,
        llm_backend=req.llm_backend,
        source_categories=req.source_categories,
    )

    async def stream() -> AsyncIterator[str]:
        try:
            async for event in run_review_workflow(params):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/download/{filename}")
async def download(filename: str, format: str = "md") -> Response:
    # Reject any filename that isn't a plain slug (letters, digits, hyphens, underscores).
    # This blocks path separators, dots, and null bytes before any filesystem access.
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Resolve the full path and confirm it stays inside OUTPUTS_DIR, defending
    # against any symlink-based traversal that slips past the regex.
    candidate = (OUTPUTS_DIR / f"{filename}.md").resolve()
    if not candidate.is_relative_to(OUTPUTS_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")

    md_path = candidate
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Review file not found")

    markdown = md_path.read_text(encoding="utf-8")

    if format == "md":
        return Response(
            content=markdown.encode("utf-8"),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}.md"'},
        )

    if format == "docx":
        try:
            from api.convert import to_docx
            data = to_docx(markdown)
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="python-docx not installed. Run: pip install python-docx",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"DOCX export failed: {exc}",
            ) from exc
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}.docx"'},
        )

    if format == "pdf":
        try:
            from api.convert import to_pdf
            data = to_pdf(markdown)
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"PDF dependencies missing ({exc}). Run: pip install reportlab",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"PDF export failed: {exc}",
            ) from exc
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
        )

    raise HTTPException(status_code=400, detail=f"Unknown format: {format}")
