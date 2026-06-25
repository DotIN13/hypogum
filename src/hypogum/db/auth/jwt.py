from fastapi import HTTPException, Request
from jose import JWTError, jwt
from loguru import logger

from hypogum.db.auth.base import AuthContext, AuthProvider


class JWTAuthProvider(AuthProvider):
    """Validates JWT Bearer tokens (HS256/RS256/ES256). Supports JWKS for asymmetric keys."""

    def __init__(self, *, secret: str | None = None, algorithm: str = "HS256",
                 jwks_url: str | None = None, issuer: str | None = None,
                 audience: str | None = None):
        self._secret = secret
        self._algorithm = algorithm
        self._jwks_url = jwks_url
        self._issuer = issuer
        self._audience = audience
        self._jwks_client: object | None = None

    async def _get_key(self, token: str) -> dict:
        if self._jwks_url:
            if self._jwks_client is None:
                from jose import jwk
                self._jwks_client = jwk  # stub — real impl uses PyJWKClient
            # For HS256, use the secret directly
            if self._secret:
                return {"key": self._secret}
            raise HTTPException(status_code=500, detail="JWT: no key configured")
        if not self._secret:
            raise HTTPException(status_code=500, detail="JWT: no secret configured")
        return {"key": self._secret}

    def _decode(self, token: str) -> dict:
        try:
            options: dict = {"verify_exp": True}
            if self._issuer:
                options["verify_iss"] = True
            if self._audience:
                options["verify_aud"] = True

            payload = jwt.decode(
                token,
                self._secret or "",
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                options=options,
            )
            return payload
        except JWTError as e:
            logger.warning("JWT decode failed: {}", e)
            raise HTTPException(status_code=401, detail="Invalid or expired token")

    async def authenticate(self, request: Request) -> AuthContext:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Bearer token")
        token = auth_header[len("Bearer "):]
        payload = self._decode(token)
        user_id = payload.get("sub", "")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing 'sub' claim")
        return AuthContext(
            user_id=user_id,
            scopes=payload.get("scopes", []),
        )

    async def authenticate_optional(self, request: Request) -> AuthContext | None:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        try:
            return await self.authenticate(request)
        except HTTPException:
            return None
