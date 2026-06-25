import datetime
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from loguru import logger


def resolve_timezone(name: str | None):
    """Return a tzinfo for the configured IANA name, or the OS-local timezone.

    Using the OS-local timezone needs no extra dependency; an explicit IANA name
    uses zoneinfo (and the `tzdata` package on platforms without a system tz db).
    """
    if name:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception as e:  # pragma: no cover - bad tz name / missing tzdata
            logger.warning(
                "Invalid HYPOGUM_TIMEZONE {!r} ({}); using OS-local", name, e,
            )
    return datetime.datetime.now().astimezone().tzinfo


def now_local(name: str | None = None) -> datetime.datetime:
    """Current time as an offset-aware datetime in the configured (or OS-local) tz."""
    return datetime.datetime.now(resolve_timezone(name))


def local_iso(name: str | None = None) -> str:
    """Offset-aware local ISO timestamp to seconds, e.g. 2026-06-25T00:12:02-07:00."""
    return now_local(name).isoformat(timespec="seconds")


def local_date(name: str | None = None) -> str:
    """Local calendar date, YYYY-MM-DD."""
    return now_local(name).strftime("%Y-%m-%d")


def to_local_iso(value: str, name: str | None = None) -> str:
    """Convert a (UTC or offset-aware) ISO string to offset-aware local ISO.

    Naive inputs are assumed UTC. Unparseable inputs are returned unchanged.
    """
    try:
        dt = datetime.datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return dt.astimezone(resolve_timezone(name)).isoformat(timespec="seconds")


def tz_label(name: str | None = None) -> str:
    """A display label for the configured tz — IANA key when available, else abbrev."""
    tz = resolve_timezone(name)
    return getattr(tz, "key", None) or now_local(name).strftime("%Z") or str(tz)


def _find_env() -> Path | None:
    for candidate in [
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
    ]:
        if candidate.exists():
            return candidate
    return None


_env = _find_env()
if _env:
    load_dotenv(_env)
    logger.info("Loaded .env from {}", _env)
else:
    logger.info("No .env file found (cwd={})", Path.cwd())


def _resolve_data_dir() -> Path:
    env_data_dir = os.environ.get("HYPOGUM_DATA_DIR", "").strip()
    if env_data_dir:
        data_dir = Path(env_data_dir).resolve()
        source = "HYPOGUM_DATA_DIR"
    else:
        data_dir = (Path(__file__).resolve().parent.parent / "data").resolve()
        source = "default"
    logger.info("Using data dir {} (source: {})", data_dir, source)
    return data_dir


def _resolve_prompts_dir() -> Path:
    env_prompts_dir = os.environ.get("HYPOGUM_PROMPTS_DIR", "").strip()
    if env_prompts_dir:
        prompts_dir = Path(env_prompts_dir).resolve()
        source = "HYPOGUM_PROMPTS_DIR"
    else:
        prompts_dir = (Path(__file__).resolve().parent / "agent" / "prompts").resolve()
        source = "default"
    logger.info("Using prompts dir {} (source: {})", prompts_dir, source)
    return prompts_dir


def _resolve_memory_dir() -> Path:
    env_memory_dir = os.environ.get("HYPOGUM_MEMORY_DIR", "").strip()
    if env_memory_dir:
        memory_dir = Path(env_memory_dir).resolve()
        source = "HYPOGUM_MEMORY_DIR"
    else:
        data_dir = _resolve_data_dir()
        memory_dir = (data_dir / "memory").resolve()
        source = "default"
    logger.info("Using memory dir {} (source: {})", memory_dir, source)
    return memory_dir


@dataclass(slots=True)
class Config:
    # ── agent / mcp: HTTP db provider target (the `hypogum db` service) ──
    db_url: str = "http://localhost:8055"

    # ── `hypogum db` service backend ──
    db_dsn: str | None = None
    db_host: str = "0.0.0.0"
    db_port: int = 8055

    data_dir: Path = field(default_factory=_resolve_data_dir)
    prompts_dir: Path = field(default_factory=_resolve_prompts_dir)
    memory_dir: Path = field(default_factory=_resolve_memory_dir)

    llm_provider: Literal["gemini", "openai", "anthropic"] = "gemini"
    llm_model: str = "gemini-3.1-flash-lite"
    google_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # ── agent configuration ──
    agent_command: str = "opencode"
    agent_args: str = "run"
    agent_flags: str = "--format json"
    agent_timeout: int = 1800
    agent_serve_port: int = 4099
    agent_serve_host: str = "127.0.0.1"
    agent_model: str | None = None

    auth_provider: Literal["noauth", "jwt", "oauth2"] = "noauth"
    auth_jwt_secret: str | None = None
    auth_jwt_algorithm: str = "ES256"
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
    screen_dedup_enabled: bool = True
    screen_dedup_threshold: int = 10
    screen_dedup_hash_size: int = 16
    pause_when_locked: bool = True
    pause_when_idle: bool = False
    idle_threshold: int = 300
    notify_on_tips: bool = True
    process_interval: int = 600
    tip_interval: int = 600
    max_artifacts: int = 20
    max_tip_goals: int = 5
    max_tip_events: int = 5
    max_tip_traits: int = 20
    tip_summary_chars: int = 1000
    trait_similarity_threshold: float = 0.5
    memory_lint_interval: int = 86400

    # ── calendar / user input ──
    timezone: str | None = None
    observe_user_input_enabled: bool = True
    user_input_interval: int = 60
    calendar_ics_enabled: bool = False
    calendar_view_enabled: bool = True
    calendar_view_png_enabled: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        data_dir = _resolve_data_dir()

        db_dsn = os.environ.get("HYPOGUM_DB_DSN", "").strip() or None
        if db_dsn is None:
            db_dsn = f"sqlite+aiosqlite:///{(data_dir / 'app.db').as_posix()}"

        return cls(
            db_url=os.environ.get("HYPOGUM_DB_URL") or "http://localhost:8055",
            db_dsn=db_dsn,
            db_host=os.environ.get("HYPOGUM_DB_HOST", "0.0.0.0"),
            db_port=int(os.environ.get("HYPOGUM_DB_PORT", "8055")),
            data_dir=data_dir,
            prompts_dir=_resolve_prompts_dir(),
            memory_dir=_resolve_memory_dir(),

            llm_provider=os.environ.get("HYPOGUM_LLM_PROVIDER", "gemini"),  # type: ignore[arg-type]
            llm_model=os.environ.get("HYPOGUM_LLM_MODEL", "gemini-3.1-flash-lite"),
            google_api_key=os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or None,
            openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,

            agent_command=os.environ.get("HYPOGUM_AGENT_COMMAND", "opencode"),
            agent_args=os.environ.get("HYPOGUM_AGENT_ARGS", "run"),
            agent_flags=os.environ.get("HYPOGUM_AGENT_FLAGS", "--format json"),
            agent_timeout=int(os.environ.get("HYPOGUM_AGENT_TIMEOUT", "1800")),
            agent_serve_port=int(os.environ.get("HYPOGUM_AGENT_SERVE_PORT", "4099")),
            agent_serve_host=os.environ.get("HYPOGUM_AGENT_SERVE_HOST", "127.0.0.1"),
            agent_model=os.environ.get("HYPOGUM_AGENT_MODEL") or None,

            auth_provider=os.environ.get("HYPOGUM_AUTH_PROVIDER", "noauth"),  # type: ignore[arg-type]
            auth_jwt_secret=os.environ.get("HYPOGUM_AUTH_JWT_SECRET") or None,
            auth_jwt_algorithm=os.environ.get("HYPOGUM_AUTH_JWT_ALGORITHM", "ES256"),
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
            screen_dedup_enabled=os.environ.get("HYPOGUM_SCREEN_DEDUP_ENABLED", "true").lower() == "true",
            screen_dedup_threshold=int(os.environ.get("HYPOGUM_SCREEN_DEDUP_THRESHOLD", "10")),
            screen_dedup_hash_size=int(os.environ.get("HYPOGUM_SCREEN_DEDUP_HASH_SIZE", "16")),
            pause_when_locked=os.environ.get("HYPOGUM_PAUSE_WHEN_LOCKED", "true").lower() == "true",
            pause_when_idle=os.environ.get("HYPOGUM_PAUSE_WHEN_IDLE", "false").lower() == "true",
            idle_threshold=int(os.environ.get("HYPOGUM_IDLE_THRESHOLD", "300")),
            notify_on_tips=os.environ.get("HYPOGUM_NOTIFY_ON_TIPS", "true").lower() == "true",
            process_interval=int(os.environ.get("HYPOGUM_PROCESS_INTERVAL", "600")),
            tip_interval=int(os.environ.get("HYPOGUM_TIP_INTERVAL", "600")),
            max_artifacts=int(os.environ.get("HYPOGUM_MAX_ARTIFACTS", "20")),
            max_tip_goals=int(os.environ.get("HYPOGUM_MAX_TIP_GOALS", "5")),
            max_tip_events=int(os.environ.get("HYPOGUM_MAX_TIP_EVENTS", "5")),
            max_tip_traits=int(os.environ.get("HYPOGUM_MAX_TIP_TRAITS", "20")),
            tip_summary_chars=int(os.environ.get("HYPOGUM_TIP_SUMMARY_CHARS", "1000")),
            trait_similarity_threshold=float(os.environ.get("HYPOGUM_TRAIT_SIMILARITY_THRESHOLD", "0.5")),
            memory_lint_interval=int(os.environ.get("HYPOGUM_MEMORY_LINT_INTERVAL", "86400")),

            timezone=os.environ.get("HYPOGUM_TIMEZONE") or None,
            observe_user_input_enabled=os.environ.get("HYPOGUM_OBSERVE_USER_INPUT_ENABLED", "true").lower() == "true",
            user_input_interval=int(os.environ.get("HYPOGUM_USER_INPUT_INTERVAL", "60")),
            calendar_ics_enabled=os.environ.get("HYPOGUM_CALENDAR_ICS", "false").lower() == "true",
            calendar_view_enabled=os.environ.get("HYPOGUM_CALENDAR_VIEW", "true").lower() == "true",
            calendar_view_png_enabled=os.environ.get("HYPOGUM_CALENDAR_VIEW_PNG", "true").lower() == "true",
        )
