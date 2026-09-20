from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.services.observability import metrics_content_type, render_metrics

router = APIRouter(tags=["Metrics"])


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    return Response(
        content=render_metrics(),
        media_type=metrics_content_type(),
    )
