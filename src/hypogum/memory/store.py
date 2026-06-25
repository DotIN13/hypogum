import datetime
import re
from importlib import resources
from pathlib import Path

from loguru import logger


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


class MemoryStore:
    """File-based CRUD for markdown memory pages under a root directory."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for sub in ["entities", "traits", "events", "goals", "tips"]:
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self._bootstrap_conventions()

    def _bootstrap_conventions(self) -> None:
        """Copy MEMORY.md conventions from package on first run."""
        target = self.root / "MEMORY.md"
        if target.exists():
            return
        try:
            content = resources.read_text("hypogum.agent.prompts", "MEMORY.md")
            target.write_text(content, encoding="utf-8")
            logger.info("[MemoryStore] bootstrapped MEMORY.md conventions")
        except Exception:
            pass

    def read_page(self, path: str) -> str:
        full = self.root / path
        if not full.exists():
            raise FileNotFoundError(f"Memory page not found: {path}")
        return full.read_text(encoding="utf-8")

    def write_page(self, path: str, content: str) -> None:
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        logger.info("[MemoryStore] wrote {}", path)

    def list_pages(self, subdir: str | None = None) -> list[str]:
        base = self.root / subdir if subdir else self.root
        if not base.exists():
            return []
        pages: list[str] = []
        for f in sorted(base.rglob("*.md")):
            rel = f.relative_to(self.root).as_posix()
            if rel.startswith(".") or f.name in ("index.md", "log.md", "MEMORY.md"):
                continue
            pages.append(rel)
        return pages

    def delete_page(self, path: str) -> None:
        full = self.root / path
        if full.exists():
            full.unlink()
            logger.info("[MemoryStore] deleted {}", path)

    def get_index(self) -> str:
        path = self.root / "index.md"
        if not path.exists():
            return "# Memory Index\n\n*(empty)*\n"
        return path.read_text(encoding="utf-8")

    def write_index(self, content: str) -> None:
        (self.root / "index.md").write_text(content, encoding="utf-8")

    def get_log(self, limit: int | None = None) -> str:
        path = self.root / "log.md"
        if not path.exists():
            return "# Memory Log\n\n*(empty)*\n"
        text = path.read_text(encoding="utf-8")
        if limit and limit > 0:
            lines = text.split("\n")
            kept = lines[: min(len(lines), limit * 3)]
            text = "\n".join(kept)
        return text

    def append_log(self, entry: str) -> None:
        path = self.root / "log.md"
        if not path.exists():
            path.write_text("# Memory Log\n\n", encoding="utf-8")
        existing = path.read_text(encoding="utf-8")
        now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")
        header = f"## [{now}] {entry}\n"
        lines = existing.split("\n")
        title = lines[0] if lines else "# Memory Log"
        rest = lines[1:] if lines else []
        new = [title, "", header] + rest
        path.write_text("\n".join(new), encoding="utf-8")

    def list_tips(self, limit: int = 10) -> list[dict]:
        """Return recent tips from memory/tips/, newest first."""
        tips_dir = self.root / "tips"
        if not tips_dir.exists():
            return []

        files = sorted(tips_dir.rglob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        result: list[dict] = []
        for f in files[:limit]:
            content = f.read_text(encoding="utf-8")
            fm = self._parse_frontmatter(content)
            title = self._extract_title(content)
            result.append({
                "path": f.relative_to(self.root).as_posix(),
                "goal": fm.get("goal", f.parent.name),
                "created": fm.get("created", ""),
                "summary": fm.get("summary", title),
                "content": content,
            })
        return result

    def _parse_frontmatter(self, text: str) -> dict:
        """Extract YAML frontmatter as a simple key-value dict."""
        m = _FRONTMATTER_RE.match(text)
        if not m:
            return {}
        result: dict = {}
        for line in m.group(1).split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                key, _, val = line.partition(":")
                result[key.strip()] = val.strip()
        return result

    def _extract_title(self, text: str) -> str:
        """Extract the first H1 heading from markdown."""
        for line in text.split("\n"):
            if line.startswith("# "):
                return line[2:].strip()
        return ""
