"""安全措施接口：维护安全措施票，覆盖签发、执行、终结与导出。

所有写接口都经过归属判定（app.identity + SafetyService.evaluate）：
只读账号、外队组账号的越权操作一律以 403 拒收，并在 detail 里写明缺的授权项。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.identity import Identity, current_identity, resolve_identity
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.safety import SafetyService

router = APIRouter(prefix="/api/safety", tags=["安全措施"])

service = SafetyService()

LIST_FIELDS = ["措施编号", "措施类型", "涉及设备", "签发人", "执行人", "监护人", "有效期至", "措施状态"]
STATUSES = ["待签发", "已签发", "已执行", "已终结"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按措施编号检索"),
    status: str | None = Query(default=None, description="待签发、已签发、已执行、已终结"),
    page: int = 1,
    size: int = 20,
    identity: Identity = Depends(current_identity),
) -> PageResult[dict]:
    """按措施编号与状态过滤安全措施列表；没有数据时返回空页，不报错。

    列表与详情共用同一个序列化出口，监护人、状态等字段两处必然一致。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        identity=identity, keyword=keyword, status=status, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    operator: str | None = Query(default=None, description="导出链接带不上请求头时用该参数认人"),
) -> dict[str, Any]:
    """导出安全措施清单：全量去重，同一张票只显示一行。"""
    # 导出是只读能力，只认人不拦权限；解析不到身份时报 401。
    identity = resolve_identity(operator)
    if identity is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "UNREGISTERED_OPERATOR",
                "reason": f"经办人「{operator or '未提供'}」未备案，禁止导出",
                "required_permission": "有效的队组备案身份",
            },
        )
    items = service.export_entries()
    return {"module": "safety", "total": len(items), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int, identity: Identity = Depends(current_identity)) -> dict:
    """读取单条安全措施票明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id, identity)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"安全措施票 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(
    payload: EntryPayload, identity: Identity = Depends(current_identity)
) -> ActionResult:
    """登记一条安全措施票。

    措施编号、措施类型、涉及设备缺一项不许保存（400 并列明缺项）；
    同一措施编号重复提交只留一条，幂等返回既有票。
    """
    entry, missing, duplicated = service.create_entry(payload.values, identity)
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MISSING_REQUIRED_FIELDS",
                "reason": f"缺少必填字段：{'、'.join(missing)}，缺一项不许保存",
                "missing_fields": missing,
                "required_permission": "补齐措施编号、措施类型、涉及设备",
            },
        )
    if duplicated:
        return ActionResult(ok=True, message="该措施编号已存在，重复提交只保留原有票据", entry=entry)
    return ActionResult(ok=True, message="安全措施票已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int, payload: EntryPayload, identity: Identity = Depends(current_identity)
) -> ActionResult:
    """对单条安全措施票执行签发、执行、终结；越权与跳状态一律被拦下并说明原因。"""
    values = payload.values if payload and payload.values else {}
    action = str(values.get("action") or "").strip()
    conclusion = values.get("conclusion")
    try:
        entry, message = service.run_action(entry_id, action, identity, conclusion=conclusion)
    except HTTPException:
        raise
    if entry is None:
        # 业务顺序/互斥类拒绝：400；授权类拒绝在 service 内已抛 403。
        raise HTTPException(status_code=400, detail={"code": "ACTION_REJECTED", "reason": message})
    return ActionResult(ok=True, message=message, entry=entry)
