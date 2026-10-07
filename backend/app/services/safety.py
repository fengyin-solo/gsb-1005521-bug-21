"""安全措施业务规则：归属判定、状态流转、字段校验与签发结论登记。

状态顺序固定为：待签发 -> 已签发 -> 已执行 -> 已终结，只许逐格前进。
授权口径（与 app.identity 保持一致，全系统只此一处判定）：
- 措施编号、措施类型、涉及设备缺一项不许保存；
- 只有本队组的监护人能签发、终结；只有票上指派的本队组执行人能执行；
- 外队组账号只能查看，任何改动一律拒收并写明缺的授权项；
- 只读账号拒绝一切写操作；执行人与签发人互斥。
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.identity import Identity, latest_filing
from app.store import store

MODULE = "safety"
MAINTENANCE_MODULE = "maintenance"
REQUIRED_FIELDS = ["措施编号", "措施类型", "涉及设备"]
# 登记时建议补齐的人员/期限字段；签发/终结动作会再次强制校验。
STAFF_FIELDS = ["签发人", "执行人", "监护人", "有效期至"]

# 新状态序列（老票「执行中/已解除」在 store 入库时已兼容映射）。
STATUS_ORDER = ["待签发", "已签发", "已执行", "已终结"]
# 动作 -> 目标状态；旧前端/外部调用沿用旧动作名时做别名兼容。
ACTION_RULES = {
    "签发措施": "已签发",
    "开始执行": "已执行",
    "执行措施": "已执行",
    "终结措施": "已终结",
    "解除措施": "已终结",  # 旧动作名兼容
}
ACTION_TO_NEXT = {"已签发": "签发措施", "已执行": "执行措施", "已终结": "终结措施"}


def owner_team(entry: dict[str, Any]) -> str:
    """措施票归属队组：新票直接读「归属队组」；老票缺字段时按监护人最近一次备案回填。

    这是归属判定的唯一口径，列表、详情、导出、动作校验都走这里，
    保证同一张票在各处看到的归属（以及由归属派生的签发权限）完全一致。
    """
    team = str(entry.get("归属队组") or "").strip()
    if team:
        return team
    guardian = str(entry.get("监护人") or "").strip()
    filing = latest_filing(guardian)
    return filing.team if filing else ""


def _forbidden(identity: Identity, entry: dict[str, Any], *, required: str, reason: str) -> HTTPException:
    from app.identity import denied_detail

    detail = denied_detail(required=required, reason=reason)
    detail["operator_team"] = identity.team
    detail["entry_team"] = owner_team(entry)
    return HTTPException(status_code=403, detail=detail)


def _next_action(entry: dict[str, Any]) -> str | None:
    status = entry.get("status")
    if status not in STATUS_ORDER:
        return None
    index = STATUS_ORDER.index(status)
    if index == len(STATUS_ORDER) - 1:
        return None
    return ACTION_TO_NEXT[STATUS_ORDER[index + 1]]


def evaluate(action: str, entry: dict[str, Any], identity: Identity) -> tuple[bool, str, str]:
    """判定经办人能否对该票执行某动作；返回 (允许, 原因, 所需授权项)。

    校验顺序：只读 -> 队组归属 -> 角色与人员 -> 状态顺序，先拦人再拦状态，
    错误信息直接给出缺的是哪一项授权。
    """
    required = ""
    if not identity.writable:
        required = f"非只读账号（当前身份「{identity.name}」为只读）"
        return False, "只读账号仅可查看，不能提交或变更措施状态", required

    team = owner_team(entry)
    if not identity.belongs_to(team):
        required = f"{team}的成员身份（经办人当前归属「{identity.team}」）"
        return False, f"该措施票归属{team}，外队组只能查看、不能改动", required

    target = ACTION_RULES.get(action)
    status = entry.get("status")
    current_index = STATUS_ORDER.index(status) if status in STATUS_ORDER else -1
    target_index = STATUS_ORDER.index(target) if target in STATUS_ORDER else -1

    if action in ("签发措施",):
        required = f"{team}的监护人权限，且为该票监护人"
        if not identity.is_guardian:
            return False, "签发安全措施票必须由本队组监护人操作", required
        if str(entry.get("监护人") or "").strip() != identity.name:
            return False, "只有该票指派的监护人才能签发", required
        signer = str(entry.get("签发人") or "").strip()
        executor = str(entry.get("执行人") or "").strip()
        if signer and executor and signer == executor:
            return False, "执行人与签发人互斥，不能由同一人担任", "执行人与签发人非同一人"
        # 签发将把签发人记成当前监护人，同样不能撞执行人。
        if executor == identity.name:
            return False, "执行人与签发人互斥，监护人不能同时担任该票执行人", "执行人与签发人非同一人"
    elif action in ("开始执行", "执行措施"):
        required = f"{team}的执行人权限，且为该票指派执行人"
        if not identity.is_executor:
            return False, "执行安全措施必须由本队组执行人操作", required
        if str(entry.get("执行人") or "").strip() != identity.name:
            return False, "只有该票指派的执行人才能执行", required
    elif action in ("终结措施", "解除措施"):
        required = f"{team}的监护人权限，且为该票监护人"
        if not identity.is_guardian:
            return False, "终结安全措施票必须由本队组监护人操作", required
        if str(entry.get("监护人") or "").strip() != identity.name:
            return False, "只有该票指派的监护人才能终结", required

    if target is None:
        return False, f"动作「{action}」不属于安全措施可执行范围", required
    if current_index < 0:
        return False, f"当前状态「{status}」不在允许的状态序列里", required
    if target_index != current_index + 1:
        if target_index <= current_index:
            return False, f"措施票已处于「{status}」，不能重复或回退到「{target}」", required
        return False, f"措施状态须按顺序流转，当前「{status}」不能直接跳到「{target}」", required
    return True, "", required


def serialize(entry: dict[str, Any], identity: Identity | None = None) -> dict[str, Any]:
    """列表、详情、导出共用的唯一出口：监护人/状态等字段一处产出、处处一致。"""
    item = dict(entry)
    team = owner_team(entry)
    item["归属队组"] = team
    item["措施状态"] = entry.get("status")
    if identity is not None:
        next_action = _next_action(entry)
        allowed = False
        reason = ""
        required = ""
        if next_action is not None:
            allowed, reason, required = evaluate(next_action, entry, identity)
        elif not identity.writable:
            reason = "只读账号仅可查看"
        elif not identity.belongs_to(team):
            reason = f"该票归属{team}，外队组仅可查看"
        item["可执行动作"] = next_action if allowed else None
        item["不可操作原因"] = reason if not allowed else ""
        item["缺少授权项"] = required if not allowed else ""
    return item


class SafetyService:
    def list_entries(
        self,
        *,
        identity: Identity,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("措施编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size]
        return [serialize(row, identity) for row in page_rows], total

    def get_entry(self, entry_id: int, identity: Identity) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return serialize(entry, identity) if entry is not None else None

    def create_entry(
        self, values: dict[str, Any], identity: Identity
    ) -> tuple[dict[str, Any] | None, list[str], bool]:
        """登记措施票。

        返回 (条目, 缺失字段, 是否命中重复)。措施编号、措施类型、涉及设备缺一项不许保存；
        同一张票（措施编号相同）重复提交只留一条，直接返回既有票，不再新建。
        """
        if not identity.writable:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "FORBIDDEN",
                    "reason": "只读账号仅可查看，不能登记安全措施票",
                    "required_permission": "非只读账号（监护人或执行人）",
                    "operator_team": identity.team,
                    "entry_team": identity.team,
                },
            )
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False

        rows = store.rows(MODULE)
        code = str(values.get("措施编号") or "").strip()
        existing = next((row for row in rows if str(row.get("措施编号") or "").strip() == code), None)
        if existing is not None:
            # 同一张票重复提交只留一条：幂等返回，不再插入，也不产生重复导出行。
            return serialize(existing, identity), [], True

        signer = str(values.get("签发人") or "").strip()
        executor = str(values.get("执行人") or "").strip()
        if signer and executor and signer == executor:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "ROLE_CONFLICT",
                    "reason": "执行人与签发人互斥，不能登记为同一人",
                    "required_permission": "执行人与签发人非同一人",
                },
            )

        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in [*REQUIRED_FIELDS, *STAFF_FIELDS]:
            value = values.get(field)
            if value is not None and str(value).strip():
                entry[field] = str(value).strip()
        # 归属取经办人最近一次备案认定的当前队组。
        entry["归属队组"] = identity.team
        entry["status"] = STATUS_ORDER[0]
        entry["措施状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["操作记录"] = [{"action": "登记", "operator": identity.name, "at": _today()}]
        rows.append(entry)
        store.commit()
        return serialize(entry, identity), [], False

    def run_action(
        self, entry_id: int, action_text: str, identity: Identity, *, conclusion: str | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"安全措施票 {entry_id} 不存在或已归档"
        action = str(action_text or "").strip()
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于安全措施可执行范围"

        allowed, reason, required = evaluate(action, entry, identity)
        if not allowed:
            # 越权操作一律拒收（403），并把缺的授权项写清楚。
            if not identity.writable or not identity.belongs_to(owner_team(entry)):
                raise _forbidden(identity, entry, required=required, reason=reason)
            return None, reason

        target = ACTION_RULES[action]
        entry["status"] = target
        entry["措施状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        records = entry.setdefault("操作记录", [])

        if target == "已签发":
            # 签发人即当前监护人，落库留痕，且已与执行人做互斥校验。
            entry["签发人"] = identity.name
            record_note = conclusion or "同意签发"
            records.append({"action": action, "operator": identity.name, "at": _today(), "结论": record_note})
            # 签发结论落到检修计划的待办列表（按涉及设备关联检修计划）。
            self._push_maintenance_todo(entry, record_note, identity)
        elif target == "已终结":
            records.append({"action": action, "operator": identity.name, "at": _today()})
            self._close_maintenance_todo(entry)
        else:
            records.append({"action": action, "operator": identity.name, "at": _today()})

        store.commit()
        return serialize(entry, identity), f"安全措施票已{action.replace('措施', '').replace('开始', '')}"

    def export_entries(self) -> list[dict[str, Any]]:
        """导出全量清单：按 id 与措施编号去重，同一张票只出现一行。"""
        rows = store.rows(MODULE)
        unique: dict[Any, dict[str, Any]] = {}
        for row in rows:
            key = row.get("id")
            code = str(row.get("措施编号") or "").strip()
            if key in unique or (code and code in {str(r.get("措施编号") or "").strip() for r in unique.values()}):
                continue
            unique[key] = serialize(row)
        return list(unique.values())

    # ------------------------------------------------------------------
    # 签发结论 -> 检修计划待办
    # ------------------------------------------------------------------
    def _push_maintenance_todo(
        self, entry: dict[str, Any], conclusion: str, identity: Identity
    ) -> dict[str, Any]:
        """把签发结论登记进检修计划的待办列表；同一票只登记一次。"""
        todos = store.rows("maintenance_todos")
        existing = next((todo for todo in todos if todo.get("来源票id") == entry.get("id")), None)
        if existing is not None:
            return existing
        plan = self._find_maintenance_plan(entry)
        todo = {
            "id": max((int(row.get("id", 0)) for row in todos), default=0) + 1,
            "事项": f"安全措施票 {entry.get('措施编号')} 已签发",
            "来源票编号": entry.get("措施编号"),
            "来源票id": entry.get("id"),
            "涉及设备": entry.get("涉及设备"),
            "关联计划编号": plan.get("计划编号") if plan else None,
            "签发结论": conclusion,
            "签发人": identity.name,
            "归属队组": owner_team(entry),
            "status": "待办",
            "pending": True,
            "abnormal": False,
            "登记日期": _today(),
        }
        todos.append(todo)
        return todo

    def _close_maintenance_todo(self, entry: dict[str, Any]) -> None:
        """措施票终结后，对应待办同步关闭。"""
        for todo in store.rows("maintenance_todos"):
            if todo.get("来源票id") == entry.get("id"):
                todo["status"] = "已关闭"
                todo["pending"] = False
                todo["关闭日期"] = _today()

    def _find_maintenance_plan(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        """按涉及设备匹配检修计划；匹配不到也不影响签发，待办照常登记。"""
        device = str(entry.get("涉及设备") or "").strip()
        if not device:
            return None
        for plan in store.rows(MAINTENANCE_MODULE):
            if device in str(plan.get("检修设备") or ""):
                return plan
        return None


def _today() -> str:
    from datetime import date

    return date.today().isoformat()
