import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List


class AuditLogStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> List[Dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def save(self, items: List[Dict]):
        self.path.write_text(
            json.dumps(items[-200:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append(self, item: Dict) -> List[Dict]:
        items = self.load()
        items.append(item)
        self.save(items)
        return items[-200:]

    def clear(self):
        self.save([])

    def export_text(self) -> str:
        lines = []
        for item in self.load():
            lines.append(
                f"[{item.get('time', '--:--:--')}] {item.get('status', 'info').upper()} "
                f"{item.get('stage', '')} | {item.get('detail', '')}"
            )
        return "\n".join(lines)


def build_audit_entry(stage: str, detail: str, status: str = "info") -> Dict:
    return {
        "time": datetime.now().strftime("%H:%M:%S"),
        "stage": stage,
        "detail": detail,
        "status": status,
    }
