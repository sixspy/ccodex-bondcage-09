"""解笼拨付：核验通过后把笼内可用额拨付给受益人。

越权写闸（2026-11-22 纪要）：
- 直接写口仅 admin 可调；无出金写权角色在鉴权层被拒，业务表零增。
- 无写权角色只能建审批影子单，管理员批准后由本模块 `apply_release` 代写。
- 失败即回滚，不落半成品。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_withdrawal_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import ReleaseIn

router = APIRouter(tags=["release"])


def apply_release(conn, actor: str, cage_id: int, amount=None, payee=None) -> dict:
    """正式拨付代写（调用方负责锁与事务）。校验失败抛 HTTPException，调用方回滚。"""
    cage = conn.execute("SELECT * FROM cages WHERE id=?", (cage_id,)).fetchone()
    if not cage:
        raise HTTPException(404, "笼不存在")
    if cage["status"] != "核验通过":
        raise HTTPException(409, "仅核验通过的笼可解笼拨付")
    # 核验结论必须对齐当前笼代
    att = conn.execute(
        """SELECT * FROM attestations
           WHERE cage_id=? AND attest_gen=? AND outcome='通过'
           ORDER BY id DESC LIMIT 1""",
        (cage_id, int(cage["generation"])),
    ).fetchone()
    if not att:
        raise HTTPException(409, "缺少与笼代对齐的通过核验")
    avail = float(cage["available"])
    amt = float(amount) if amount is not None else avail
    if amt <= 0:
        raise HTTPException(400, "拨付金额须大于 0")
    if amt > avail + 1e-9:
        raise HTTPException(409, "拨付金额超过笼可用额")
    target_payee = payee or cage["beneficiary"]
    now = now_iso()
    gen = int(cage["generation"])
    ref = f"REL-{cage['cage_code']}-g{gen}-{int(now.replace(':', '').replace('-', '').replace('T', '')[-8:])}"
    cur = conn.execute(
        """INSERT INTO releases(cage_id,amount,payee,cage_generation,status,release_ref,created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (cage_id, amt, target_payee, gen, "已拨付", ref, now),
    )
    new_avail = round(avail - amt, 6)
    new_status = "已解笼" if new_avail <= 1e-9 else "部分解笼"
    conn.execute(
        "UPDATE cages SET available=?, status=? WHERE id=?",
        (max(new_avail, 0.0), new_status, cage_id),
    )
    # 账户：冻结减少，余额减少（资金离开系统）
    conn.execute(
        """UPDATE bond_accounts
           SET frozen = frozen - ?, balance = balance - ?
           WHERE party_key=?""",
        (amt, amt, cage["party_key"]),
    )
    write_audit(
        conn,
        actor,
        "cage_release",
        cage["cage_code"],
        {
            "release_id": cur.lastrowid,
            "amount": amt,
            "payee": target_payee,
            "cage_generation": gen,
            "release_ref": ref,
        },
    )
    return dict(
        conn.execute("SELECT * FROM releases WHERE id=?", (cur.lastrowid,)).fetchone()
    )


@router.get("/api/releases")
def list_releases(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT r.*, c.cage_code, c.contract_no
               FROM releases r
               JOIN cages c ON c.id=r.cage_id
               ORDER BY r.id DESC LIMIT 200"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/releases")
def do_release(body: ReleaseIn, authorization: AuthHeader = None):
    user = require_withdrawal_writer(authorization, "cage_release")
    lock_key = f"cage:{body.cage_id}"
    with connect() as conn:
        try:
            require_lock(conn, lock_key, user)
            row = apply_release(conn, user, body.cage_id, body.amount, body.payee)
            conn.commit()
            return row
        except Exception:
            conn.rollback()
            raise
        finally:
            release(conn, lock_key, user)
            conn.commit()
