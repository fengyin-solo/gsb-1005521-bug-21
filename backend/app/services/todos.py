"""检修计划待办：安全措施票签发后的结论要落到这里。

安全措施票一经本队监护人签发，就生成一条检修待办；同一票重复签发只保留一条；
票终结后对应待办标记完成。待办单独存一张惰性表，不计入运营概览的各模块计数。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "maintenance_todos"


def _rows() -> list[dict[str, Any]]:
    return store.rows(MODULE)


def ensure_for_issue(entry: dict[str, Any], guardian_name: str) -> dict[str, Any]:
    """签发结论落到检修待办；按安全措施票去重，重复提交只留一条。"""
    safety_id = int(entry.get("id", 0))
    for row in _rows():
        if int(row.get("safetyId", 0)) == safety_id:
            return row

    rows = _rows()
    todo = {
        "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
        "safetyId": safety_id,
        "措施编号": entry.get("措施编号", ""),
        "涉及设备": entry.get("涉及设备", ""),
        "措施类型": entry.get("措施类型", ""),
        "归属队组": entry.get("归属队组", ""),
        "签发人": guardian_name,
        "title": f"落实安全措施 {entry.get('措施编号', '')}（{entry.get('涉及设备', '')}）",
        "来源": "安全措施票签发",
        "状态": "待落实",
        "done": False,
    }
    rows.append(todo)
    return todo


def mark_done_for_close(entry: dict[str, Any]) -> None:
    """票终结后把对应待办标记完成。"""
    safety_id = int(entry.get("id", 0))
    for row in _rows():
        if int(row.get("safetyId", 0)) == safety_id:
            row["状态"] = "已闭环"
            row["done"] = True


def list_todos(
    *,
    team: str | None = None,
    only_open: bool = False,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    rows = list(_rows())
    if team:
        rows = [row for row in rows if row.get("归属队组") == team]
    if only_open:
        rows = [row for row in rows if not row.get("done")]
    if keyword:
        rows = [
            row
            for row in rows
            if keyword in str(row.get("措施编号", "")) or keyword in str(row.get("title", ""))
        ]
    rows.sort(key=lambda row: int(row.get("id", 0)))
    return rows
