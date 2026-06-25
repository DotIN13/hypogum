import datetime
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from loguru import logger


def _parse_session_id(stdout: str) -> str | None:
    """Extract sessionID from the first JSON line of opencode --format json output."""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = event.get("sessionID")
        if sid:
            return sid
    return None


def _save_session_log(memory_dir: Path, task: str, prompt: str, stdout: str) -> None:
    """Write the opencode run output (JSON events) to a timestamped file in data/sessions/."""
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    log_dir = memory_dir.parent / "sessions"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{ts}-{task}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(stdout.rstrip("\n") + "\n")
    logger.info("[memory-agent] session log saved → {}", path)


async def invoke_agent(
    task: str,
    memory_dir: Path,
    prompt: str,
    *,
    command: str = "opencode",
    args: list[str] | None = None,
    serve_port: int = 4099,
    timeout: int = 300,
    model: str | None = None,
) -> dict:
    """Shell out to the configured agent CLI for a memory task.

    Attaches to a running ``opencode serve`` process to avoid cold boot.
    Agent has write access scoped to the data/ directory only.

    Returns a dict with ``status`` and ``session_id`` (if available).
    """

    if args is None:
        args = [
            "run",
            "--attach", f"http://127.0.0.1:{serve_port}",
            "--dir", str(memory_dir.parent),
            "--format", "json",
            "--dangerously-skip-permissions",
        ]
        if model:
            args += ["--model", model]

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

    _save_session_log(memory_dir, task, prompt, proc.stdout)

    session_id = _parse_session_id(proc.stdout)

    if session_id:
        logger.info("[memory-agent] {} session_id={}", task, session_id)

    logger.info("[memory-agent] {} completed", task)
    return {"status": "ok", "session_id": session_id}


async def invoke_agent_continue(
    session_id: str,
    memory_dir: Path,
    prompt: str,
    *,
    command: str = "opencode",
    serve_port: int = 4099,
    timeout: int = 300,
    model: str | None = None,
) -> dict:
    """Send a follow-up prompt to an existing opencode session.

    Uses ``--session`` to resume the session created by a prior
    ``invoke_agent`` call.
    """

    args = [
        "run",
        "--session", session_id,
        "--attach", f"http://127.0.0.1:{serve_port}",
        "--format", "json",
        "--dir", str(memory_dir.parent),
        "--dangerously-skip-permissions",
    ]
    if model:
        args += ["--model", model]

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

    _save_session_log(memory_dir, f"{session_id[:8]}-continue", prompt, proc.stdout)

    logger.info("[memory-agent] tip session completed")
    return {"status": "ok"}
