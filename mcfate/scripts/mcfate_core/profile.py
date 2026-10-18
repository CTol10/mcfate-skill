"""个人探索记录的本地持久化（单 JSON 文件，无数据库依赖）。

边界说明：
- 只记录用户“明确标记”的餐品，不从订单或推荐结果反推“吃过”。
- 未标记 ≠ 没吃过；因此所有依赖历史的算法都要先看 history_reliable。
- 文件损坏时不崩溃，降级为空档案并给出提示。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import config

VALID_STATUS = ("tried", "liked", "disliked", "rejected")
STATUS_LABEL = {
    "tried": "已尝试",
    "liked": "喜欢",
    "disliked": "不喜欢",
    "rejected": "不想再被推荐",
}


def default_path() -> Path:
    """默认落在用户目录，避免污染项目仓库。"""
    custom = os.environ.get("MCFATE_HOME")
    root = Path(custom) if custom else Path.home() / ".mcfate"
    return root / "profile.json"


def _today() -> str:
    return date.today().isoformat()


@dataclass
class Profile:
    items: Dict[str, Dict[str, Any]]
    recent: List[Dict[str, Any]]
    preferences: Dict[str, List[str]]
    dates: List[str]
    warnings: List[str]

    @classmethod
    def empty(cls, warnings: Optional[List[str]] = None) -> "Profile":
        return cls(items={}, recent=[], preferences={}, dates=[], warnings=list(warnings or []))

    @classmethod
    def load(cls, path: Path) -> "Profile":
        if not path.exists():
            return cls.empty()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return cls.empty([f"个人档案读取失败，本轮按空档案处理：{exc}"])
        if not isinstance(raw, dict):
            return cls.empty(["个人档案格式异常，本轮按空档案处理"])

        items = raw.get("items") if isinstance(raw.get("items"), dict) else {}
        recent = raw.get("recent") if isinstance(raw.get("recent"), list) else []
        preferences = raw.get("preferences") if isinstance(raw.get("preferences"), dict) else {}
        dates = raw.get("dates") if isinstance(raw.get("dates"), list) else []
        return cls(
            items={str(k): v for k, v in items.items() if isinstance(v, dict)},
            recent=[r for r in recent if isinstance(r, dict)],
            preferences={str(k): [str(x) for x in v] for k, v in preferences.items() if isinstance(v, list)},
            dates=[str(d) for d in dates],
            warnings=[],
        )

    @classmethod
    def from_dict(cls, raw: Any) -> "Profile":
        if not isinstance(raw, dict) or not raw:
            return cls.empty()
        items = raw.get("items") if isinstance(raw.get("items"), dict) else {}
        return cls(
            items={str(k): v for k, v in items.items() if isinstance(v, dict)},
            recent=[r for r in (raw.get("recent") or []) if isinstance(r, dict)],
            preferences={str(k): [str(x) for x in v] for k, v in (raw.get("preferences") or {}).items() if isinstance(v, list)},
            dates=[str(d) for d in (raw.get("dates") or [])],
            warnings=[],
        )

    # ---------- 写入 ----------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "items": self.items,
            "recent": self.recent[: config.RECENT_LIMIT],
            "preferences": self.preferences,
            "dates": self.dates,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        handle, temp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def mark(self, code: str, name: str, category: str = "", status: str = "tried", day: Optional[str] = None) -> Dict[str, Any]:
        if status not in VALID_STATUS:
            raise ValueError(f"未知状态：{status}")
        code = str(code)
        entry = self.items.setdefault(code, {})
        entry.update({"name": name, "category": category or entry.get("category", ""), "status": status})
        entry["date"] = day or _today()
        if status == "liked":
            entry.pop("disliked", None)
        elif status == "disliked":
            entry.pop("liked", None)
        self._touch_day(entry["date"])
        return entry

    def add_recent(self, code: str, name: str, category: str = "", day: Optional[str] = None) -> None:
        stamp = day or _today()
        self.recent = [r for r in self.recent if str(r.get("code")) != str(code)]
        self.recent.insert(0, {"code": str(code), "name": name, "category": category, "date": stamp})
        self.recent = self.recent[: config.RECENT_LIMIT]
        self._touch_day(stamp)

    def prune_rejected(self) -> None:
        rejected = [code for code, entry in self.items.items() if entry.get("status") == "rejected"]
        if len(rejected) <= config.REJECT_MEMORY_LIMIT:
            return
        rejected.sort(key=lambda code: self.items[code].get("date", ""))
        for code in rejected[: len(rejected) - config.REJECT_MEMORY_LIMIT]:
            self.items.pop(code, None)

    def _touch_day(self, day: str) -> None:
        if day not in self.dates:
            self.dates.append(day)

    # ---------- 读取 ----------

    def status(self, code: str) -> Optional[str]:
        entry = self.items.get(str(code))
        return entry.get("status") if entry else None

    def name_of(self, code: str) -> str:
        entry = self.items.get(str(code)) or {}
        return str(entry.get("name") or "")

    @property
    def tried_codes(self) -> set:
        return {code for code, entry in self.items.items() if entry.get("status") in ("tried", "liked", "disliked")}

    @property
    def liked_codes(self) -> set:
        return {code for code, entry in self.items.items() if entry.get("status") == "liked"}

    @property
    def disliked_codes(self) -> set:
        return {code for code, entry in self.items.items() if entry.get("status") == "disliked"}

    @property
    def rejected_codes(self) -> set:
        return {code for code, entry in self.items.items() if entry.get("status") == "rejected"}

    @property
    def history_reliable(self) -> bool:
        """只有存在用户明确标记的记录，才认为历史可用。"""
        return bool(self.tried_codes)

    def tried_categories(self) -> set:
        return {str(entry.get("category")) for entry in self.items.values() if entry.get("status") in ("tried", "liked", "disliked") and entry.get("category")}

    def recent_codes(self, limit: int = config.RECENT_LIMIT) -> List[str]:
        return [str(r.get("code")) for r in self.recent[:limit] if r.get("code") is not None]

    def recent_categories(self, limit: int = config.RECENT_LIMIT) -> List[str]:
        return [str(r.get("category")) for r in self.recent[:limit] if r.get("category")]

    def preference(self, key: str) -> List[str]:
        return list(self.preferences.get(key) or [])

    def streak_days(self, today: Optional[str] = None) -> int:
        """连续探索天数：仅基于有记录的真实日期，缺口即中断。"""
        if not self.dates:
            return 0
        known = set(self.dates)
        cursor = date.fromisoformat(today or _today())
        if cursor.isoformat() not in known:
            cursor = cursor - timedelta(days=1)
        streak = 0
        while cursor.isoformat() in known:
            streak += 1
            cursor -= timedelta(days=1)
        return streak

    def summary(self, today: Optional[str] = None) -> Dict[str, Any]:
        return {
            "history_reliable": self.history_reliable,
            "tried_count": len(self.tried_codes),
            "liked_count": len(self.liked_codes),
            "disliked_count": len(self.disliked_codes),
            "rejected_count": len(self.rejected_codes),
            "categories": sorted(self.tried_categories()),
            "streak_days": self.streak_days(today),
            "recent": [{"code": r.get("code"), "name": r.get("name"), "category": r.get("category")} for r in self.recent[:5]],
            "warnings": self.warnings,
        }

    def progress(self, menu: Iterable[Any]) -> Dict[str, Any]:
        """按品类统计图鉴进度（分母来自当前菜单）。"""
        total: Dict[str, int] = {}
        tried: Dict[str, int] = {}
        for item in menu:
            category = getattr(item, "category", "") or "未分类"
            total[category] = total.get(category, 0) + 1
            if getattr(item, "code", None) in self.tried_codes:
                tried[category] = tried.get(category, 0) + 1
        rows = [
            {
                "category": category,
                "tried": tried.get(category, 0),
                "total": count,
                "ratio": round(tried.get(category, 0) / count, 3) if count else 0.0,
            }
            for category, count in sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        return {
            "categories": rows,
            "explored_categories": sum(1 for row in rows if row["tried"] > 0),
            "total_categories": len(rows),
            "next_suggestion": next((row["category"] for row in rows if row["tried"] == 0), None),
        }


def merge(base: Profile, extra: Any) -> Profile:
    """导入档案时做合并，绝不覆盖已有真实记录。"""
    incoming = Profile.from_dict(extra)
    for code, entry in incoming.items.items():
        if code not in base.items:
            base.items[code] = entry
            continue
        current = base.items[code]
        if entry.get("date", "") >= current.get("date", ""):
            current.update({k: v for k, v in entry.items() if v not in (None, "")})
    known = {str(r.get("code")) for r in base.recent}
    for row in incoming.recent:
        if row.get("code") is not None and str(row.get("code")) not in known:
            base.recent.append(row)
    base.recent.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    base.recent = base.recent[: config.RECENT_LIMIT]
    for key, values in incoming.preferences.items():
        bucket = base.preferences.setdefault(key, [])
        for value in values:
            if value not in bucket:
                bucket.append(value)
    for day in incoming.dates:
        if day not in base.dates:
            base.dates.append(day)
    base.dates.sort()
    return base


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
