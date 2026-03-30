import httpx

client = httpx.AsyncClient(
    timeout=60.0,
    follow_redirects=True,
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=100)
)
