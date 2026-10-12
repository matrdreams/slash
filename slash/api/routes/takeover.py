"""Takeover release, recording download, and forward_auth verify."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from slash.api.deps import require_bearer
from slash.core.errors import TokenError

auth_router = APIRouter(prefix="/takeover", dependencies=[Depends(require_bearer)])
public_router = APIRouter(prefix="/takeover")


@auth_router.post("/{takeover_id}:release")
async def release(takeover_id: str, request: Request):
    row = await request.app.state.ctx.takeover.release(takeover_id)
    return {"id": row.id, "released_at": row.released_at, "recording_ref": row.recording_ref}


@auth_router.post("/{takeover_id}/release")
async def release_slash(takeover_id: str, request: Request):
    return await release(takeover_id, request)


@auth_router.get("/{takeover_id}/recording")
async def recording(takeover_id: str, request: Request):
    state = request.app.state.ctx
    row = state.takeover.require(takeover_id)
    if not row.recording_ref:
        raise HTTPException(status_code=404, detail="no recording")
    return Response(content=state.blobs.get(row.recording_ref), media_type="video/mp4")


@public_router.get("/verify")
async def verify(request: Request):
    """Caddy forward_auth. The signed URL is one-time; a cookie keeps the session."""
    state = request.app.state.ctx
    cookie = request.cookies.get("slash_takeover")
    if cookie:
        try:
            state.takeover.verify_cookie(cookie)
        except TokenError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return Response(status_code=200)
    uri = request.headers.get("x-forwarded-uri") or request.url.path
    token = _token_from_uri(uri)
    if not token:
        raise HTTPException(status_code=401, detail="missing takeover token")
    try:
        row = state.takeover.verify(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    response = Response(status_code=200)
    response.set_cookie(
        "slash_takeover",
        state.takeover.cookie_for(row),
        max_age=state.config.takeover.ttl_s,
        httponly=True,
        samesite="strict",
    )
    return response


def _token_from_uri(uri: str) -> str:
    marker = "/takeover/"
    if marker not in uri:
        return ""
    rest = uri.split(marker, 1)[1]
    token = rest.split("/", 1)[0]
    if token in {"verify", ""}:
        return ""
    return token
