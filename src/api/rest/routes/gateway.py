import logging

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from src.config import get_settings
from src.core.clients import client

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

async def proxy_request(request: Request, service_name: str, path: str) -> Response:
    service_url = settings.services.get(service_name)
    if not service_url:
        return JSONResponse(status_code=404, content={"detail":
        f"Service {service_name} not found"})

    path = path.strip("/")
    target_url = f"{service_url}/{path}" if path else service_url

    if request.query_params:
        query_string = "&".join([f"{k}={v}" for k, v in request.query_params.items()])
        target_url = f"{target_url}?{query_string}"

    headers = dict(request.headers)
    for header in settings.EXCLUDED_HEADERS:
        headers.pop(header, None)

    logger.debug("Request Headers: %s", headers)
    logger.info("Proxying %s %s -> %s", request.method, request.url.path, target_url)

    body = await request.body()

    try:
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body if body else None,
            cookies=request.cookies,
        )

        logger.info("Response from %s: Status %s", service_name, resp.status_code)

        set_cookie_headers = []
        if hasattr(resp.headers, 'get_list'):
            set_cookie_headers = resp.headers.get_list('set-cookie')
        else:
            for key, value in resp.headers.items():
                if key.lower() == 'set-cookie':
                    set_cookie_headers.extend(value if isinstance(value, list)
                     else [value])

        response = Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
        )

        origin = request.headers.get("origin")
        if origin and origin in settings.all_allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"

        if set_cookie_headers:
            for k in [k for k in response.headers if k.lower() == 'set-cookie']:
                del response.headers[k]
            for cookie_header in set_cookie_headers:
                if cookie_header:
                    response.headers.append("set-cookie", cookie_header)

        return response

    except httpx.RequestError as e:
        logger.error("Error proxying to %s: %s", service_name, str(e))
        return JSONResponse(status_code=502,
        content={"detail": f"Bad gateway: {str(e)}"})
    except Exception as e:
        logger.error("Unexpected error: %s", str(e))
        return JSONResponse(status_code=500,
        content={"detail": f"Internal server error: {str(e)}"})

@router.api_route("/auth/{path:path}",
                  methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_auth(request: Request, path: str) -> Response:
    return await proxy_request(request, "auth", path)

@router.api_route("/dispute/{path:path}",
                  methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_dispute(request: Request, path: str) -> Response:
    return await proxy_request(request, "dispute", path)
