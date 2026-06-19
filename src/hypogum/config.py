import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


def _find_env() -> str | None:
    for candidate in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]:
        if os.path.exists(candidate):
            return candidate
    return None


_env = _find_env()
if _env:
    load_dotenv(_env)


def _default_data_dir() -> Path:
    d = os.environ.get("HYPOGUM_DATA_DIR", "").strip()
    if d:
        return Path(d).resolve()
    return Path(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")).resolve()


def _default_prompts_dir() -> Path:
    d = os.environ.get("HYPOGUM_PROMPTS_DIR", "").strip()
    if d:
        return Path(d).resolve()
    return Path(os.path.dirname(__file__)) / "prompts"


@dataclass
class Config:
    db_mode: Literal["local", "remote"] = "local"
    db_url: str | None = None
    vec_mode: Literal["local", "remote"] = "local"
    vec_url: str | None = None
    store_api_key: str | None = None
    data_dir: Path = field(default_factory=_default_data_dir)
    prompts_dir: Path = field(default_factory=_default_prompts_dir)

    llm_provider: Literal["gemini", "openai", "anthropic"] = "gemini"
    llm_model: str = "gemini-3.5-flash-lite"
    embedding_model: str = "gemini-embedding-2"
    embedding_provider: str | None = None
    google_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    auth_provider: Literal["noauth", "jwt", "oauth2"] = "noauth"
    auth_jwt_secret: str | None = None
    auth_jwt_algorithm: str = "HS256"
    auth_jwt_jwks_url: str | None = None
    auth_jwt_issuer: str | None = None
    auth_jwt_audience: str = "hypogum"
    auth_oauth2_introspection_url: str | None = None
    auth_oauth2_client_id: str | None = None
    auth_oauth2_client_secret: str | None = None
    auth_oauth2_user_claim: str = "sub"
    auth_oauth2_cache_ttl: int = 300

    user_id: str = "default"
    observe_screen_enabled: bool = True
    observe_screen_interval: int = 60
    observe_camera_enabled: bool = False
    observe_camera_interval: int = 120
    observe_quality: int = 85
    observe_max_width: int = 1920
    observe_detect_windows: bool = True
    notify_on_tips: bool = True
    process_interval: int = 300
    tip_interval: int = 0
    confidence_threshold: int = 5
    merge_threshold: float = 0.85
    max_artifacts: int = 20
    max_evidence_entries: int = 10
    max_tip_goals: int = 5
    max_tip_events: int = 5
    max_tip_traits: int = 20
    tip_summary_chars: int = 1000
    trait_similarity_threshold: float = 0.5

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            db_mode=os.environ.get("HYPOGUM_DB_MODE", "local"),  # type: ignore[arg-type]
            db_url=os.environ.get("HYPOGUM_DB_URL") or None,
            vec_mode=os.environ.get("HYPOGUM_VEC_MODE", "local"),  # type: ignore[arg-type]
            vec_url=os.environ.get("HYPOGUM_VEC_URL") or None,
            store_api_key=os.environ.get("HYPOGUM_STORE_API_KEY") or None,
            data_dir=Path(os.environ.get("HYPOGUM_DATA_DIR", str(_default_data_dir()))),
            prompts_dir=Path(os.environ.get("HYPOGUM_PROMPTS_DIR", str(_default_prompts_dir()))),

            llm_provider=os.environ.get("HYPOGUM_LLM_PROVIDER", "gemini"),  # type: ignore[arg-type]
            llm_model=os.environ.get("HYPOGUM_LLM_MODEL", "gemini-3.5-flash-lite"),
            embedding_model=os.environ.get("HYPOGUM_EMBEDDING_MODEL", "gemini-embedding-2"),
            embedding_provider=os.environ.get("HYPOGUM_EMBEDDING_PROVIDER") or None,
            google_api_key=os.environ.get("GOOGLE_API_KEY") or None,
            openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,

            auth_provider=os.environ.get("HYPOGUM_AUTH_PROVIDER", "noauth"),  # type: ignore[arg-type]
            auth_jwt_secret=os.environ.get("HYPOGUM_AUTH_JWT_SECRET") or None,
            auth_jwt_algorithm=os.environ.get("HYPOGUM_AUTH_JWT_ALGORITHM", "HS256"),
            auth_jwt_jwks_url=os.environ.get("HYPOGUM_AUTH_JWT_JWKS_URL") or None,
            auth_jwt_issuer=os.environ.get("HYPOGUM_AUTH_JWT_ISSUER") or None,
            auth_jwt_audience=os.environ.get("HYPOGUM_AUTH_JWT_AUDIENCE", "hypogum"),
            auth_oauth2_introspection_url=os.environ.get("HYPOGUM_AUTH_OAUTH2_INTROSPECTION_URL") or None,
            auth_oauth2_client_id=os.environ.get("HYPOGUM_AUTH_OAUTH2_CLIENT_ID") or None,
            auth_oauth2_client_secret=os.environ.get("HYPOGUM_AUTH_OAUTH2_CLIENT_SECRET") or None,
            auth_oauth2_user_claim=os.environ.get("HYPOGUM_AUTH_OAUTH2_USER_CLAIM", "sub"),
            auth_oauth2_cache_ttl=int(os.environ.get("HYPOGUM_AUTH_OAUTH2_CACHE_TTL", "300")),

            user_id=os.environ.get("HYPOGUM_USER_ID", "default"),
            observe_screen_enabled=os.environ.get("HYPOGUM_OBSERVE_SCREEN_ENABLED", "true").lower() == "true",
            observe_screen_interval=int(os.environ.get("HYPOGUM_OBSERVE_SCREEN_INTERVAL", "60")),
            observe_camera_enabled=os.environ.get("HYPOGUM_OBSERVE_CAMERA_ENABLED", "false").lower() == "true",
            observe_camera_interval=int(os.environ.get("HYPOGUM_OBSERVE_CAMERA_INTERVAL", "120")),
            observe_quality=int(os.environ.get("HYPOGUM_OBSERVE_QUALITY", "85")),
            observe_max_width=int(os.environ.get("HYPOGUM_OBSERVE_MAX_WIDTH", "1920")),
            observe_detect_windows=os.environ.get("HYPOGUM_OBSERVE_DETECT_WINDOWS", "true").lower() == "true",
            notify_on_tips=os.environ.get("HYPOGUM_NOTIFY_ON_TIPS", "true").lower() == "true",
            process_interval=int(os.environ.get("HYPOGUM_PROCESS_INTERVAL", "300")),
            tip_interval=int(os.environ.get("HYPOGUM_TIP_INTERVAL", "0")),
            confidence_threshold=int(os.environ.get("HYPOGUM_CONFIDENCE_THRESHOLD", "5")),
            merge_threshold=float(os.environ.get("HYPOGUM_MERGE_THRESHOLD", "0.85")),
            max_artifacts=int(os.environ.get("HYPOGUM_MAX_ARTIFACTS", "20")),
            max_evidence_entries=int(os.environ.get("HYPOGUM_MAX_EVIDENCE_ENTRIES", "10")),
            max_tip_goals=int(os.environ.get("HYPOGUM_MAX_TIP_GOALS", "5")),
            max_tip_events=int(os.environ.get("HYPOGUM_MAX_TIP_EVENTS", "5")),
            max_tip_traits=int(os.environ.get("HYPOGUM_MAX_TIP_TRAITS", "20")),
            tip_summary_chars=int(os.environ.get("HYPOGUM_TIP_SUMMARY_CHARS", "1000")),
            trait_similarity_threshold=float(os.environ.get("HYPOGUM_TRAIT_SIMILARITY_THRESHOLD", "0.5")),
        )
