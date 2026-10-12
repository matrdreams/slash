"""HMAC-SHA256 takeover tokens: device_id|task_id|exp|nonce."""

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from slash.core.errors import TokenError


@dataclass
class TokenClaims:
    device_id: str
    task_id: str
    exp: int
    nonce: str


class TokenService:
    def __init__(self, secret: bytes, ttl_s: int = 300) -> None:
        if not secret:
            raise ValueError("takeover secret is empty")
        self.secret = secret
        self.ttl_s = ttl_s

    def issue(self, device_id: str, task_id: str, *, now: int | None = None) -> tuple[str, TokenClaims]:
        issued_at = int(time.time()) if now is None else now
        claims = TokenClaims(
            device_id=device_id,
            task_id=task_id or "",
            exp=issued_at + self.ttl_s,
            nonce=secrets.token_hex(8),
        )
        return self._sign(claims), claims

    def verify(
        self,
        token: str,
        *,
        device_id: str | None = None,
        now: int | None = None,
    ) -> TokenClaims:
        claims = self._parse(token)
        current = int(time.time()) if now is None else now
        if claims.exp < current:
            raise TokenError("takeover token expired")
        if device_id is not None and claims.device_id != device_id:
            raise TokenError("takeover token is for a different device")
        return claims

    def session_cookie(self, takeover_id: str, exp: int) -> str:
        msg = f"{takeover_id}|{exp}".encode()
        sig = hmac.new(self.secret, msg, hashlib.sha256).hexdigest()
        return f"{takeover_id}.{exp}.{sig}"

    def verify_cookie(self, cookie: str, *, now: int | None = None) -> tuple[str, int]:
        parts = cookie.split(".")
        if len(parts) != 3:
            raise TokenError("malformed takeover cookie")
        takeover_id, exp_text, sig = parts
        try:
            exp = int(exp_text)
        except ValueError as exc:
            raise TokenError("malformed takeover cookie") from exc
        msg = f"{takeover_id}|{exp}".encode()
        expected = hmac.new(self.secret, msg, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise TokenError("bad takeover cookie signature")
        current = int(time.time()) if now is None else now
        if exp < current:
            raise TokenError("takeover cookie expired")
        return takeover_id, exp

    def _sign(self, claims: TokenClaims) -> str:
        message = f"{claims.device_id}|{claims.task_id}|{claims.exp}|{claims.nonce}".encode()
        sig = hmac.new(self.secret, message, hashlib.sha256).hexdigest()
        blob = base64.urlsafe_b64encode(message).decode("ascii").rstrip("=")
        return f"{blob}.{sig}"

    def _parse(self, token: str) -> TokenClaims:
        if "." not in token:
            raise TokenError("malformed takeover token")
        blob, sig = token.rsplit(".", 1)
        padded = blob + "=" * (-len(blob) % 4)
        try:
            message = base64.urlsafe_b64decode(padded.encode("ascii"))
        except Exception as exc:
            raise TokenError("malformed takeover token") from exc
        expected = hmac.new(self.secret, message, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise TokenError("bad takeover token signature")
        try:
            device_id, task_id, exp_text, nonce = message.decode("ascii").split("|")
            exp = int(exp_text)
        except ValueError as exc:
            raise TokenError("malformed takeover token") from exc
        return TokenClaims(device_id=device_id, task_id=task_id, exp=exp, nonce=nonce)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
