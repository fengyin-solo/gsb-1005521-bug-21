"""数据仓库：给每个业务模块准备一份可筛选、可流转的数据，并持久化到本地库。

- 首次启动用示例种子数据初始化到 ``settings.store_path``（JSON 文件库）；
- 之后每次改动整表落盘，措施状态等重启不丢（对应需求里的「状态要进库」）；
- 老票（安全措施旧状态「执行中/已解除」）在入库/读取时统一兼容到新状态序列
  「待签发、已签发、已执行、已终结」，归属沿用既有判定（见 app.identity）。
"""
from __future__ import annotations

import json
import tempfile
from typing import Any

from app.config import settings
from app.seed import SEED_ROWS

# 老状态 -> 新状态序列，老票兼容：「执行中」统一视作「已执行」，「已解除」视作「已终结」。
SAFETY_LEGACY_STATUS = {"执行中": "已执行", "已解除": "已终结"}


def _normalize_safety_row(row: dict[str, Any]) -> dict[str, Any]:
    """老票状态/字段兼容：旧状态映射到新序列，展示字段与机器状态保持同一个值。"""
    status = row.get("status")
    if status in SAFETY_LEGACY_STATUS:
        status = SAFETY_LEGACY_STATUS[status]
        row["status"] = status
    # 措施状态是给人看的状态列，必须与 status 同源，避免列表、详情两处对不上。
    row["措施状态"] = status
    return row


_NORMALIZERS = {
    "safety": _normalize_safety_row,
}


class Store:
    def __init__(self) -> None:
        self._path = settings.store_path
        self._tables: dict[str, list[dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict):
                    self._tables = {
                        name: [dict(row) for row in rows]
                        for name, rows in payload.items()
                        if isinstance(rows, list)
                    }
            except (ValueError, OSError):
                # 库文件损坏时退回种子数据，保证服务可用。
                self._tables = {}
        # 种子里新增的模块补进来，不覆盖库里已有数据。
        for name, rows in SEED_ROWS.items():
            if name not in self._tables:
                self._tables[name] = [dict(row) for row in rows]
        self._migrate()
        self._persist()

    def _migrate(self) -> None:
        """对存量数据做一次兼容整理（老状态映射、字段补齐）。"""
        for module, rows in self._tables.items():
            normalizer = _NORMALIZERS.get(module)
            if normalizer is None:
                continue
            for row in rows:
                normalizer(row)

    def _persist(self) -> None:
        """整表原子落盘：先写临时文件再替换，避免写一半导致库损坏。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self._path.parent, delete=False
        ) as tmp:
            json.dump(self._tables, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        os_replace(tmp_path, str(self._path))

    def commit(self) -> None:
        """业务动作改完数据后调用，把状态落库。"""
        self._persist()

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


def os_replace(src: str, dst: str) -> None:
    """包一层方便测试时打桩，逻辑上等价于 os.replace。"""
    import os

    os.replace(src, dst)


store = Store()
