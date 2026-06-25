from hypogum.db.auth.base import AuthContext, AuthProvider


class NoAuthProvider(AuthProvider):
    """Always returns a fixed 'default' user — for single-user / dev use."""

    def __init__(self, user_id: str = "default"):
        self._user_id = user_id

    async def authenticate(self, request) -> AuthContext:
        return AuthContext(user_id=self._user_id)

    async def authenticate_optional(self, request) -> AuthContext | None:
        return AuthContext(user_id=self._user_id)
