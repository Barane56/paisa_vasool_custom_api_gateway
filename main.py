from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging
from typing import Dict, List
import uvicorn
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="API Gateway", version="1.0.0")

# ============================================================================
# CORS Configuration
# ============================================================================

ALLOWED_ORIGINS = [
    "http://localhost",
    "http://localhost:80",
    "http://localhost:3000",
    "http://127.0.0.1",
    "http://127.0.0.1:80",
    "http://127.0.0.1:3000",
]



app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ============================================================================
# Service Configuration
# ============================================================================

from dotenv import load_dotenv

load_dotenv()

if os.getenv("ENVIRONMENT") == "production":
    SERVICES = {
                    
        "auth": os.getenv("auth_service_url"),
        "dispute": os.getenv("dispute_service_url"),
    }
    ALLOWED_ORIGINS.append(os.getenv("frontend_url"))
else:
    SERVICES = {
        "auth":    "http://auth:8001",
        "dispute": "http://dispute:8002",
    }

# Shared HTTP client with connection pooling
client = httpx.AsyncClient(
    timeout=60.0,
    follow_redirects=True,
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=100)
)

# Headers to exclude when forwarding (hop-by-hop headers)
EXCLUDED_HEADERS = {
    "host",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


# ============================================================================
# Startup/Shutdown Events
# ============================================================================

@app.on_event("startup")
async def startup():
    logger.info("=" * 50)
    logger.info("API Gateway Starting Up")
    logger.info(f"CORS Allowed Origins: {ALLOWED_ORIGINS}")
    logger.info(f"Services: {SERVICES}")
    logger.info("=" * 50)


@app.on_event("shutdown")
async def shutdown():
    await client.aclose()
    logger.info("API Gateway Shut Down")


# ============================================================================
# Route Handlers
# ============================================================================

@app.api_route("/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_auth(request: Request, path: str):
    """Proxy requests to auth service"""
    logger.info(f"Auth route called with path: {path}")
    return await proxy_request(request, "auth", path)


@app.api_route("/dispute/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_dispute(request: Request, path: str):
    """Proxy requests to dispute service"""
    logger.info(f"Dispute route called with path: {path}")
    return await proxy_request(request, "dispute", path)


# ============================================================================
# Health Check
# ============================================================================

@app.get("/health")
@app.head("/health")
async def health_check(request: Request):
    service_status = {}
    for name, url in SERVICES.items():
        try:
            async with httpx.AsyncClient(timeout=2.0) as health_client:
                resp = await health_client.get(f"{url}/health")
                service_status[name] = "healthy" if resp.status_code < 500 else "unhealthy"
        except Exception as e:
            logger.warning(f"Health check failed for {name}: {str(e)}")
            service_status[name] = "unhealthy"

    overall_status = "healthy"
    if any(status == "unhealthy" for status in service_status.values()):
        overall_status = "degraded"

    if request.method == "HEAD":
        return Response(status_code=200 if overall_status == "healthy" else 503)

    return JSONResponse(content={
        "status": overall_status,
        "services": service_status,
        "cors_origins": ALLOWED_ORIGINS,
    })


# ============================================================================
# Main Proxy Function
# ============================================================================

async def proxy_request(request: Request, service_name: str, path: str):
    service_url = SERVICES.get(service_name)
    if not service_url:
        return JSONResponse(status_code=404, content={"detail": f"Service {service_name} not found"})

    path = path.strip("/")
    target_url = f"{service_url}/{path}" if path else service_url

    if request.query_params:
        query_string = "&".join([f"{k}={v}" for k, v in request.query_params.items()])
        target_url = f"{target_url}?{query_string}"

    headers = dict(request.headers)
    for header in EXCLUDED_HEADERS:
        headers.pop(header, None)

    print("Request Headers :", headers)

    logger.info("=" * 50)
    logger.info(f"Request: {request.method} {request.url.path}")
    logger.info(f"Target URL: {target_url}")
    logger.info(f"Origin: {request.headers.get('origin', 'None')}")
    logger.info(f"Auth header: {headers.get('authorization', 'None')}")

    body = await request.body()

    try:
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body if body else None,
            cookies=request.cookies,
        )

        logger.info(f"Response from {service_name}: Status {resp.status_code}")

        set_cookie_headers = []
        if hasattr(resp.headers, 'get_list'):
            set_cookie_headers = resp.headers.get_list('set-cookie')
        else:
            for key, value in resp.headers.items():
                if key.lower() == 'set-cookie':
                    set_cookie_headers.extend(value if isinstance(value, list) else [value])

        response = Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
        )

        origin = request.headers.get("origin")
        if origin and origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"

        if set_cookie_headers:
            for k in [k for k in response.headers.keys() if k.lower() == 'set-cookie']:
                del response.headers[k]
            for cookie_header in set_cookie_headers:
                if cookie_header:
                    response.headers.append("set-cookie", cookie_header)

        logger.info("=" * 50)

        print(response.__dict__)
        return response

    except httpx.RequestError as e:
        logger.error(f"Error proxying to {service_name}: {str(e)}")
        return JSONResponse(status_code=502, content={"detail": f"Bad gateway: {str(e)}"})
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return JSONResponse(status_code=500, content={"detail": f"Internal server error: {str(e)}"})


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True, log_level="info")