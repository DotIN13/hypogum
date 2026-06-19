import argparse
import asyncio
import signal
import sys

from loguru import logger

from hypogum.config import Config
from hypogum.db.local import LocalDBStore
from hypogum.vector.local import LocalVectorStore


def _make_db(config: Config):
    if config.db_mode == "remote":
        from hypogum.db.remote import RemoteDBStore
        assert config.db_url, "HYPOGUM_DB_URL required for remote db mode"
        return RemoteDBStore(config.db_url, config.store_api_key)
    db = LocalDBStore(str(config.data_dir / "app.db"))
    return db


def _make_vec(config: Config):
    if config.vec_mode == "remote":
        from hypogum.vector.remote import RemoteVectorStore
        assert config.vec_url, "HYPOGUM_VEC_URL required for remote vector mode"
        return RemoteVectorStore(config.vec_url, config.store_api_key)
    vec = LocalVectorStore(str(config.data_dir / "chroma.db"))
    return vec


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
        from hypogum.auth.noauth import NoAuthProvider
        return NoAuthProvider(user_id="default")
    elif config.auth_provider == "jwt":
        from hypogum.auth.jwt import JWTAuthProvider
        return JWTAuthProvider(
            secret=config.auth_jwt_secret,
            algorithm=config.auth_jwt_algorithm,
            jwks_url=config.auth_jwt_jwks_url,
            issuer=config.auth_jwt_issuer,
            audience=config.auth_jwt_audience,
        )
    elif config.auth_provider == "oauth2":
        from hypogum.auth.oauth2 import OAuth2Provider
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
    from hypogum.observers.screen import ScreenObserver
    from hypogum.observers.camera import CameraObserver
    from hypogum.utils.window_detector import create_window_detector

    window_detector = create_window_detector() if config.observe_detect_windows else None

    observers = []
    if config.observe_screen_enabled:
        observers.append(ScreenObserver(
            window_detector=window_detector,
            interval=config.observe_screen_interval,
        ))
    if config.observe_camera_enabled:
        observers.append(CameraObserver(
            interval=config.observe_camera_interval,
        ))
    return observers


def _make_notifier(config: Config):
    if not config.notify_on_tips:
        return None
    from hypogum.utils.notifier import create_notifier
    return create_notifier()


def _is_local(obj) -> bool:
    return isinstance(obj, (LocalDBStore, LocalVectorStore))


# ── CLI commands ─────────────────────────────

def cmd_store(args):
    config = Config.from_env()
    db = _make_db(config)
    vec = _make_vec(config)
    auth = _make_auth(config)

    if not _is_local(db) or not _is_local(vec):
        logger.error("store subcommand requires local db/vec modes")
        sys.exit(1)

    from hypogum.store import run_store
    run_store(args.host, args.port, db=db, vec=vec, auth=auth)


async def _init_locals_async(db, vec):
    if isinstance(db, LocalDBStore):
        await db.init()
    if isinstance(vec, LocalVectorStore):
        await vec.init()


def cmd_agent(args):
    config = Config.from_env()
    db = _make_db(config)
    vec = _make_vec(config)
    llm = _make_llm(config)
    observers = _make_observers(config)
    notifier = _make_notifier(config)

    from hypogum.agent import run_agent

    async def _run():
        await _init_locals_async(db, vec)
        await run_agent(config, db, vec, llm, observers, notifier=notifier)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("Agent interrupted")


def cmd_mcp(args):
    config = Config.from_env()
    db = _make_db(config)
    vec = _make_vec(config)
    llm = _make_llm(config)

    async def _init():
        await _init_locals_async(db, vec)

    asyncio.run(_init())

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

    p_store = sub.add_parser("store", help="Start data store HTTP server")
    p_store.add_argument("--host", default="0.0.0.0")
    p_store.add_argument("--port", type=int, default=8000)

    p_agent = sub.add_parser("agent", help="Run observer -> process -> tip loop")

    p_mcp = sub.add_parser("mcp", help="Start MCP endpoint")
    p_mcp.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    p_mcp.add_argument("--host", default="0.0.0.0")
    p_mcp.add_argument("--port", type=int, default=8080)

    args = parser.parse_args()

    if args.command == "store":
        cmd_store(args)
    elif args.command == "agent":
        cmd_agent(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
