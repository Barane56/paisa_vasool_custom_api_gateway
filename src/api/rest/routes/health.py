import logging

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

@router.get("/health")
@router.head("/health")
async def health_check(request: Request) -> Response:
    service_status: dict[str, str] = {}
    for name, url in settings.services.items():
        try:
            async with httpx.AsyncClient(timeout=2.0) as health_client:
                resp = await health_client.get(f"{url}/health")
                service_status[name] = (
                    "healthy" if resp.status_code < 500 else "unhealthy"
                )
        except Exception as e:
            logger.warning("Health check failed for %s: %s", name, str(e))
            service_status[name] = "unhealthy"

    overall_status = "healthy"
    if any(status == "unhealthy" for status in service_status.values()):
        overall_status = "degraded"

    if request.method == "HEAD":
        return Response(status_code=200 if overall_status == "healthy" else 503)

    return JSONResponse(content={
        "status": overall_status,
        "services": service_status,
        "cors_origins": settings.all_allowed_origins,
    })
