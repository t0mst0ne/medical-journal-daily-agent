import json
from datetime import datetime, timezone
from pathlib import Path


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data = {"last_run_at": None, "seen": {}}
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    @property
    def last_run(self):
        value = self.data.get("last_run_at")
        return datetime.fromisoformat(value) if value else None

    def seen(self, key: str) -> bool:
        return key in self.data.setdefault("seen", {})

    def mark(self, key: str):
        self.data.setdefault("seen", {})[key] = datetime.now(timezone.utc).isoformat()

    def save(self):
        self.data["last_run_at"] = datetime.now(timezone.utc).isoformat()
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
