"""登录与角色鉴权。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from db import connect, sha_password, write_audit

router = APIRouter(tags=["auth"])
SECRET = b"bondcage-dev-secret-not-for-prod"
AuthHeader = Annotated[str | None, Header(alias="Authorization")]


class LoginIn(BaseModel):
    username: str
    password: str


def _sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    sig = hmac.new(SECRET, body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _parse(token: str) -> dict:
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(401, "令牌无效") from exc
    expect = hmac.new(SECRET, body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        raise HTTPException(401, "令牌签名错误")
    data = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    if data.get("exp", 0) < time.time():
        raise HTTPException(401, "令牌已过期")
    return data


def require_user(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    data = _parse(authorization[7:].strip())
    return data["u"]


def role_of(authorization: str | None) -> tuple[str, str]:
    """返回 (username, role)，以库内角色为准（不信任令牌里的旧角色）。"""
    user = require_user(authorization)
    with connect() as conn:
        row = conn.execute(
            "SELECT role FROM users WHERE username=?", (user,)
        ).fetchone()
    if not row:
        raise HTTPException(401, "用户不存在")
    return user, row["role"]


def _audit_reject(user: str, role: str, action: str, payload: dict) -> None:
    """越权偏航独立落库：请求随即 403，痕迹不能被回滚吃掉。"""
    with connect() as conn:
        write_audit(conn, user, "越权偏航", action, {"role": role, **payload})
        conn.commit()


def require_writer(authorization: str | None) -> str:
    """非出金类写口：admin 与 clerk 可用，viewer 拒绝。"""
    user, role = role_of(authorization)
    if role not in ("admin", "clerk"):
        _audit_reject(user, role, "general_write", {})
        raise HTTPException(403, "只读账号禁止写入")
    return user


def require_withdrawal_writer(authorization: str | None, action: str) -> str:
    """出金类写口：仅 admin 可直接写；无出金写权角色零写入并记越权偏航。"""
    user, role = role_of(authorization)
    if role != "admin":
        _audit_reject(user, role, action, {})
        raise HTTPException(
            403, "无出金写权：出金写口禁止直接写入，请走审批影子单"
        )
    return user


def require_admin(authorization: str | None) -> str:
    user, role = role_of(authorization)
    if role != "admin":
        _audit_reject(user, role, "admin_only", {})
        raise HTTPException(403, "需要管理员")
    return user


@router.post("/api/login")
def login(body: LoginIn):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=?", (body.username,)
        ).fetchone()
        if not row or row["password_sha"] != sha_password(body.password):
            raise HTTPException(401, "用户名或密码错误")
        token = _sign({"u": row["username"], "r": row["role"], "exp": time.time() + 86400})
        write_audit(conn, row["username"], "login", row["username"], {"role": row["role"]})
        conn.commit()
        return {
            "token": token,
            "username": row["username"],
            "role": row["role"],
        }


@router.get("/api/me")
def me(authorization: AuthHeader = None):
    user = require_user(authorization)
    with connect() as conn:
        row = conn.execute(
            "SELECT username, role FROM users WHERE username=?", (user,)
        ).fetchone()
    if not row:
        raise HTTPException(401, "用户不存在")
    return dict(row)


@router.get("/api/dashboard")
def dashboard(authorization: AuthHeader = None):
    require_user(authorization)
    from db import dashboard_stats

    with connect() as conn:
        return dashboard_stats(conn)
