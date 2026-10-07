"""检修计划接口：维护检修计划，覆盖提交审批、开始执行、确认完工等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.identity import Identity, current_identity
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.maintenance import MaintenanceService
from app.services.maintenance_todos import todo_service

router = APIRouter(prefix="/api/maintenance", tags=["检修计划"])

service = MaintenanceService()

LIST_FIELDS = ["计划编号", "检修设备", "检修类别", "计划开始", "计划结束", "责任人", "安全措施", "计划状态"]
STATUSES = ["待审批", "已批复", "执行中", "已完工"]


@router.get("/todos", response_model=PageResult[dict])
def list_todos(
    status: str | None = Query(default="待办", description="默认只看待办，传空可查全部"),
    keyword: str | None = Query(default=None, description="按措施票编号或涉及设备检索"),
    only_mine: bool = Query(default=True, description="只看本队组的待办"),
    page: int = 1,
    size: int = 20,
    identity: Identity = Depends(current_identity),
) -> PageResult[dict]:
    """安全措施票签发结论生成的检修待办；外队组账号在这里看不到别队组的待办。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    team = identity.team if only_mine else None
    items, total = todo_service.list_todos(
        team=team, status=status or None, keyword=keyword, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按计划编号检索"),
    status: str | None = Query(default=None, description="待审批、已批复、执行中、已完工"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按计划编号与状态过滤检修计划列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条检修计划明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"检修计划 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条检修计划，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="检修计划已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条检修计划执行提交审批、开始执行、确认完工；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出检修计划清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "maintenance", "total": total, "items": items}
