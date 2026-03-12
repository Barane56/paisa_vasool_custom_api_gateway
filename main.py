from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging
from typing import Dict, List
import uvicorn

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="API Gateway", version="1.0.0")

# ============================================================================
# CORS Configuration
# ============================================================================

# Define allowed origins (frontend URLs)
ALLOWED_ORIGINS = [
    "http://localhost",
    "http://localhost:80",
    "http://localhost:3000",  # Common React dev port
    "http://127.0.0.1",
    "http://127.0.0.1:80",
    "http://127.0.0.1:3000",
]

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,  # ABSOLUTELY CRITICAL for cookies
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ============================================================================
# Service Configuration
# ============================================================================

# Service URLs (using Docker service names)

import os

SERVICES = None

if os.getenv("ENVIRONMENT") == "production":
    SERVICES = {
        "auth" : "http://auth:8001",
        "dispute" : "http://dispute:8002"
    }
else :
    SERVICES = {
    "auth": "http://localhost:8001",
    "dispute": "http://localhost:8002",
    }

# Create a shared HTTP client with connection pooling
client = httpx.AsyncClient(
    timeout=30.0,
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
    "content-length",  # Will be set automatically
}


# ============================================================================
# Startup/Shutdown Events
# ============================================================================

@app.on_event("startup")
async def startup():
    """Log CORS configuration on startup"""
    logger.info("=" * 50)
    logger.info("API Gateway Starting Up")
    logger.info(f"CORS Allowed Origins: {ALLOWED_ORIGINS}")
    logger.info(f"CORS Allow Credentials: True")
    logger.info(f"Services: {SERVICES}")
    logger.info("=" * 50)


@app.on_event("shutdown")
async def shutdown():
    """Clean up HTTP client on shutdown"""
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
    """Gateway health check"""
    # Check if services are reachable
    service_status = {}
    
    for name, url in SERVICES.items():
        try:
            # Use a short timeout for health checks
            async with httpx.AsyncClient(timeout=2.0) as health_client:
                resp = await health_client.get(f"{url}/health")
                service_status[name] = "healthy" if resp.status_code < 500 else "unhealthy"
        except Exception as e:
            logger.warning(f"Health check failed for {name}: {str(e)}")
            service_status[name] = "unhealthy"
    
    # Determine overall status
    overall_status = "healthy"
    if any(status == "unhealthy" for status in service_status.values()):
        overall_status = "degraded"
    
    response_data = {
        "status": overall_status,
        "services": service_status,
        "cors_origins": ALLOWED_ORIGINS
    }
    
    # For HEAD requests, return only headers
    if request.method == "HEAD":
        return Response(status_code=200 if overall_status == "healthy" else 503)
    
    return JSONResponse(content=response_data)


# ============================================================================
# Main Proxy Function (FIXED VERSION)
# ============================================================================

async def proxy_request(request: Request, service_name: str, path: str):
    """
    Proxy the incoming request to the target service with full CORS support
    """
    service_url = SERVICES.get(service_name)
    if not service_url:
        logger.error(f"Service {service_name} not found")
        return JSONResponse(
            status_code=404,
            content={"detail": f"Service {service_name} not found"}
        )
    
    # Build the target URL - handle empty path and trailing slashes properly
    if path:
        # Remove any leading/trailing slashes to avoid double slashes
        path = path.strip('/')
        target_url = f"{service_url}/{path}"
    else:
        target_url = service_url
    
    # Add query parameters if present
    if request.query_params:
        query_string = "&".join([f"{k}={v}" for k, v in request.query_params.items()])
        target_url = f"{target_url}?{query_string}"
    
    # Prepare headers (exclude hop-by-hop headers)
    headers = dict(request.headers)
    for header in EXCLUDED_HEADERS:
        headers.pop(header, None)
    
    # Log request details (useful for debugging)
    logger.info("=" * 50)
    logger.info(f"Request: {request.method} {request.url.path}")
    logger.info(f"Target URL: {target_url}")
    logger.info(f"Origin: {request.headers.get('origin', 'None')}")
    logger.info(f"Cookies received: {dict(request.cookies)}")
    logger.info(f"Cookie header: {headers.get('cookie', 'None')}")
    logger.info(f"Auth header: {headers.get('authorization', 'None')}")
    
    # Get request body
    body = await request.body()
    if body:
        logger.info(f"Request body size: {len(body)} bytes")
    
    try:
        # Forward the request to the target service
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body if body else None,
            cookies=request.cookies,  # Explicitly forward cookies
        )
        
        # Log response details
        logger.info(f"Response from {service_name}: Status {resp.status_code}")
        
        # FIXED: Handle Set-Cookie headers properly
        # In httpx, headers can be accessed as a dictionary or with .get_list()
        set_cookie_headers = []
        
        # Method 1: Try to get all Set-Cookie headers using get_list if available
        if hasattr(resp.headers, 'get_list'):
            set_cookie_headers = resp.headers.get_list('set-cookie')
        else:
            # Method 2: Manual extraction - httpx headers are case-insensitive
            set_cookie_headers = []
            for key, value in resp.headers.items():
                if key.lower() == 'set-cookie':
                    if isinstance(value, list):
                        set_cookie_headers.extend(value)
                    else:
                        set_cookie_headers.append(value)
        
        # Log cookies from response
        if set_cookie_headers:
            for cookie in set_cookie_headers:
                if cookie:
                    # Truncate for logging
                    cookie_preview = cookie[:100] + "..." if len(cookie) > 100 else cookie
                    logger.info(f"Set-Cookie from service: {cookie_preview}")
        
        # Create response with the same status code and content
        response = Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
        )
        
        # Add CORS headers explicitly (redundant but safe)
        origin = request.headers.get("origin")
        if origin and origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        
        # FIXED: Ensure cookies are properly forwarded
        # We need to make sure all Set-Cookie headers are preserved
        if set_cookie_headers:
            # Clear any existing Set-Cookie headers that might have been added
            # and add them back properly
            cookie_headers_to_remove = [k for k in response.headers.keys() if k.lower() == 'set-cookie']
            for key in cookie_headers_to_remove:
                del response.headers[key]
            
            # Add each Set-Cookie header individually
            for cookie_header in set_cookie_headers:
                if cookie_header:
                    response.headers.append("set-cookie", cookie_header)
        
        logger.info(f"Response headers: {dict(response.headers)}")
        logger.info("=" * 50)
        
        return response
        
    except httpx.RequestError as e:
        logger.error(f"Error proxying to {service_name}: {str(e)}")
        logger.error("=" * 50)
        return JSONResponse(
            status_code=502,
            content={"detail": f"Bad gateway: Cannot reach {service_name} service. Error: {str(e)}"}
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        logger.error("=" * 50)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error: {str(e)}"}
        )


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )