"""检修计划待办：安全措施票签发后，签发结论落到这里形成待办列表。"""
from __future__ import annotations

from typing import Any

from app.store import store

TODO_MODULE = "maintenance_todos"


class MaintenanceTodoService:
    def list_todos(
        self,
        *,
        team: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(TODO_MODULE)
        if team:
            rows = [row for row in rows if row.get("归属队组") == team]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("来源票编号") or "") or keyword in str(row.get("涉及设备") or "")
            ]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total


todo_service = MaintenanceTodoService()
