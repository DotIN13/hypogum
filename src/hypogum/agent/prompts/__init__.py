"""Jinja2-based prompt rendering for hypogum LLM prompts."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template


_env_cache: dict[Path, Environment] = {}


def _get_env(prompts_dir: Path) -> Environment:
    if prompts_dir not in _env_cache:
        _env_cache[prompts_dir] = Environment(
            loader=FileSystemLoader(str(prompts_dir)),
            autoescape=False,
            keep_trailing_newline=True,
        )
    return _env_cache[prompts_dir]


def render_prompt(prompts_dir: Path, name: str, **vars) -> str:
    """Load and render a prompt template by filename (e.g. 'describe_prompt.md')."""
    env = _get_env(prompts_dir)
    template: Template = env.get_template(name)
    return template.render(**vars)
