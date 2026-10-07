"""人员备案接口：查询花名册与当前操作人（前端用于身份切换和权限展示）。"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.services.identity import IdentityError, resolve_actor, roster

router = APIRouter(prefix="/api/identity", tags=["人员备案"])


@router.get("/roster")
def get_roster() -> dict[str, object]:
    """返回当前生效的人员花名册（一人多岗只保留最近一次备案）。"""
    items = roster()
    return {"total": len(items), "items": items}


@router.get("/me")
def get_me(x_operator_id: str | None = Header(default=None)) -> dict[str, object]:
    """解析请求头里的操作人，回显其归属队组、角色与授权项。"""
    try:
        actor = resolve_actor(x_operator_id)
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail={"message": exc.message})
    return actor.as_dict()
