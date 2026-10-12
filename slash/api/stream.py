"""Proxy /takeover/<token>/ to ws-scrcpy after the signed link is consumed.

Caddy does the same job in production: forward_auth, then strip the token
prefix. This route lets `slash serve` embed the stream without Caddy.
"""

from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import RedirectResponse, Response

from slash.core.errors import TokenError
from slash.takeover.tokens import hash_token

HOP = {"host", "content-length", "connection", "authorization", "cookie", "transfer-encoding"}


def install_stream(app: FastAPI) -> None:
    @app.get("/takeover/{token}")
    async def slash_redirect(token: str):
        return RedirectResponse(url=f"/takeover/{token}/", status_code=307)

    async def proxy_http(token: str, path: str, request: Request):
        state = request.app.state.ctx
        try:
            _row, fresh = _authorize(state, token, request.cookies.get("slash_takeover"))
        except TokenError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        upstream = _upstream_http(state.config.takeover.ws_scrcpy_upstream, path, request.url.query)
        headers = {key: value for key, value in request.headers.items() if key.lower() not in HOP}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=2.0), follow_redirects=False) as client:
                upstream_response = await client.request(
                    request.method,
                    upstream,
                    content=await request.body(),
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            response = Response(status_code=502, content=f"ws-scrcpy upstream unavailable: {exc}".encode())
        else:
            passthrough = {
                key: value
                for key, value in upstream_response.headers.items()
                if key.lower() not in HOP | {"content-encoding"}
            }
            response = Response(
                content=upstream_response.content,
                status_code=upstream_response.status_code,
                headers=passthrough,
            )
        if fresh:
            _set_cookie(response, state, _row)
        return response

    for method in ("GET", "HEAD", "POST", "PUT", "DELETE"):
        app.add_api_route(
            "/takeover/{token}/{path:path}",
            proxy_http,
            methods=[method],
            operation_id=f"proxy_takeover_{method.lower()}",
        )

    @app.websocket("/takeover/{token}/{path:path}")
    async def proxy_ws(websocket: WebSocket, token: str, path: str = ""):
        state = websocket.app.state.ctx
        try:
            _authorize(state, token, websocket.cookies.get("slash_takeover"))
        except TokenError:
            await websocket.accept()
            await websocket.close(code=1008)
            return
        await websocket.accept()
        upstream = _upstream_ws(state.config.takeover.ws_scrcpy_upstream, path, websocket.url.query)
        try:
            from websockets.asyncio.client import connect
        except ImportError:
            await websocket.close(code=1011)
            return
        try:
            async with connect(upstream, max_size=None, open_timeout=5) as remote:
                await _bridge(websocket, remote)
        except Exception:
            await websocket.close(code=1011)


def _authorize(state, token: str, cookie: str | None):
    if cookie:
        row = state.takeover.verify_cookie(cookie)
        linked = state.store.get_takeover_by_hash(hash_token(token))
        if linked is None or linked.id != row.id:
            raise TokenError("takeover cookie does not match this link")
        return row, False
    row = state.takeover.verify(token)
    return row, True


def _set_cookie(response: Response, state, row) -> None:
    response.set_cookie(
        "slash_takeover",
        state.takeover.cookie_for(row),
        max_age=state.config.takeover.ttl_s,
        httponly=True,
        samesite="strict",
        path="/",
    )


def _upstream_http(base: str, path: str, query: str) -> str:
    suffix = path.lstrip("/")
    root = base.rstrip("/")
    url = f"{root}/{suffix}" if suffix else f"{root}/"
    if query:
        url = f"{url}?{query}"
    return url


def _upstream_ws(base: str, path: str, query: str) -> str:
    parts = urlsplit(base)
    scheme = "wss" if parts.scheme == "https" else "ws"
    suffix = path.lstrip("/")
    ws_path = f"/{suffix}" if suffix else "/"
    return urlunsplit((scheme, parts.netloc, ws_path, query, ""))


async def _bridge(websocket: WebSocket, remote) -> None:
    import asyncio

    async def client_to_upstream() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("text") is not None:
                await remote.send(message["text"])
            elif message.get("bytes") is not None:
                await remote.send(message["bytes"])

    async def upstream_to_client() -> None:
        async for message in remote:
            if isinstance(message, bytes):
                await websocket.send_bytes(message)
            else:
                await websocket.send_text(message)

    _done, pending = await asyncio.wait(
        {
            asyncio.create_task(client_to_upstream()),
            asyncio.create_task(upstream_to_client()),
        },
        return_when=asyncio.FIRST_COMPLETED,
    )
    for item in pending:
        item.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
