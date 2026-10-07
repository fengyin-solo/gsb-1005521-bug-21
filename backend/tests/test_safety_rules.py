"""安全措施票归属与权限回归测试。

纯标准库运行（不依赖 fastapi/pydantic），直接验证 services 层的业务规则：

    cd backend && python3 tests/test_safety_rules.py

覆盖：必填校验、归属判定、最近一次备案、外队组只读、只读账号拒收、
仅本队监护人签发/终结、顺序状态流转、签发人执行人互斥、重复提交幂等、
导出去重、签发结论落检修待办、老票兼容。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import todos  # noqa: E402
from app.services.identity import TEAM_A, TEAM_B, resolve_actor
from app.services.safety import PermissionDenied, SafetyService, TicketError
from app.store import store


def main() -> None:
    svc = SafetyService()
    zhou = resolve_actor("P101")   # 运维一队 监护人
    li = resolve_actor("P102")     # 运维一队 执行人
    chen = resolve_actor("P201")   # 运维二队 监护人
    zhao = resolve_actor("P202")   # 运维二队 执行人
    sun = resolve_actor("P301")    # 双备案，最近在二队 监护人
    wu = resolve_actor("P901")     # 一队 只读账号

    def must_raise(label: str, fn, exc_type) -> None:
        try:
            fn()
        except exc_type:
            return
        raise AssertionError(label)

    # 一人多岗：按最近一次备案归属二队
    assert sun.team == TEAM_B and sun.role == "监护人"

    # 老票：无归属字段，凭监护人陈监护反查到二队；旧状态“已解除”映射“已终结”
    old = svc.get_entry(5)
    assert old["归属队组"] == TEAM_B and old["措施状态"] == "已终结"

    # 列表与详情同口径：监护人、状态、归属一致
    listed, _ = svc.list_entries(keyword="SAFE-0002")
    detail = svc.get_entry(2)
    assert listed[0]["监护人"] == detail["监护人"] == "周检"
    assert listed[0]["措施状态"] == detail["措施状态"] == "已签发"

    # 必填：缺一项不许保存
    must_raise("缺涉及设备", lambda: svc.create_entry({"措施编号": "X", "措施类型": "Y"}, actor=zhou), TicketError)

    # 只读账号不能改动
    must_raise(
        "只读不能登记",
        lambda: svc.create_entry({"措施编号": "X", "措施类型": "Y", "涉及设备": "Z"}, actor=wu),
        PermissionDenied,
    )
    must_raise("只读不能签发", lambda: svc.run_action(1, "签发措施", actor=wu), PermissionDenied)

    # 执行人不能签发
    must_raise("执行人不能签发", lambda: svc.run_action(1, "签发措施", actor=li), PermissionDenied)

    # 外队组越权拒收
    must_raise("外队监护人不能签一队票", lambda: svc.run_action(1, "签发措施", actor=chen), PermissionDenied)
    must_raise("外队执行人不能动一队票", lambda: svc.run_action(1, "执行措施", actor=zhao), PermissionDenied)
    must_raise("双备案者按二队算不能动一队票", lambda: svc.run_action(1, "签发措施", actor=sun), PermissionDenied)

    # 登记幂等：同一措施编号重复提交只留一条
    first = svc.create_entry(
        {"措施编号": "SAFE-TEST", "措施类型": "停电", "涉及设备": "3号逆变器", "执行人": "王执行"},
        actor=li,
    )
    second = svc.create_entry(
        {"措施编号": "SAFE-TEST", "措施类型": "停电", "涉及设备": "3号逆变器", "执行人": "王执行"},
        actor=li,
    )
    tid = int(first["id"])
    assert second["id"] == first["id"]
    assert sum(1 for row in store.rows("safety") if row.get("措施编号") == "SAFE-TEST") == 1

    # 签发人/执行人互斥
    store.find("safety", tid)["执行人"] = "周检"
    must_raise("签发人=执行人互斥", lambda: svc.run_action(tid, "签发措施", actor=zhou), TicketError)
    store.find("safety", tid)["执行人"] = "李安全"

    # 顺序流转：一队票由本队监护人签发 → 本队执行人执行 → 本队监护人终结
    issued, _ = svc.run_action(tid, "签发措施", actor=zhou)
    assert issued["措施状态"] == "已签发" and issued["签发人"] == "周检"
    # 重复签发幂等，不重复落待办
    _, repeat_msg = svc.run_action(tid, "签发措施", actor=zhou)
    assert "重复提交" in repeat_msg
    open_todos = todos.list_todos(keyword="SAFE-TEST", only_open=True)
    assert len(open_todos) == 1 and open_todos[0]["归属队组"] == TEAM_A

    executed, _ = svc.run_action(tid, "执行措施", actor=li)
    assert executed["措施状态"] == "已执行" and executed["执行人"] == "李安全"

    # 执行人不能终结，监护人才行
    must_raise("执行人不能终结", lambda: svc.run_action(tid, "终结措施", actor=li), PermissionDenied)
    closed, _ = svc.run_action(tid, "终结措施", actor=zhou)
    assert closed["措施状态"] == "已终结" and closed["pending"] is False
    assert todos.list_todos(keyword="SAFE-TEST", only_open=True) == []

    # 跳步拒绝：二队待签发票不能直接执行
    must_raise("跳步拒绝", lambda: svc.run_action(4, "执行措施", actor=zhao), TicketError)
    # 二队全流程
    svc.run_action(4, "签发措施", actor=chen)
    svc.run_action(4, "执行措施", actor=zhao)
    svc.run_action(4, "终结措施", actor=chen)
    assert svc.get_entry(4)["措施状态"] == "已终结"

    # 导出按 id 去重
    items = svc.export_entries()
    ids = [int(item["id"]) for item in items]
    assert len(ids) == len(set(ids))

    print("全部安全措施归属/权限回归用例通过 ✅  导出票数 =", len(items))


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print("用例失败：", exc or "断言不成立")
        sys.exit(1)
