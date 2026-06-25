"""Scaffold the opencode.json that the memory agent's opencode session reads.

The memory agent shells out to ``opencode run --attach ... --dir <memory_dir.parent>``
(see ``hypogum.memory.agent``). opencode resolves project config from that
directory up to the git root and deep-merges it over the user's global config.

We write an ``opencode.json`` there that declares only the ``brave-search`` MCP
and explicitly disables the ``hypogum`` MCP — disabling is required because the
``mcp`` map is merged by key, so a globally-defined ``hypogum`` server would
otherwise stay active and let the memory agent recurse into hypogum's own tools.
"""

from importlib import resources
from pathlib import Path

from loguru import logger


def ensure_agent_opencode_config(opencode_dir: Path) -> None:
    """Overwrite ``<opencode_dir>/opencode.json`` from the shipped template."""
    content = resources.read_text("hypogum.agent.templates", "opencode.json")
    target = Path(opencode_dir) / "opencode.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    logger.info("[scaffold] wrote agent opencode.json -> {}", target)
