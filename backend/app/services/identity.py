"""人员备案与归属判定。

安全措施票的签发、执行、终结权限都要先判定“这个人现在属于哪个队组、是什么角色”。

- 一个人可能在多个队组留过备案（一人同挂两个队组），**以最近一次备案为准**；
- 角色分监护人 / 执行人 / 只读账号，角色决定能用哪些授权项；
- 老票里可能只写了人名，需要凭人名反查其当前备案队组（见 :func:`team_of_person`）。

备案数据集中在本文件维护，业务服务只调用这里的判定函数，不自行解读人名。
"""
from __future__ import annotations

from typing import Any, TypedDict

# 队组
TEAM_A = "运维一队"
TEAM_B = "运维二队"
TEAMS = [TEAM_A, TEAM_B]

# 角色
ROLE_GUARDIAN = "监护人"
ROLE_EXECUTOR = "执行人"
ROLE_VIEWER = "只读账号"
ROLES = [ROLE_GUARDIAN, ROLE_EXECUTOR, ROLE_VIEWER]

# 授权项：key 供程序判定，label 用于把“缺的授权项”写清楚
PERMISSIONS: dict[str, str] = {
    "safety:view": "查看安全措施票",
    "safety:create": "登记安全措施票",
    "safety:issue": "签发安全措施票",
    "safety:execute": "执行安全措施票",
    "safety:close": "终结安全措施票",
    "team:member": "归属本队组",
}

# 各角色拥有的授权项；只读账号不含任何可改动的授权
ROLE_PERMISSIONS: dict[str, list[str]] = {
    ROLE_GUARDIAN: ["safety:view", "safety:create", "safety:issue", "safety:execute", "safety:close"],
    ROLE_EXECUTOR: ["safety:view", "safety:create", "safety:execute"],
    ROLE_VIEWER: ["safety:view"],
}


class Filing(TypedDict):
    """一次人员备案记录。filed_at 为备案时间（ISO 字符串，可直接按字符串比较新旧）。"""

    id: str
    name: str
    team: str
    role: str
    filed_at: str


# 备案流水：同一人出现多次即“一人同挂两个队组”，按 filed_at 取最近一条。
FILINGS: list[Filing] = [
    # 运维一队
    {"id": "P101", "name": "周检", "team": TEAM_A, "role": ROLE_GUARDIAN, "filed_at": "2026-08-01T09:00:00"},
    {"id": "P102", "name": "李安全", "team": TEAM_A, "role": ROLE_EXECUTOR, "filed_at": "2026-08-02T09:00:00"},
    {"id": "P103", "name": "王执行", "team": TEAM_A, "role": ROLE_EXECUTOR, "filed_at": "2026-08-03T09:00:00"},
    # 运维二队
    {"id": "P201", "name": "陈监护", "team": TEAM_B, "role": ROLE_GUARDIAN, "filed_at": "2026-08-01T09:00:00"},
    {"id": "P202", "name": "赵动手", "team": TEAM_B, "role": ROLE_EXECUTOR, "filed_at": "2026-08-02T09:00:00"},
    # 一人同挂两队：较早备案在一队，最近一次备案在二队 → 当前归属二队
    {"id": "P301", "name": "孙双岗", "team": TEAM_A, "role": ROLE_EXECUTOR, "filed_at": "2026-07-10T09:00:00"},
    {"id": "P301", "name": "孙双岗", "team": TEAM_B, "role": ROLE_GUARDIAN, "filed_at": "2026-09-20T09:00:00"},
    # 只读账号：只能看，任何改动授权都没有
    {"id": "P901", "name": "吴旁观", "team": TEAM_A, "role": ROLE_VIEWER, "filed_at": "2026-08-05T09:00:00"},
]

_BY_ID: dict[str, Filing] = {}
_BY_NAME: dict[str, Filing] = {}
for _filing in FILINGS:
    _id_key = _filing["id"]
    if _id_key not in _BY_ID or _filing["filed_at"] > _BY_ID[_id_key]["filed_at"]:
        _BY_ID[_id_key] = _filing
    _name_key = _filing["name"]
    if _name_key not in _BY_NAME or _filing["filed_at"] > _BY_NAME[_name_key]["filed_at"]:
        _BY_NAME[_name_key] = _filing


class IdentityError(Exception):
    """无法识别操作人身份。"""


class Actor:
    """当前操作人：解析自最近一次备案。"""

    def __init__(self, filing: Filing) -> None:
        self.id: str = filing["id"]
        self.name: str = filing["name"]
        self.team: str = filing["team"]
        self.role: str = filing["role"]

    @property
    def permissions(self) -> list[str]:
        return ROLE_PERMISSIONS.get(self.role, [])

    @property
    def readonly(self) -> bool:
        return self.role == ROLE_VIEWER

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def missing(self, permissions: list[str]) -> list[str]:
        return [perm for perm in permissions if perm not in self.permissions]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "team": self.team,
            "role": self.role,
            "permissions": self.permissions,
            "permissionLabels": [PERMISSIONS[perm] for perm in self.permissions if perm in PERMISSIONS],
            "readonly": self.readonly,
        }


def resolve_actor(value: str | None) -> Actor:
    """按工号（优先）或姓名解析当前操作人；识别不了直接拒绝。"""
    key = str(value or "").strip()
    if not key:
        raise IdentityError("缺少操作人身份（请求头 X-Operator-Id），无法判定归属与授权")
    filing = _BY_ID.get(key) or _BY_NAME.get(key)
    if filing is None:
        raise IdentityError(f"操作人「{key}」未在人员备案中登记，无法判定所属队组与角色")
    return Actor(filing)


def roster() -> list[dict[str, Any]]:
    """返回当前生效的人员花名册（同一人只保留最近一次备案）。"""
    actors: dict[str, dict[str, Any]] = {}
    for filing in FILINGS:
        actor = Actor(filing).as_dict()
        # FILINGS 按时间顺序书写，后写的覆盖先写的，天然得到“最近一次备案”
        actors[filing["id"]] = actor
    return [actors[key] for key in sorted(actors)]


def find_by_name(name: str | None) -> Actor | None:
    """凭人名反查当前备案；查不到返回 None（供老票归属兜底）。"""
    filing = _BY_NAME.get(str(name or "").strip())
    return Actor(filing) if filing else None


def find_by_id(person_id: str | None) -> Actor | None:
    filing = _BY_ID.get(str(person_id or "").strip())
    return Actor(filing) if filing else None


def resolve_person(value: str | None) -> Actor | None:
    """人名或工号都能解析，识别不了返回 None。"""
    key = str(value or "").strip()
    if not key:
        return None
    filing = _BY_ID.get(key) or _BY_NAME.get(key)
    return Actor(filing) if filing else None


def permission_labels(permissions: list[str]) -> list[str]:
    return [PERMISSIONS[perm] for perm in permissions if perm in PERMISSIONS]
