"""罚没：核验违约后将笼内可用额写入罚没册。

越权写闸（2026-11-22 纪要）：同解笼拨付——直接写口仅 admin；无出金写权
角色零写入并记越权偏航；影子审批单批准后由 `apply_forfeit` 代写。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_withdrawal_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import ForfeitIn

router = APIRouter(tags=["forfeit"])


def apply_forfeit(conn, actor: str, cage_id: int, amount=None, reason=None) -> dict:
    """正式罚没代写（调用方负责锁与事务）。校验失败抛 HTTPException，调用方回滚。"""
    cage = conn.execute("SELECT * FROM cages WHERE id=?", (cage_id,)).fetchone()
    if not cage:
        raise HTTPException(404, "笼不存在")
    if cage["status"] != "核验违约":
        raise HTTPException(409, "仅核验违约的笼可罚没")
    att = conn.execute(
        """SELECT * FROM attestations
           WHERE cage_id=? AND attest_gen=? AND outcome='违约'
           ORDER BY id DESC LIMIT 1""",
        (cage_id, int(cage["generation"])),
    ).fetchone()
    if not att:
        raise HTTPException(409, "缺少与笼代对齐的违约核验")
    avail = float(cage["available"])
    amt = float(amount) if amount is not None else avail
    if amt <= 0:
        raise HTTPException(400, "罚没金额须大于 0")
    if amt > avail + 1e-9:
        raise HTTPException(409, "罚没金额超过笼可用额")
    now = now_iso()
    gen = int(cage["generation"])
    ref = f"FOR-{cage['cage_code']}-g{gen}"
    cur = conn.execute(
        """INSERT INTO forfeits(cage_id,amount,reason,cage_generation,status,forfeit_ref,created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (cage_id, amt, reason or "履约违约", gen, "已罚没", ref, now),
    )
    new_avail = round(avail - amt, 6)
    new_status = "已罚没" if new_avail <= 1e-9 else "部分罚没"
    conn.execute(
        "UPDATE cages SET available=?, status=? WHERE id=?",
        (max(new_avail, 0.0), new_status, cage_id),
    )
    conn.execute(
        """UPDATE bond_accounts
           SET frozen = frozen - ?, balance = balance - ?
           WHERE party_key=?""",
        (amt, amt, cage["party_key"]),
    )
    write_audit(
        conn,
        actor,
        "cage_forfeit",
        cage["cage_code"],
        {
            "forfeit_id": cur.lastrowid,
            "amount": amt,
            "reason": reason,
            "cage_generation": gen,
            "forfeit_ref": ref,
        },
    )
    return dict(
        conn.execute("SELECT * FROM forfeits WHERE id=?", (cur.lastrowid,)).fetchone()
    )


@router.get("/api/forfeits")
def list_forfeits(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT f.*, c.cage_code, c.contract_no
               FROM forfeits f
               JOIN cages c ON c.id=f.cage_id
               ORDER BY f.id DESC LIMIT 200"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/forfeits")
def do_forfeit(body: ForfeitIn, authorization: AuthHeader = None):
    user = require_withdrawal_writer(authorization, "cage_forfeit")
    lock_key = f"cage:{body.cage_id}"
    with connect() as conn:
        try:
            require_lock(conn, lock_key, user)
            row = apply_forfeit(conn, user, body.cage_id, body.amount, body.reason)
            conn.commit()
            return row
        except Exception:
            conn.rollback()
            raise
        finally:
            release(conn, lock_key, user)
            conn.commit()
