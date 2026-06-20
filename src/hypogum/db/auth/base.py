from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class AuthContext:
    """Authenticated user identity extracted from a request."""
    user_id: str
    scopes: list[str] = field(default_factory=list)


class AuthProvider(ABC):
    """Extracts and validates user identity from an HTTP request."""

    @abstractmethod
    async def authenticate(self, request) -> AuthContext:
        """Return authenticated AuthContext or raise 401."""
        ...

    @abstractmethod
    async def authenticate_optional(self, request) -> AuthContext | None:
        """Return AuthContext or None if no credentials present."""
        ...
