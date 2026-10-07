"""安全措施业务规则：归属判定、状态流转、字段校验与授权都收在这里。

归属（症结所在）
    每张票有唯一“归属队组”。新票归属取登记人**最近一次备案**的队组；
    老票没有归属字段时，按既有归属判定兜底：先看票上监护人/签发人当前备案队组，
    再不行才回落到默认队组。列表与详情共用同一套序列化，监护人等字段两处一致。

权限
    - 外队组只能查看、不能改动，越权一律拒收；
    - 只读账号没有任何改动授权，点开也不能提交；
    - 签发 / 终结只能由**本队组监护人**完成；执行只能由本队组执行人完成；
    - 被拒时把“缺的授权项”一并写清楚。

状态流转（严格按顺序）
    待签发 → 已签发 → 已执行 → 已终结，不允许跳步、不允许重复提交。
    签发结论落到检修计划待办（见 services/todos.py）。
"""
from __future__ import annotations

from typing import Any

from app.services import todos
from app.services.identity import (
    PERMISSIONS,
    TEAM_A,
    Actor,
    permission_labels,
    resolve_person,
)
from app.store import store

MODULE = "safety"

REQUIRED_FIELDS = ["措施编号", "措施类型", "涉及设备"]
# 对外展示与详情使用的字段顺序；列表与详情共用，杜绝两处监护人对不上
DISPLAY_FIELDS = [
    "措施编号",
    "措施类型",
    "涉及设备",
    "归属队组",
    "签发人",
    "执行人",
    "监护人",
    "有效期至",
    "措施状态",
]

# 状态严格按顺序：待签发 → 已签发 → 已执行 → 已终结
STATUS_ORDER = ["待签发", "已签发", "已执行", "已终结"]

# 动作 → (目标状态, 需要的授权项)
ACTION_RULES: dict[str, tuple[str, str]] = {
    "签发措施": ("已签发", "safety:issue"),
    "执行措施": ("已执行", "safety:execute"),
    "终结措施": ("已终结", "safety:close"),
}
# 兼容旧页面可能仍发来的旧动作名
ACTION_ALIASES = {"开始执行": "执行措施", "解除措施": "终结措施"}

# 老票旧状态 → 新状态序列，按顺序就近映射，兼容既有数据
LEGACY_STATUS_MAP = {"执行中": "已执行", "已解除": "已终结"}

VALIDITY_FIELD = "有效期至"


class PermissionDenied(Exception):
    """越权操作：携带可读原因与缺失的授权项，供路由层转成 403。"""

    def __init__(self, message: str, required: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.required = required or []

    @property
    def required_labels(self) -> list[str]:
        return permission_labels(self.required)


class TicketError(Exception):
    """业务规则不满足（字段缺失、状态不允许、互斥冲突等）。"""

    def __init__(self, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.missing = missing or []


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def normalize_status(value: Any) -> str:
    """把票上的状态归并到当前状态序列；未知值回落到首态。"""
    status = _clean(value)
    status = LEGACY_STATUS_MAP.get(status, status)
    return status if status in STATUS_ORDER else STATUS_ORDER[0]


def owner_team(entry: dict[str, Any]) -> str:
    """计算票的归属队组（老票兼容既有的归属判定）。

    优先级：票上显式记录的归属 → 监护人当前备案队组 → 签发人当前备案队组 → 默认队组。
    """
    explicit = _clean(entry.get("归属队组"))
    if explicit:
        return explicit
    for field in ("监护人", "签发人"):
        person = resolve_person(entry.get(field))
        if person is not None:
            return person.team
    return TEAM_A


def serialize(entry: dict[str, Any]) -> dict[str, Any]:
    """列表与详情唯一的出参口径：状态、归属、监护人等两处完全一致。"""
    status = normalize_status(entry.get("status"))
    explicit_team = _clean(entry.get("归属队组"))
    if explicit_team:
        team = explicit_team
        team_source = "票内记录"
    else:
        fallback = resolve_person(entry.get("监护人")) or resolve_person(entry.get("签发人"))
        if fallback is not None:
            team = fallback.team
            team_source = "备案反查"
        else:
            team = TEAM_A
            team_source = "默认归属"

    result: dict[str, Any] = {
        "id": entry.get("id"),
        "归属队组": team,
        "归属来源": team_source,
        "措施状态": status,
        "status": status,
        "pending": status != STATUS_ORDER[-1],
        "abnormal": bool(entry.get("abnormal")),
    }
    for field in DISPLAY_FIELDS:
        if field in ("归属队组", "措施状态"):
            continue
        result[field] = _clean(entry.get(field))
    return result


class SafetyService:
    # ---- 查询 -----------------------------------------------------------------
    def list_entries(
        self,
        *,
        actor: Actor | None = None,
        keyword: str | None = None,
        status: str | None = None,
        team: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [serialize(row) for row in store.rows(MODULE)]
        if keyword:
            key = _clean(keyword)
            rows = [row for row in rows if key in str(row.get("措施编号", ""))]
        if status:
            wanted = normalize_status(status)
            rows = [row for row in rows if row["措施状态"] == wanted]
        if team:
            rows = [row for row in rows if row["归属队组"] == team]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int, *, actor: Actor | None = None) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return serialize(entry) if entry is not None else None

    # ---- 登记 -----------------------------------------------------------------
    def create_entry(self, values: dict[str, Any], *, actor: Actor) -> dict[str, Any]:
        # 只读账号与任何无登记授权的身份一律拒收
        self._require(actor, "safety:create")

        # 措施编号、措施类型、涉及设备缺一项不许保存
        missing = [field for field in REQUIRED_FIELDS if not _clean(values.get(field))]
        if missing:
            raise TicketError(
                f"措施编号、措施类型、涉及设备缺一项不许保存；当前缺少：{'、'.join(missing)}",
                missing=missing,
            )

        code = _clean(values.get("措施编号"))

        # 执行人与签发人互斥：登记时若两者都已指定，不允许为同一人
        self._ensure_issuer_executor_distinct(
            issuer_raw=values.get("签发人"), executor_raw=values.get("执行人")
        )

        rows = store.rows(MODULE)

        # 同一张票重复提交只留一条：按措施编号去重，已存在直接返回原票（幂等）
        for row in rows:
            if _clean(row.get("措施编号")) == code:
                return serialize(row)

        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "归属队组": actor.team,  # 归属按登记人最近一次备案
            "签发人": "",
            "执行人": "",
            "监护人": "",
            VALIDITY_FIELD: _clean(values.get(VALIDITY_FIELD)),
            "status": STATUS_ORDER[0],
            "abnormal": False,
        }
        for field in REQUIRED_FIELDS:
            entry[field] = _clean(values.get(field))
        # 允许登记时先指定执行人/监护人；监护人须属于本队组
        executor = self._resolve_member(values.get("执行人"), actor.team, "执行人")
        guardian = self._resolve_optional_member(values.get("监护人"), actor.team, "监护人")
        entry["执行人"] = executor
        entry["监护人"] = guardian
        rows.append(entry)
        return serialize(entry)

    # ---- 动作流转 -------------------------------------------------------------
    def run_action(self, entry_id: int, raw_action: str, *, actor: Actor) -> tuple[dict[str, Any], str]:
        action = _clean(raw_action)
        action = ACTION_ALIASES.get(action, action)

        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise TicketError(f"安全措施票 {entry_id} 不存在或已归档")

        if action not in ACTION_RULES:
            raise TicketError(f"动作「{raw_action}」不属于安全措施可执行范围")

        target, permission = ACTION_RULES[action]

        # 只读账号 / 无相应授权：先按授权拦截，并写清缺的授权项
        self._require(actor, permission)

        team = owner_team(entry)
        # 外队组点开只能查看、不能改动；越权操作一律拒收
        if actor.team != team:
            raise PermissionDenied(
                f"票 {entry.get('措施编号', entry_id)} 归属{team}，{actor.name}属{actor.team}，"
                f"外队组只能查看，不能{action}",
                required=[f"team:member:{team}"],
            )

        # 签发 / 终结仅本队监护人；执行仅本队执行人（角色不匹配同样列出所需授权）
        self._require_role_for_action(action, actor)

        current = normalize_status(entry.get("status"))
        current_index = STATUS_ORDER.index(current)
        target_index = STATUS_ORDER.index(target)

        # 同一张票重复提交只留一条结果：已处于目标态视为重复提交，幂等返回
        if current == target:
            return serialize(entry), f"安全措施票已是「{target}」，请勿重复提交"
        # 必须按顺序流转，禁止跳步
        if target_index != current_index + 1:
            raise TicketError(
                f"措施状态需按顺序流转：{' → '.join(STATUS_ORDER)}；"
                f"当前为「{current}」，不能直接{action}到「{target}」"
            )

        if action == "签发措施":
            # 签发人即操作的本队监护人；执行人与签发人互斥
            executor_name = _clean(entry.get("执行人"))
            self._ensure_names_distinct(actor.name, executor_name, "签发人", "执行人")
            entry["签发人"] = actor.name
            entry["监护人"] = actor.name
            todos.ensure_for_issue(serialize(entry), actor.name)
        elif action == "终结措施":
            # 终结仍由本队监护人完成
            entry["终结人"] = actor.name
            todos.mark_done_for_close(serialize(entry))
        elif action == "执行措施":
            entry["执行人"] = actor.name
            # 执行人不得同时是签发人（互斥规则在执行环节同样强制）
            self._ensure_names_distinct(actor.name, _clean(entry.get("签发人")), "执行人", "签发人")

        entry["status"] = target
        entry["abnormal"] = False
        return serialize(entry), f"安全措施票已{action}，状态：{target}"

    # ---- 导出 -----------------------------------------------------------------
    def export_entries(self, *, actor: Actor | None = None) -> list[dict[str, Any]]:
        """导出安全措施清单；按票 id 去重，重复数据只显示同一条。"""
        rows = store.rows(MODULE)
        unique: dict[int, dict[str, Any]] = {}
        for row in rows:
            serialized = serialize(row)
            unique.setdefault(int(serialized["id"]), serialized)
        return [unique[key] for key in sorted(unique)]

    # ---- 内部校验 -------------------------------------------------------------
    def _require(self, actor: Actor, permission: str) -> None:
        if not actor.can(permission):
            label = PERMISSIONS.get(permission, permission)
            raise PermissionDenied(
                f"{actor.role}{actor.name}缺少授权项「{label}」，该操作被拒收",
                required=[permission],
            )

    def _require_role_for_action(self, action: str, actor: Actor) -> None:
        if action in ("签发措施", "终结措施") and actor.role != "监护人":
            required = "safety:issue" if action == "签发措施" else "safety:close"
            raise PermissionDenied(
                f"仅本队组监护人可{action}，{actor.role}{actor.name}无权操作",
                required=[required],
            )
        if action == "执行措施" and actor.role == "只读账号":
            raise PermissionDenied(
                f"只读账号不能执行措施，{actor.name}的操作被拒收",
                required=["safety:execute"],
            )

    def _resolve_member(self, value: Any, team: str, label: str) -> str:
        name = _clean(value)
        if not name:
            return ""
        person = resolve_person(name)
        if person is None:
            raise TicketError(f"{label}「{name}」未在人员备案中登记")
        if person.team != team:
            raise PermissionDenied(
                f"{label}「{name}」属{person.team}，与票归属{team}不一致，不能挂到本票",
                required=[f"team:member:{team}"],
            )
        return person.name

    def _resolve_optional_member(self, value: Any, team: str, label: str) -> str:
        return self._resolve_member(value, team, label) if _clean(value) else ""

    def _ensure_issuer_executor_distinct(self, *, issuer_raw: Any, executor_raw: Any) -> None:
        issuer = resolve_person(issuer_raw)
        executor = resolve_person(executor_raw)
        if issuer and executor and issuer.id == executor.id:
            raise TicketError("执行人与签发人互斥，不能由同一人担任")

    def _ensure_names_distinct(
        self, name_a: str, name_b: str, label_a: str, label_b: str
    ) -> None:
        person_a = resolve_person(name_a)
        person_b = resolve_person(name_b)
        if name_a and name_b and ((person_a and person_b and person_a.id == person_b.id) or name_a == name_b):
            raise TicketError(f"{label_a}与{label_b}互斥，不能由同一人担任（{name_a}）")
