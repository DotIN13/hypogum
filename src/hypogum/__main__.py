import argparse
import asyncio

from loguru import logger

from hypogum.config import Config

# ── providers / factories ────────────────────

def _make_db(config: Config):
    """Agent/MCP relational provider: always HTTP to the `hypogum db` service."""
    from hypogum.agent.db import RemoteDBStore
    assert config.db_url, "HYPOGUM_DB_URL required (the `hypogum db` service URL)"
    return RemoteDBStore(config.db_url)


def _make_memory_store(config: Config):
    """Memory store: local file-based markdown page CRUD."""
    from hypogum.memory.store import MemoryStore
    config.memory_dir.mkdir(parents=True, exist_ok=True)
    return MemoryStore(config.memory_dir, tz_name=config.timezone)


def _make_llm(config: Config):
    if config.llm_provider == "gemini":
        from hypogum.llm.gemini import GeminiProvider
        assert config.google_api_key, "GOOGLE_API_KEY required for Gemini provider"
        return GeminiProvider(
            api_key=config.google_api_key,
            model=config.llm_model,
        )
    elif config.llm_provider == "openai":
        from hypogum.llm.openai import OpenAIProvider
        assert config.openai_api_key, "OPENAI_API_KEY required for OpenAI provider"
        return OpenAIProvider(
            api_key=config.openai_api_key,
            model=config.llm_model,
        )
    elif config.llm_provider == "anthropic":
        from hypogum.llm.anthropic import AnthropicProvider
        assert config.anthropic_api_key, "ANTHROPIC_API_KEY required for Anthropic provider"
        return AnthropicProvider(
            api_key=config.anthropic_api_key,
            model=config.llm_model,
        )
    raise ValueError(f"Unknown LLM provider: {config.llm_provider}")


def _make_auth(config: Config):
    if config.auth_provider == "noauth":
        from hypogum.db.auth.noauth import NoAuthProvider
        return NoAuthProvider(user_id="default")
    elif config.auth_provider == "jwt":
        from hypogum.db.auth.jwt import JWTAuthProvider
        return JWTAuthProvider(
            secret=config.auth_jwt_secret,
            algorithm=config.auth_jwt_algorithm,
            jwks_url=config.auth_jwt_jwks_url,
            issuer=config.auth_jwt_issuer,
            audience=config.auth_jwt_audience,
        )
    elif config.auth_provider == "oauth2":
        from hypogum.db.auth.oauth2 import OAuth2Provider
        assert config.auth_oauth2_introspection_url, "AUTH_OAUTH2_INTROSPECTION_URL required"
        assert config.auth_oauth2_client_id, "AUTH_OAUTH2_CLIENT_ID required"
        assert config.auth_oauth2_client_secret, "AUTH_OAUTH2_CLIENT_SECRET required"
        return OAuth2Provider(
            introspection_url=config.auth_oauth2_introspection_url,
            client_id=config.auth_oauth2_client_id,
            client_secret=config.auth_oauth2_client_secret,
            user_claim=config.auth_oauth2_user_claim,
            cache_ttl=config.auth_oauth2_cache_ttl,
        )
    raise ValueError(f"Unknown auth provider: {config.auth_provider}")


def _make_observers(config: Config):
    from hypogum.agent.observers.camera import CameraObserver
    from hypogum.agent.observers.screen import ScreenObserver
    from hypogum.agent.observers.user_input import UserInputObserver
    from hypogum.agent.utils.window_detector import create_window_detector

    window_detector = create_window_detector() if config.observe_detect_windows else None

    observers = []
    if config.observe_screen_enabled:
        observers.append(ScreenObserver(
            window_detector=window_detector,
            interval=config.observe_screen_interval,
            dedup_enabled=config.screen_dedup_enabled,
            dedup_threshold=config.screen_dedup_threshold,
            dedup_hash_size=config.screen_dedup_hash_size,
        ))
    if config.observe_camera_enabled:
        observers.append(CameraObserver(
            interval=config.observe_camera_interval,
        ))
    if config.observe_user_input_enabled:
        observers.append(UserInputObserver(
            inbox_dir=config.memory_dir / ".tasks" / "user-input",
            interval=config.user_input_interval,
        ))
    return observers


def _make_notifier(config: Config):
    if not config.notify_on_tips:
        return None
    from hypogum.agent.utils.notifier import create_notifier
    return create_notifier()


def _make_pause_gate(config: Config):
    if not (config.pause_when_locked or config.pause_when_idle):
        return None
    from hypogum.agent.utils.activity_detector import (
        PauseGate,
        create_activity_detector,
    )
    return PauseGate(
        create_activity_detector(),
        pause_when_locked=config.pause_when_locked,
        pause_when_idle=config.pause_when_idle,
        idle_threshold=config.idle_threshold,
    )


# ── CLI commands ─────────────────────────────

def cmd_db(args):
    """Run the standalone db service: relational (local/remote via DSN)."""
    config = Config.from_env()

    from hypogum.db.relational.engine import SQLAlchemyDBStore
    from hypogum.db.server import run_db_service

    assert config.db_dsn, "HYPOGUM_DB_DSN could not be resolved"
    db = SQLAlchemyDBStore(config.db_dsn)
    auth = _make_auth(config)

    host = args.host if args.host is not None else config.db_host
    port = args.port if args.port is not None else config.db_port
    logger.info("Starting `hypogum db` (dsn={})", config.db_dsn)
    run_db_service(host, port, db=db, auth=auth)


def cmd_agent(args):
    config = Config.from_env()
    db = _make_db(config)
    llm = _make_llm(config)
    memory_store = _make_memory_store(config)
    observers = _make_observers(config)
    notifier = _make_notifier(config)
    pause_gate = _make_pause_gate(config)

    from hypogum.agent import run_agent

    async def _run():
        await run_agent(config, db, llm, memory_store, observers,
                        notifier=notifier, pause_gate=pause_gate)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Agent interrupted")


def cmd_mcp(args):
    config = Config.from_env()
    db = _make_db(config)
    llm = _make_llm(config)
    memory_store = _make_memory_store(config)

    from hypogum.mcp_server import create_mcp_server
    mcp = create_mcp_server(config, db, llm, memory_store, config.user_id)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "http":
        host = args.host or "0.0.0.0"
        port = args.port or 8080
        mcp.run(transport="sse", host=host, port=port)


def cmd_note(args):
    """Queue a free-text note for the UserInputObserver to ingest."""
    import uuid

    from hypogum.config import now_local

    config = Config.from_env()
    inbox = config.memory_dir / ".tasks" / "user-input"
    inbox.mkdir(parents=True, exist_ok=True)

    ts = now_local(config.timezone).strftime("%Y-%m-%dT%H-%M-%S")
    path = inbox / f"note_{ts}_{uuid.uuid4().hex[:6]}.md"
    body = (f"# {args.title}\n\n" if args.title else "") + args.text + "\n"
    path.write_text(body, encoding="utf-8")
    print(f"Queued note → {path}")


def cmd_calendar(args):
    """Export or display the file-based calendar."""
    from pathlib import Path

    config = Config.from_env()

    if args.action == "export":
        from hypogum.calendar.ics import export_ics

        out = Path(args.out) if args.out else config.data_dir / "calendar.ics"
        count = export_ics(config.memory_dir, out, days=args.days)
        print(f"Exported {count} event(s) → {out}")
    elif args.action == "show":
        from hypogum.calendar.parse import load_entries

        entries = load_entries(config.memory_dir)
        if args.date:
            entries = [e for e in entries if e.date == args.date]
        if args.bucket:
            entries = [e for e in entries if e.bucket == args.bucket]
        entries.sort(key=lambda e: (e.date, e.start))
        if not entries:
            print("No calendar entries.")
            return
        for e in entries:
            end = e.end or ("recurs" if e.recurrence else "open")
            start = e.start[11:16] if len(e.start) >= 16 else e.start
            end = end[11:16] if len(end) >= 16 else end
            flag = "*" if e.significant else " "
            print(f"{flag} {e.date} {start}-{end} [{e.bucket}/{e.source}] "
                  f"{e.category}: {e.title}")
    elif args.action == "view":
        import datetime as _dt

        from hypogum.calendar.view import export_view
        from hypogum.config import resolve_timezone

        tz = resolve_timezone(config.timezone)
        today = _dt.datetime.now(tz).date()
        out_dir = Path(args.out_dir) if args.out_dir else config.memory_dir
        res = export_view(config.memory_dir, out_dir, today=today,
                          tz_label=config.timezone or "", png=not args.no_png)
        kind = "+ PNGs" if res["png"] else "(markdown only)"
        print(
            f"Rendered calendar view for {res['entries']} event(s) {kind} → {out_dir}"
        )


# ── entry point ──────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="hypogum",
        description="Standalone background agent with observer, processor, tip engine, and MCP endpoint",
    )
    sub = parser.add_subparsers(dest="command")

    p_db = sub.add_parser("db", help="Start the standalone db service (relational store)")
    p_db.add_argument("--host", default=None)
    p_db.add_argument("--port", type=int, default=None)

    sub.add_parser("agent", help="Run observer -> process -> tip loop")

    p_mcp = sub.add_parser("mcp", help="Start MCP endpoint")
    p_mcp.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    p_mcp.add_argument("--host", default="0.0.0.0")
    p_mcp.add_argument("--port", type=int, default=8080)

    p_note = sub.add_parser("note", help="Queue a free-text note for the agent to ingest")
    p_note.add_argument("text", help="The note text (e.g. 'meeting next Tue 2-3pm with Alice')")
    p_note.add_argument("--title", default=None)

    p_cal = sub.add_parser("calendar", help="Export or display the calendar")
    p_cal.add_argument("action", choices=["export", "show", "view"])
    p_cal.add_argument("--out", default=None, help="ICS output path (export)")
    p_cal.add_argument("--days", type=int, default=None, help="Limit to last N days (export)")
    p_cal.add_argument("--date", default=None, help="Filter to a YYYY-MM-DD day (show)")
    p_cal.add_argument("--bucket", default=None,
                       choices=["suggested", "planned", "observed"],
                       help="Filter to a lifecycle bucket (show)")
    p_cal.add_argument("--out-dir", default=None, help="Output dir for the view (view)")
    p_cal.add_argument("--no-png", action="store_true", help="Skip PNGs (view)")

    args = parser.parse_args()

    if args.command == "db":
        cmd_db(args)
    elif args.command == "agent":
        cmd_agent(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    elif args.command == "note":
        cmd_note(args)
    elif args.command == "calendar":
        cmd_calendar(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
