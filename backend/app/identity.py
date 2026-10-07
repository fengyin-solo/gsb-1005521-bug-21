"""归属判定与授权：队组备案、当前身份解析、越权拦截都收在这里。

归属判定口径（全系统唯一来源）：
- 每人可在多个队组备案，同一人存在多条备案时，按 ``filed_at`` 最近的一条认定其当前队组；
- 措施票新建时归属取经办人当前队组；老票没有「归属队组」字段时，
  按监护人的最近一次备案回填，保证历史数据沿用既有归属判定；
- 角色取自最近一次备案：监护人 / 执行人 / 只读，只读账号一律拒绝写操作。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Header

# 演示用备案台账：姓名 -> 历次备案（filed_at 越大越新）。
# 真实项目这里换成「人员-队组备案表」，多人多队组的取数口径保持不变。


@dataclass(frozen=True)
class Filing:
    """一次队组备案记录。"""

    name: str
    team: str
    role: str  # 监护人 / 执行人 / 只读
    filed_at: str  # ISO 日期，越大代表越近的备案


FILINGS: list[Filing] = [
    # 运维一队：监护人 + 执行人
    Filing("张护", "运维一队", "监护人", "2026-08-01"),
    Filing("李行", "运维一队", "执行人", "2026-08-02"),
    # 运维二队
    Filing("王护", "运维二队", "监护人", "2026-08-03"),
    Filing("赵行", "运维二队", "执行人", "2026-08-04"),
    # 只读账号
    Filing("周看", "运维一队", "只读", "2026-08-05"),
    # 一人同挂两个队组：先在运维二队备案，后改挂运维一队，归属按最近一次算
    Filing("陈兼", "运维二队", "执行人", "2026-07-10"),
    Filing("陈兼", "运维一队", "监护人", "2026-09-15"),
]

# 未显式带身份时默认的演示经办人（须在备案台账内）。
DEFAULT_OPERATOR = "张护"

GUARDIAN_ROLE = "监护人"
EXECUTOR_ROLE = "执行人"
READONLY_ROLE = "只读"


@dataclass(frozen=True)
class Identity:
    """经办人当前身份：姓名、按最近一次备案认定的队组与角色。"""

    name: str
    team: str
    role: str

    @property
    def writable(self) -> bool:
        """只读账号没有任何写权限。"""
        return self.role != READONLY_ROLE

    @property
    def is_guardian(self) -> bool:
        return self.role == GUARDIAN_ROLE

    @property
    def is_executor(self) -> bool:
        return self.role == EXECUTOR_ROLE

    def belongs_to(self, team: str | None) -> bool:
        return bool(team) and self.team == team


def latest_filing(name: str) -> Filing | None:
    """取某人最近一次备案；没有备案记录返回 None。"""
    filings = [filing for filing in FILINGS if filing.name == name]
    if not filings:
        return None
    return max(filings, key=lambda filing: filing.filed_at)


def resolve_identity(name: str | None) -> Identity | None:
    """按姓名解析当前身份；未登录或备案查不到时返回 None。"""
    filing = latest_filing(name or DEFAULT_OPERATOR)
    if filing is None:
        return None
    return Identity(name=filing.name, team=filing.team, role=filing.role)


def denied_detail(*, required: str, reason: str) -> dict[str, Any]:
    """统一构造越权返回：把「缺的授权项」与原因写清楚，便于前端直接提示。"""
    return {
        "code": "FORBIDDEN",
        "reason": reason,
        "required_permission": required,
        "operator_team": None,
        "entry_team": None,
    }


def current_identity(
    x_operator: str | None = Header(default=None, alias="X-Operator"),
    x_operator_id: str | None = Header(default=None, alias="X-Operator-Id"),
) -> Identity:
    """请求依赖：解析经办人身份；未备案人员一律拒收（401，先认人再谈授权）。

    HTTP 头只能走 Latin-1，前端对中文姓名用 ``encodeURIComponent`` 百分号编码后
    放在 ``X-Operator``；也可以传纯英文/数字的 ``X-Operator-Id``。
    """
    from fastapi import HTTPException
    from urllib.parse import unquote

    raw = x_operator_id or x_operator
    name = unquote(raw).strip() if raw else None
    identity = resolve_identity(name)
    if identity is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "UNREGISTERED_OPERATOR",
                "reason": f"经办人「{name or '未提供'}」未在队组备案台账中登记，禁止操作",
                "required_permission": "有效的队组备案身份",
            },
        )
    return identity
