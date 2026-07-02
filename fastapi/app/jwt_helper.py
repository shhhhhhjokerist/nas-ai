"""
Drop-in replacement for fastapi_jwt_auth, using PyJWT directly.
Compatible with Pydantic V2.
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Request, HTTPException


class AuthJWTException(Exception):
    """Base JWT exception, mirroring fastapi_jwt_auth's exception."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


class AuthJWT:
    """Drop-in replacement for fastapi_jwt_auth.AuthJWT.

    Usage (identical to fastapi_jwt_auth):
        @AuthJWT.load_config
        def get_config():
            return [
                ("authjwt_secret_key", "your-secret"),
                ("authjwt_access_token_expires", 86400),
                ("authjwt_refresh_token_expires", 2592000),
            ]

        @router.get("/protected")
        async def protected(authorize: AuthJWT = Depends()):
            authorize.jwt_required()
            user_id = authorize.get_jwt_subject()
            ...
    """

    _config: dict = {}

    # ── config ──────────────────────────────────────────────────────

    @staticmethod
    def load_config(func):
        """Decorator that stores config from a function returning list-of-tuples."""
        result = func()
        AuthJWT._config = dict(result)
        return func

    # ── FastAPI dependency injection entry point ───────────────────

    def __init__(self, request: Request = None):
        self._request: Optional[Request] = request
        self._token: Optional[str] = None
        self._payload: Optional[dict] = None

    # ── helpers ─────────────────────────────────────────────────────

    @property
    def _secret_key(self) -> str:
        return self._config.get("authjwt_secret_key", "secret")

    def _get_token_from_request(self) -> Optional[str]:
        """Extract JWT from request per configured token_location."""
        if self._request is None:
            return None

        # Authorization: Bearer <token>
        auth_header = self._request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]

        # Cookie fallback
        token_locations = self._config.get("authjwt_token_location", {"headers"})
        if "cookies" in token_locations:
            cookie_key = self._config.get(
                "authjwt_access_cookie_key", "access_token"
            )
            token = self._request.cookies.get(cookie_key)
            if token:
                return token

        return None

    def _decode(self) -> dict:
        token = self._get_token_from_request()
        if not token:
            raise AuthJWTException(401, "Missing token")

        try:
            return jwt.decode(
                token,
                self._secret_key,
                algorithms=["HS256"],
                options={"require": ["exp", "sub", "type", "jti"]},
            )
        except jwt.ExpiredSignatureError:
            raise AuthJWTException(401, "Token has expired")
        except jwt.InvalidTokenError as e:
            raise AuthJWTException(422, f"Invalid token: {e}")

    def _require_type(self, token_type: str) -> None:
        """Decode & verify the token matches expected type (access / refresh)."""
        payload = self._decode()
        if payload.get("type") != token_type:
            raise AuthJWTException(
                401, f"Invalid token type — expected '{token_type}'"
            )
        self._payload = payload

    # ── public API (mirrors fastapi_jwt_auth) ───────────────────────

    def jwt_required(self) -> None:
        """Require a valid access token."""
        self._require_type("access")

    def jwt_refresh_token_required(self) -> None:
        """Require a valid refresh token."""
        self._require_type("refresh")

    def get_jwt_subject(self) -> str:
        """Return the ``sub`` claim from the verified token."""
        if self._payload is None:
            raise AuthJWTException(500, "Token not verified — call jwt_required first")
        return self._payload["sub"]

    def get_raw_jwt(self) -> dict:
        """Return the full decoded payload (e.g. for jti blacklisting)."""
        if self._payload is None:
            raise AuthJWTException(500, "Token not verified — call jwt_required first")
        return dict(self._payload)

    def _create_token(
        self,
        subject: str,
        token_type: str,
        expires_time: Optional[timedelta] = None,
    ) -> str:
        """Shared token-creation logic."""
        default_seconds = self._config.get(
            "authjwt_access_token_expires"
            if token_type == "access"
            else "authjwt_refresh_token_expires",
            24 * 60 * 60,
        )
        if isinstance(default_seconds, timedelta):
            delta = expires_time or default_seconds
        else:
            delta = expires_time or timedelta(seconds=default_seconds)

        now = datetime.utcnow()
        payload = {
            "sub": subject,
            "type": token_type,
            "iat": now,
            "exp": now + delta,
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(payload, self._secret_key, algorithm="HS256")

    def create_access_token(
        self,
        subject: str,
        expires_time: Optional[timedelta] = None,
    ) -> str:
        return self._create_token(subject, "access", expires_time)

    def create_refresh_token(
        self,
        subject: str,
        expires_time: Optional[timedelta] = None,
    ) -> str:
        return self._create_token(subject, "refresh", expires_time)
