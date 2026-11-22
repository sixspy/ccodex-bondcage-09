"""审批影子单：无出金写权角色只建影子，管理员批准后服务端代写。

越权写闸（2026-11-22 纪要）乙路径：
- 申请（viewer/clerk/admin 均可发）：只写 approval_requests，业务表零改。
- 批准（仅 admin）：在同一事务内调用 release/forfeit 的正式代写，成功才把
  影子单置「已批准」并回填 resulting_ref。
- 驳回（仅 admin）：影子单置「已驳回」，正式表零改。
- 影子单从不直接改写 releases/forfeits；正式册只由代写写入。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_admin, require_user
from db import connect, now_iso, write_audit
from locks import release as unlock, require_lock
from models import ApprovalDecisionIn, ApprovalRequestIn
from forfeit_svc import apply_forfeit
from release_svc import apply_release

router = APIRouter(tags=["approvals"])

KIND_LABEL = {"release": "解笼拨付", "forfeit": "罚没"}
_APPLY = {"release": apply_release, "forfeit": apply_forfeit}


@router.get("/api/approvals")
def list_approvals(authorization: AuthHeader = None, status: str | None = None):
    require_user(authorization)
    with connect() as conn:
        if status:
            rows = conn.execute(
                """SELECT a.*, c.cage_code, c.contract_no, c.party_key,
                          c.available, c.status AS cage_status
                   FROM approval_requests a JOIN cages c ON c.id=a.cage_id
                   WHERE a.status=? ORDER BY a.id DESC LIMIT 200""",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT a.*, c.cage_code, c.contract_no, c.party_key,
                          c.available, c.status AS cage_status
                   FROM approval_requests a JOIN cages c ON c.id=a.cage_id
                   ORDER BY a.id DESC LIMIT 200"""
            ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/approvals")
def create_approval(body: ApprovalRequestIn, authorization: AuthHeader = None):
    """建影子单：不碰正式册、不改笼、不改账户。"""
    user = require_user(authorization)
    with connect() as conn:
        role = conn.execute(
            "SELECT role FROM users WHERE username=?", (user,)
        ).fetchone()["role"]
        cage = conn.execute(
            "SELECT * FROM cages WHERE id=?", (body.cage_id,)
        ).fetchone()
        if not cage:
            raise HTTPException(404, "笼不存在")
        amount = float(body.amount) if body.amount is not None else None
        if amount is not None and amount <= 0:
            raise HTTPException(400, "金额须大于 0")
        now = now_iso()
        cur = conn.execute(
            """INSERT INTO approval_requests
               (kind,cage_id,amount,payee,reason,note,status,requested_by,
                requested_role,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                body.kind,
                body.cage_id,
                amount,
                body.payee,
                body.reason,
                body.note,
                "待审批",
                user,
                role,
                now,
            ),
        )
        write_audit(
            conn,
            user,
            "审批申请",
            cage["cage_code"],
            {
                "approval_id": cur.lastrowid,
                "kind": body.kind,
                "amount": amount,
                "requested_role": role,
            },
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM approval_requests WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


@router.post("/api/approvals/{approval_id}/decide")
def decide_approval(
    approval_id: int, body: ApprovalDecisionIn, authorization: AuthHeader = None
):
    user = require_admin(authorization)
    with connect() as conn:
        req = conn.execute(
            "SELECT * FROM approval_requests WHERE id=?", (approval_id,)
        ).fetchone()
        if not req:
            raise HTTPException(404, "审批单不存在")
        if req["status"] != "待审批":
            raise HTTPException(409, "该审批单已处理")
        cage = conn.execute(
            "SELECT * FROM cages WHERE id=?", (req["cage_id"],)
        ).fetchone()
        if not cage:
            raise HTTPException(404, "笼不存在")
        now = now_iso()

        if body.decision == "reject":
            conn.execute(
                """UPDATE approval_requests
                   SET status='已驳回', decided_by=?, decided_at=?, decision_note=?
                   WHERE id=?""",
                (user, now, body.note, approval_id),
            )
            write_audit(
                conn,
                user,
                "审批驳回",
                cage["cage_code"],
                {"approval_id": approval_id, "kind": req["kind"]},
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM approval_requests WHERE id=?", (approval_id,)
            ).fetchone()
            return dict(row)

        # 批准：服务端代写正式拨付/罚没，成功才晋升影子单
        lock_key = f"cage:{req['cage_id']}"
        try:
            require_lock(conn, lock_key, user)
            if req["kind"] == "release":
                written = apply_release(
                    conn, user, req["cage_id"], req["amount"], req["payee"]
                )
                resulting_ref = written["release_ref"]
            elif req["kind"] == "forfeit":
                written = apply_forfeit(
                    conn, user, req["cage_id"], req["amount"], req["reason"]
                )
                resulting_ref = written["forfeit_ref"]
            else:  # pragma: no cover - kind 受 CHECK 约束
                raise HTTPException(400, "未知审批类型")
            conn.execute(
                """UPDATE approval_requests
                   SET status='已批准', decided_by=?, decided_at=?, decision_note=?,
                       resulting_ref=?
                   WHERE id=?""",
                (user, now, body.note, resulting_ref, approval_id),
            )
            write_audit(
                conn,
                user,
                "审批通过",
                cage["cage_code"],
                {
                    "approval_id": approval_id,
                    "kind": req["kind"],
                    "resulting_ref": resulting_ref,
                },
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            unlock(conn, lock_key, user)
            conn.commit()
        row = conn.execute(
            "SELECT * FROM approval_requests WHERE id=?", (approval_id,)
        ).fetchone()
        return dict(row)
