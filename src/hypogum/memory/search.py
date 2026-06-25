import json
import subprocess
from pathlib import Path

from loguru import logger


def search_memory(
    query: str,
    memory_dir: Path,
    max_results: int = 20,
) -> list[dict]:
    """Search memory markdown pages with ripgrep.

    Returns list of {file, line_number, line_content, match}.
    """
    try:
        proc = subprocess.run(
            [
                "rg",
                "--json",
                "--ignore-case",
                "--max-count", str(max_results),
                "--glob", "*.md",
                "--glob", "!.tasks/",
                "--glob", "!MEMORY.md",
                query,
                str(memory_dir),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        logger.warning("[memory-search] ripgrep not found; falling back to string search")
        return _fallback_search(query, memory_dir, max_results)
    except subprocess.TimeoutExpired:
        logger.warning("[memory-search] ripgrep timed out")
        return []

    results: list[dict] = []
    for line in proc.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            match = json.loads(line)
            msg_type = match.get("type", "")
            if msg_type == "match":
                data = match.get("data", {})
                path_data = data.get("path", {})
                file_path = path_data.get("text", "")
                rel_path = Path(file_path).relative_to(memory_dir).as_posix() if file_path else ""
                for sub in data.get("submatches", []):
                    m = sub.get("match", {})
                    results.append({
                        "file": rel_path,
                        "line_number": data.get("line_number", 1),
                        "line_content": data.get("lines", {}).get("text", "").rstrip("\n"),
                        "match": m.get("text", query),
                    })
        except (json.JSONDecodeError, KeyError):
            continue

    return results[:max_results]


def _fallback_search(query: str, memory_dir: Path, max_results: int) -> list[dict]:
    results: list[dict] = []
    ql = query.lower()
    for f in sorted(memory_dir.rglob("*.md")):
        if ".tasks" in f.parts or f.name == "MEMORY.md":
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").split("\n")
        except OSError:
            continue
        rel = f.relative_to(memory_dir).as_posix()
        for i, line in enumerate(lines):
            if ql in line.lower():
                results.append({
                    "file": rel,
                    "line_number": i + 1,
                    "line_content": line[:200],
                    "match": query,
                })
                if len(results) >= max_results:
                    return results
    return results
