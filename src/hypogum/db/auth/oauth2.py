import time

from fastapi import HTTPException, Request

from hypogum.db.auth.base import AuthContext, AuthProvider


class OAuth2Provider(AuthProvider):
    """Validates opaque tokens via RFC 7662 introspection endpoint, with caching."""

    def __init__(self, *, introspection_url: str, client_id: str, client_secret: str,
                 user_claim: str = "sub", cache_ttl: int = 300):
        self._url = introspection_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_claim = user_claim
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, dict]] = {}  # token → (expires_at, introspect_result)

    def _clean_cache(self):
        now = time.time()
        self._cache = {k: v for k, v in self._cache.items() if v[0] > now}

    async def _introspect(self, token: str) -> dict:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._url,
                data={"token": token},
                auth=(self._client_id, self._client_secret),
            )
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Token introspection failed")
            data = response.json()
            if not data.get("active", False):
                raise HTTPException(status_code=401, detail="Token is not active")
            return data

    async def authenticate(self, request: Request) -> AuthContext:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Bearer token")
        token = auth_header[len("Bearer "):]

        self._clean_cache()
        if token in self._cache:
            _, data = self._cache[token]
        else:
            data = await self._introspect(token)
            exp = data.get("exp", int(time.time()) + self._cache_ttl)
            self._cache[token] = (time.time() + min(exp - time.time(), self._cache_ttl), data)

        user_id = data.get(self._user_claim, "")
        if not user_id:
            raise HTTPException(status_code=401, detail=f"Introspection response missing '{self._user_claim}' claim")

        scopes = data.get("scope", "")
        if isinstance(scopes, str):
            scopes = [s.strip() for s in scopes.split() if s.strip()]

        return AuthContext(user_id=str(user_id), scopes=scopes)

    async def authenticate_optional(self, request: Request) -> AuthContext | None:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        try:
            return await self.authenticate(request)
        except HTTPException:
            return None
