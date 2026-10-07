"""安全措施接口：维护安全措施票，覆盖签发、执行、终结等动作。

所有可改动接口都通过 ``X-Operator-Id`` 请求头识别操作人（工号或姓名），
服务层据其最近一次备案判定归属队组与角色；越权一律 403 拒收，并写清缺的授权项。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.identity import PERMISSIONS, IdentityError, resolve_actor
from app.services.safety import (
    PermissionDenied,
    SafetyService,
    TicketError,
)

router = APIRouter(prefix="/api/safety", tags=["安全措施"])

service = SafetyService()

LIST_FIELDS = ["措施编号", "措施类型", "涉及设备", "归属队组", "签发人", "执行人", "监护人", "有效期至", "措施状态"]


def _describe_required(required: list[str]) -> list[str]:
    """把服务层返回的缺失授权项（含形如 team:member:运维一队）转成可读说明。"""
    labels: list[str] = []
    for item in required:
        if item.startswith("team:member:"):
            labels.append(f"归属本队组（{item.split(':', 2)[2]}）")
        else:
            labels.append(PERMISSIONS.get(item, item))
    return labels


def _denied(exc: PermissionDenied) -> HTTPException:
    detail: dict[str, Any] = {"message": exc.message}
    if exc.required:
        detail["missing_permissions"] = exc.required
        detail["missing_permission_labels"] = _describe_required(exc.required)
    return HTTPException(status_code=403, detail=detail)


def _actor(x_operator_id: str | None, *, required: bool = True):
    """解析操作人；查询接口允许匿名（只读浏览），改动接口必须带身份。"""
    if not x_operator_id and not required:
        return None
    try:
        return resolve_actor(x_operator_id)
    except IdentityError as exc:
        # 匿名访问可浏览列表；其余情况拒绝
        if not required and not str(x_operator_id or "").strip():
            return None
        raise HTTPException(status_code=401, detail={"message": exc.message})


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按措施编号检索"),
    status: str | None = Query(default=None, description="待签发/已签发/已执行/已终结"),
    team: str | None = Query(default=None, description="按归属队组过滤"),
    page: int = 1,
    size: int = 20,
    x_operator_id: str | None = Header(default=None),
) -> PageResult[dict]:
    """按措施编号、状态与归属队组过滤安全措施列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    actor = _actor(x_operator_id, required=False)
    items, total = service.list_entries(
        actor=actor, keyword=keyword, status=status, team=team, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(x_operator_id: str | None = Header(default=None)) -> dict[str, Any]:
    """导出安全措施清单：同一张票只显示一条（按票 id 去重）。"""
    actor = _actor(x_operator_id, required=False)
    items = service.export_entries(actor=actor)
    return {"module": "safety", "total": len(items), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(
    entry_id: int, x_operator_id: str | None = Header(default=None)
) -> dict[str, Any]:
    """读取单条安全措施票明细；与列表同一出参口径，监护人等字段两处一致。"""
    _actor(x_operator_id, required=False)
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"message": f"安全措施票 {entry_id} 不存在或已归档"})
    return entry


@router.post("", response_model=ActionResult, status_code=201)
def create_entry(
    payload: EntryPayload, x_operator_id: str | None = Header(default=None)
) -> ActionResult:
    """登记一条安全措施票；缺必填字段、互斥冲突、越权都会被拦下并说明原因。"""
    actor = _actor(x_operator_id)
    try:
        entry = service.create_entry(payload.values, actor=actor)
    except PermissionDenied as exc:
        raise _denied(exc)
    except TicketError as exc:
        detail: dict[str, Any] = {"message": exc.message}
        if exc.missing:
            detail["missing_fields"] = exc.missing
        raise HTTPException(status_code=400, detail=detail)
    return ActionResult(ok=True, message="安全措施票已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    x_operator_id: str | None = Header(default=None),
) -> ActionResult:
    """对单条票执行签发、执行、终结；必须按状态顺序流转，越权与跳步一律拒收。"""
    actor = _actor(x_operator_id)
    action = str(payload.values.get("action") or "").strip()
    try:
        entry, message = service.run_action(entry_id, action, actor=actor)
    except PermissionDenied as exc:
        raise _denied(exc)
    except TicketError as exc:
        if "不存在或已归档" in exc.message:
            raise HTTPException(status_code=404, detail={"message": exc.message})
        # 重复提交幂等成功；其余业务冲突（跳步、互斥）按 409 说明
        status_code = 200 if "重复提交" in exc.message else 409
        raise HTTPException(status_code=status_code, detail={"message": exc.message})
    return ActionResult(ok=True, message=message, entry=entry)
