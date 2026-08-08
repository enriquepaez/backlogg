"""Metrics endpoint — Prometheus text exposition.

Thin router: it does no work of its own beyond asking the in-process registry
(``core/metrics``) to render the current samples and returning them with the
exact content type Prometheus scrapers expect. No DB, no SQLAlchemy — the
registry is a platform-layer singleton, not a domain repository.
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from backlogg.core.metrics import CONTENT_TYPE_LATEST, get_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    """Expose all registered metrics in Prometheus exposition format."""
    return PlainTextResponse(content=get_metrics().render(), media_type=CONTENT_TYPE_LATEST)
