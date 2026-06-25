"""Dev runner — starts hypogum db + opencode serve + agent, graceful shutdown on Ctrl+C."""

import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
VENV_PYTHON = str(PROJECT / ".venv" / "Scripts" / "python.exe")
DATA_DIR = str(PROJECT / "data")
OPENCODE = shutil.which("opencode") or "opencode"

DB_URL = "http://localhost:8055/api/v1/health"

_processes: list[subprocess.Popen] = []


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cleanup() -> None:
    print("\nShutting down...")
    for p in _processes:
        if p.poll() is None:
            p.terminate()
    for p in _processes:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    print("Stopped.")


def _setup_signals() -> None:
    if platform.system() == "Windows":

        def _win_handler(sig: int, frame: object) -> None:
            _cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, _win_handler)
        signal.signal(signal.SIGBREAK, _win_handler)
    else:
        signal.signal(signal.SIGINT, lambda s, f: _cleanup())
        signal.signal(signal.SIGTERM, lambda s, f: _cleanup())


def main() -> None:
    _setup_signals()

    # ── DB service ──────────────────────────────
    print("Starting hypogum db...")
    db = subprocess.Popen(
        [VENV_PYTHON, "-m", "hypogum", "db"],
        stdout=sys.stdout, stderr=sys.stderr,
    )
    _processes.append(db)

    for i in range(30):
        try:
            urllib.request.urlopen(DB_URL, timeout=2)
            print("DB ready.")
            break
        except Exception:
            if db.poll() is not None:
                print("DB failed to start", file=sys.stderr)
                _cleanup()
                sys.exit(1)
            time.sleep(1)
    else:
        print("DB did not become healthy in 30s", file=sys.stderr)
        _cleanup()
        sys.exit(1)

    # ── opencode serve ──────────────────────────
    serve_port = _find_free_port()
    print(f"Starting opencode serve on port {serve_port}...")
    serve = subprocess.Popen(
        [OPENCODE, "serve", "--port", str(serve_port), "--hostname", "127.0.0.1"],
        cwd=DATA_DIR,
        stdout=sys.stdout, stderr=sys.stderr,
    )
    _processes.append(serve)
    time.sleep(2)
    print(f"Opencode serve running at http://127.0.0.1:{serve_port}")

    # ── Agent ───────────────────────────────────
    env = os.environ.copy()
    env["HYPOGUM_AGENT_SERVE_PORT"] = str(serve_port)

    print("Starting hypogum agent...")
    agent = subprocess.Popen(
        [VENV_PYTHON, "-m", "hypogum", "agent"],
        stdout=sys.stdout, stderr=sys.stderr,
        env=env,
    )
    _processes.append(agent)

    print("All running. Press Ctrl+C to stop.")

    try:
        for p in _processes:
            p.wait()
    except Exception:
        _cleanup()
    else:
        _cleanup()


if __name__ == "__main__":
    main()
