"""越权写出金闸：先见红的两条失败测。

顺序（必须遵守）：
1. 无出金写权柜员（clerk）打解笼/罚没写口 -> 必须 403 且业务表零增，只落
   「越权偏航」审计。
2. 两个写角色同笼争用 -> 后到者 409，只留争用痕，业务表零增。

本文件只跑本机文件库（tmp_path 下的 .db 文件，非 :memory:）。
"""
import pytest
from fastapi.testclient import TestClient

import db
from app import app


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t.db")
    init_db = getattr(db, "init_db")
    init_db()
    yield


def _login(c: TestClient, user: str) -> dict:
    r = c.post("/api/login", json={"username": user, "password": "123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _add_writer(user: str, role: str = "admin") -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(username,password_sha,role) VALUES (?,?,?)",
            (user, db.sha_password("123456"), role),
        )
        conn.commit()


def _make_cage(
    c: TestClient,
    headers: dict,
    *,
    party: str = "P-OVR",
    code: str = "CG-OVR-001",
    outcome: str = "通过",
    amount: float = 10000,
) -> dict:
    r = c.post(
        "/api/bonds",
        headers=headers,
        json={
            "party_key": party,
            "party_name": "越权测试方",
            "initial_deposit": amount * 2,
        },
    )
    assert r.status_code == 200, r.text
    r = c.post(
        "/api/cages/freeze",
        headers=headers,
        json={
            "party_key": party,
            "contract_no": f"HT-{party}",
            "amount": amount,
            "beneficiary": "越权测试受益人",
            "cage_code": code,
        },
    )
    assert r.status_code == 200, r.text
    cage = r.json()
    r = c.post(
        "/api/attestations",
        headers=headers,
        json={"cage_id": cage["id"], "outcome": outcome, "evidence": "预置结论"},
    )
    assert r.status_code == 200, r.text
    return cage


def _business_snap(cage_id: int, party: str) -> dict:
    """只取业务表（拨付册/罚没册/笼/账户）——审计不在此列。"""
    with db.connect() as conn:
        return {
            "releases": conn.execute(
                "SELECT COUNT(*) c FROM releases WHERE cage_id=?", (cage_id,)
            ).fetchone()["c"],
            "forfeits": conn.execute(
                "SELECT COUNT(*) c FROM forfeits WHERE cage_id=?", (cage_id,)
            ).fetchone()["c"],
            "cage_available": conn.execute(
                "SELECT available FROM cages WHERE id=?", (cage_id,)
            ).fetchone()["available"],
            "cage_status": conn.execute(
                "SELECT status FROM cages WHERE id=?", (cage_id,)
            ).fetchone()["status"],
            "account_balance": conn.execute(
                "SELECT balance FROM bond_accounts WHERE party_key=?", (party,)
            ).fetchone()["balance"],
            "account_frozen": conn.execute(
                "SELECT frozen FROM bond_accounts WHERE party_key=?", (party,)
            ).fetchone()["frozen"],
        }


def _audit_count(actor: str, action: str) -> int:
    with db.connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) c FROM audit_trail WHERE actor=? AND action=?",
            (actor, action),
        ).fetchone()["c"]


def test_no_write_role_release_rejected_zero_write():
    """红：当前 clerk 能落正式拨付；绿：403 + 业务零增 + 仅越权偏航。"""
    c = TestClient(app)
    admin = _login(c, "admin")
    clerk = _login(c, "clerk")
    cage = _make_cage(c, admin)
    before = _business_snap(cage["id"], "P-OVR")

    r = c.post("/api/releases", headers=clerk, json={"cage_id": cage["id"]})

    assert r.status_code == 403, r.text
    assert _business_snap(cage["id"], "P-OVR") == before
    assert _audit_count("clerk", "cage_release") == 0
    assert _audit_count("clerk", "越权偏航") >= 1


def test_no_write_role_forfeit_rejected_zero_write():
    """红：当前 clerk 能落正式罚没；绿：403 + 业务零增 + 仅越权偏航。"""
    c = TestClient(app)
    admin = _login(c, "admin")
    clerk = _login(c, "clerk")
    cage = _make_cage(
        c, admin, party="P-OVR-F", code="CG-OVR-F-001", outcome="违约"
    )
    before = _business_snap(cage["id"], "P-OVR-F")

    r = c.post("/api/forfeits", headers=clerk, json={"cage_id": cage["id"]})

    assert r.status_code == 403, r.text
    assert _business_snap(cage["id"], "P-OVR-F") == before
    assert _audit_count("clerk", "cage_forfeit") == 0
    assert _audit_count("clerk", "越权偏航") >= 1


def test_two_writers_same_cage_contention_only_trace():
    """红：争用痕被事务回滚；绿：后到 409、争用痕落库、业务零增。"""
    c = TestClient(app)
    writer1 = _login(c, "admin")
    _add_writer("admin2", role="admin")
    writer2 = _login(c, "admin2")
    cage = _make_cage(
        c, writer1, party="P-CONT", code="CG-CONT-001"
    )
    lock_key = f"cage:{cage['id']}"

    held = c.post("/api/locks/acquire", headers=writer1, json={"lock_key": lock_key})
    assert held.status_code == 200, held.text
    before = _business_snap(cage["id"], "P-CONT")

    r = c.post("/api/releases", headers=writer2, json={"cage_id": cage["id"]})

    assert r.status_code == 409, r.text
    assert _business_snap(cage["id"], "P-CONT") == before
    cont = c.get("/api/contention", headers=writer1).json()["items"]
    assert any(
        x["lock_key"] == lock_key and x["actor"] == "admin2" for x in cont
    ), cont


def test_clerk_shadow_approved_by_admin_writes_once():
    """clerk 只建影子；管理员批准后由服务端代写一次正式拨付。"""
    c = TestClient(app)
    admin = _login(c, "admin")
    clerk = _login(c, "clerk")
    cage = _make_cage(
        c, admin, party="P-APR", code="CG-APR-001", amount=8000
    )
    before = _business_snap(cage["id"], "P-APR")

    shadow = c.post(
        "/api/approvals",
        headers=clerk,
        json={"kind": "release", "cage_id": cage["id"], "amount": 3000, "payee": "代收方"},
    )
    assert shadow.status_code == 200, shadow.text
    assert shadow.json()["status"] == "待审批"
    # 建影子时业务表纹丝不动
    assert _business_snap(cage["id"], "P-APR") == before
    assert _audit_count("clerk", "cage_release") == 0

    # clerk 不能自行批准
    assert (
        c.post(
            f"/api/approvals/{shadow.json()['id']}/decide",
            headers=clerk,
            json={"decision": "approve"},
        ).status_code
        == 403
    )
    assert _business_snap(cage["id"], "P-APR") == before

    # 管理员批准 -> 正式代写一次
    ok = c.post(
        f"/api/approvals/{shadow.json()['id']}/decide",
        headers=admin,
        json={"decision": "approve", "note": "同意"},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "已批准"
    assert body["decided_by"] == "admin"
    assert body["resulting_ref"].startswith("REL-")
    after = _business_snap(cage["id"], "P-APR")
    assert after["releases"] == before["releases"] + 1
    assert after["cage_available"] == before["cage_available"] - 3000
    assert after["account_balance"] == before["account_balance"] - 3000
    # 只代写一次：重复批准被拒
    assert (
        c.post(
            f"/api/approvals/{shadow.json()['id']}/decide",
            headers=admin,
            json={"decision": "approve"},
        ).status_code
        == 409
    )


def test_clerk_shadow_rejected_leaves_business_untouched():
    """管理员驳回：影子作废，正式罚没册零改。"""
    c = TestClient(app)
    admin = _login(c, "admin")
    clerk = _login(c, "clerk")
    cage = _make_cage(
        c, admin, party="P-REJ", code="CG-REJ-001", outcome="违约", amount=6000
    )
    before = _business_snap(cage["id"], "P-REJ")
    shadow = c.post(
        "/api/approvals",
        headers=clerk,
        json={"kind": "forfeit", "cage_id": cage["id"], "amount": 6000},
    )
    assert shadow.status_code == 200, shadow.text

    rej = c.post(
        f"/api/approvals/{shadow.json()['id']}/decide",
        headers=admin,
        json={"decision": "reject", "note": "证据不足"},
    )
    assert rej.status_code == 200, rej.text
    assert rej.json()["status"] == "已驳回"
    assert rej.json()["resulting_ref"] is None
    assert _business_snap(cage["id"], "P-REJ") == before
    assert _audit_count("admin", "cage_forfeit") == 0


def test_withdrawal_attempt_by_no_write_role_logs_drift_only():
    """越权尝试只留『越权偏航』，不留正式写痕，也不写业务。"""
    c = TestClient(app)
    admin = _login(c, "admin")
    clerk = _login(c, "clerk")
    viewer = _login(c, "viewer")
    cage = _make_cage(c, admin, party="P-DRIFT", code="CG-DRIFT-001")
    before = _business_snap(cage["id"], "P-DRIFT")

    for headers in (clerk, viewer):
        assert (
            c.post("/api/releases", headers=headers, json={"cage_id": cage["id"]}).status_code
            == 403
        )
    assert _business_snap(cage["id"], "P-DRIFT") == before
    assert _audit_count("clerk", "cage_release") == 0
    assert _audit_count("viewer", "cage_release") == 0
    assert _audit_count("clerk", "越权偏航") >= 1
    assert _audit_count("viewer", "越权偏航") >= 1


def test_drift_memo_present_and_locked_today():
    """越权写闸纪要须存在，且锁死日期为 2026-11-22。"""
    from pathlib import Path

    memo = Path(__file__).resolve().parents[1] / "ops" / "越权写闸纪要.md"
    assert memo.is_file()
    text = memo.read_text(encoding="utf-8")
    assert "2026-11-22" in text
    assert "乙路径" in text
