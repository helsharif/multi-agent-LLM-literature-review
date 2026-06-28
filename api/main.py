"""FastAPI entry point for the Auto Literature Review app."""
import json
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from api.workflow import ReviewParams, run_review_workflow

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"

app = FastAPI(title="Auto Literature Review API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReviewRequest(BaseModel):
    topic: str = Field(..., min_length=5)
    depth: int = Field(20, ge=5, le=100)
    format: str = Field("md", pattern="^(md|docx|pdf)$")
    zotero_collection: str = Field("")


@app.post("/api/review")
async def review(req: ReviewRequest) -> StreamingResponse:
    params = ReviewParams(
        topic=req.topic,
        depth=req.depth,
        format=req.format,
        zotero_collection=req.zotero_collection.strip() or None,
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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/download/{filename}")
async def download(filename: str, format: str = "md") -> Response:
    md_path = OUTPUTS_DIR / f"{filename}.md"
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
                detail=f"PDF dependencies missing ({exc}). Run: pip install weasyprint markdown",
            )
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
        )

    raise HTTPException(status_code=400, detail=f"Unknown format: {format}")
