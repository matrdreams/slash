"""Request dependencies."""

import hmac

from fastapi import HTTPException, Request


def ctx(request: Request):
    return request.app.state.ctx


def tokens_equal(left: str, right: str) -> bool:
    a = left.encode()
    b = right.encode()
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def require_bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = header.split(" ", 1)[1].strip()
    if not tokens_equal(token, request.app.state.ctx.token):
        raise HTTPException(status_code=401, detail="invalid token")
    return token
