import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from loguru import logger


def _parse_json_lines(stdout: str) -> tuple[str | None, str]:
    """Extract sessionID and aggregated text from opencode --format json output."""
    session_id = None
    text_parts: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if session_id is None:
            session_id = event.get("sessionID")
        if event.get("type") == "text":
            text_parts.append(event.get("part", {}).get("text", ""))
    return session_id, " ".join(text_parts)


async def invoke_agent(
    task: str,
    memory_dir: Path,
    prompt: str,
    *,
    command: str = "opencode",
    args: list[str] | None = None,
    serve_port: int = 4099,
    timeout: int = 300,
) -> dict:
    """Shell out to the configured agent CLI for a memory task.

    Attaches to a running ``opencode serve`` process to avoid cold boot.
    Agent has write access scoped to the data/ directory only.
    Result is read from <memory_dir>/.tasks/<task>-result.json.

    Returns a dict with ``status``, ``session_id`` (if available), and
    ``output`` (aggregated text from the agent).
    """
    tasks_dir = memory_dir / ".tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    if args is None:
        args = [
            "run",
            "--attach", f"http://127.0.0.1:{serve_port}",
            "--dir", str(memory_dir.parent),
            "--format", "json",
            "--dangerously-skip-permissions",
        ]

    resolved = shutil.which(command)
    if resolved is None:
        logger.error("[memory-agent] command not found: {}", command)
        return {"status": "error", "error": f"agent command not found: {command}"}

    cmd = [resolved] + args + [prompt]
    env = os.environ.copy()
    env["OPENCODE_DISABLE_MOUSE"] = "1"

    logger.info("[memory-agent] invoking {} for task '{}'", command, task)
    logger.debug("[memory-agent] cmd: {}", shlex.join(cmd))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=str(memory_dir.parent),
        )
    except subprocess.TimeoutExpired:
        logger.error("[memory-agent] {} timed out after {}s", task, timeout)
        return {"status": "error", "error": "agent timeout"}

    if proc.returncode != 0:
        logger.error("[memory-agent] {} exited with code {}: {}", task, proc.returncode, proc.stderr[:500])
        return {"status": "error", "error": proc.stderr[:500]}

    session_id, output_text = _parse_json_lines(proc.stdout)

    result_path = tasks_dir / f"{task}-result.json"
    result: dict = {"status": "ok"}
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("[memory-agent] failed to parse result JSON: {}", e)

    if session_id:
        result["session_id"] = session_id
        logger.info("[memory-agent] {} session_id={}", task, session_id)
    if output_text:
        result["output"] = output_text[:500]

    logger.info("[memory-agent] {} completed (stdout: {})", task, output_text[:200])
    return result


async def invoke_agent_continue(
    session_id: str,
    memory_dir: Path,
    prompt: str,
    *,
    command: str = "opencode",
    serve_port: int = 4099,
    timeout: int = 300,
) -> dict:
    """Send a follow-up prompt to an existing opencode session.

    Uses ``--session`` to resume the session created by a prior
    ``invoke_agent`` call.  Agent writes its result to
    <memory_dir>/.tasks/tip-result.json.

    Returns a dict with ``status``, ``session_id``, and ``output``
    (aggregated text from the agent).
    """
    tasks_dir = memory_dir / ".tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    args = [
        "run",
        "--session", session_id,
        "--attach", f"http://127.0.0.1:{serve_port}",
        "--format", "json",
        "--dir", str(memory_dir.parent),
        "--dangerously-skip-permissions",
    ]

    resolved = shutil.which(command)
    if resolved is None:
        logger.error("[memory-agent] command not found: {}", command)
        return {"status": "error", "error": f"agent command not found: {command}"}

    cmd = [resolved] + args + [prompt]
    env = os.environ.copy()
    env["OPENCODE_DISABLE_MOUSE"] = "1"

    logger.info("[memory-agent] continuing session {} for tips", session_id)
    logger.debug("[memory-agent] cmd: {}", shlex.join(cmd))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=str(memory_dir.parent),
        )
    except subprocess.TimeoutExpired:
        logger.error("[memory-agent] tip session timed out after {}s", timeout)
        return {"status": "error", "error": "tip session timeout"}

    if proc.returncode != 0:
        logger.error("[memory-agent] tip session exited with code {}: {}", proc.returncode, proc.stderr[:500])
        return {"status": "error", "error": proc.stderr[:500]}

    _, output_text = _parse_json_lines(proc.stdout)

    result_path = tasks_dir / "tip-result.json"
    result: dict = {"status": "ok", "session_id": session_id}
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result.setdefault("session_id", session_id)
            logger.info("[memory-agent] tip result loaded from {}", result_path)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("[memory-agent] failed to parse tip result JSON: {}", e)
    elif output_text:
        result["output"] = output_text[:1000]
        logger.info("[memory-agent] tip output (no result file): {}", output_text[:200])

    return result
