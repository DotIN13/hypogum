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


def _make_vec(config: Config):
    """Agent/MCP vector provider: always HTTP to the `hypogum db` service."""
    from hypogum.agent.db import RemoteVectorStore
    assert config.db_url, "HYPOGUM_DB_URL required (the `hypogum db` service URL)"
    return RemoteVectorStore(config.db_url)


def _make_llm(config: Config):
    if config.llm_provider == "gemini":
        from hypogum.llm.gemini import GeminiProvider
        assert config.google_api_key, "GOOGLE_API_KEY required for Gemini provider"
        return GeminiProvider(
            api_key=config.google_api_key,
            model=config.llm_model,
            embedding_model=config.embedding_model,
        )
    elif config.llm_provider == "openai":
        from hypogum.llm.openai import OpenAIProvider
        assert config.openai_api_key, "OPENAI_API_KEY required for OpenAI provider"
        return OpenAIProvider(
            api_key=config.openai_api_key,
            model=config.llm_model,
            embedding_model=config.embedding_model,
        )
    elif config.llm_provider == "anthropic":
        from hypogum.llm.anthropic import AnthropicProvider
        assert config.anthropic_api_key, "ANTHROPIC_API_KEY required for Anthropic provider"

        embedding_provider = None
        if config.embedding_provider:
            assert config.embedding_provider in ("gemini", "openai"), \
                f"Unsupported embedding_provider: {config.embedding_provider}"
            if config.embedding_provider == "gemini":
                from hypogum.llm.gemini import GeminiProvider
                embedding_provider = GeminiProvider(
                    api_key=config.google_api_key or "",
                    embedding_model=config.embedding_model or "gemini-embedding-2",
                )
            elif config.embedding_provider == "openai":
                from hypogum.llm.openai import OpenAIProvider
                embedding_provider = OpenAIProvider(
                    api_key=config.openai_api_key or "",
                    embedding_model=config.embedding_model or "text-embedding-3-small",
                )

        return AnthropicProvider(
            api_key=config.anthropic_api_key,
            model=config.llm_model,
            embedding_provider=embedding_provider,
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
    from hypogum.agent.observers.screen import ScreenObserver
    from hypogum.agent.observers.camera import CameraObserver
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
    return observers


def _make_notifier(config: Config):
    if not config.notify_on_tips:
        return None
    from hypogum.agent.utils.notifier import create_notifier
    return create_notifier()


def _make_pause_gate(config: Config):
    if not (config.pause_when_locked or config.pause_when_idle):
        return None
    from hypogum.agent.utils.activity_detector import create_activity_detector, PauseGate
    return PauseGate(
        create_activity_detector(),
        pause_when_locked=config.pause_when_locked,
        pause_when_idle=config.pause_when_idle,
        idle_threshold=config.idle_threshold,
    )


# ── CLI commands ─────────────────────────────

def cmd_db(args):
    """Run the standalone db service: relational (local/remote via DSN) + local ChromaDB."""
    config = Config.from_env()

    from hypogum.db.relational.engine import SQLAlchemyDBStore
    from hypogum.db.vector.chroma import ChromaVectorStore
    from hypogum.db.server import run_db_service

    assert config.db_dsn, "HYPOGUM_DB_DSN could not be resolved"
    db = SQLAlchemyDBStore(config.db_dsn)
    vec = ChromaVectorStore(config.chroma_dir)
    auth = _make_auth(config)

    host = args.host if args.host is not None else config.db_host
    port = args.port if args.port is not None else config.db_port
    logger.info("Starting `hypogum db` (dsn={}, chroma={})", config.db_dsn, config.chroma_dir)
    run_db_service(host, port, db=db, vec=vec, auth=auth)


def cmd_agent(args):
    config = Config.from_env()
    db = _make_db(config)
    vec = _make_vec(config)
    llm = _make_llm(config)
    observers = _make_observers(config)
    notifier = _make_notifier(config)
    pause_gate = _make_pause_gate(config)

    from hypogum.agent import run_agent

    async def _run():
        await run_agent(config, db, vec, llm, observers, notifier=notifier,
                        pause_gate=pause_gate)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Agent interrupted")


def cmd_mcp(args):
    config = Config.from_env()
    db = _make_db(config)
    vec = _make_vec(config)
    llm = _make_llm(config)

    from hypogum.mcp_server import create_mcp_server
    mcp = create_mcp_server(config, db, vec, llm, config.user_id)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "http":
        host = args.host or "0.0.0.0"
        port = args.port or 8080
        mcp.run(transport="sse", host=host, port=port)


# ── entry point ──────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="hypogum",
        description="Standalone background agent with observer, processor, tip engine, and MCP endpoint",
    )
    sub = parser.add_subparsers(dest="command")

    p_db = sub.add_parser("db", help="Start the standalone db service (relational + ChromaDB)")
    p_db.add_argument("--host", default=None)
    p_db.add_argument("--port", type=int, default=None)

    sub.add_parser("agent", help="Run observer -> process -> tip loop")

    p_mcp = sub.add_parser("mcp", help="Start MCP endpoint")
    p_mcp.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    p_mcp.add_argument("--host", default="0.0.0.0")
    p_mcp.add_argument("--port", type=int, default=8080)

    args = parser.parse_args()

    if args.command == "db":
        cmd_db(args)
    elif args.command == "agent":
        cmd_agent(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
