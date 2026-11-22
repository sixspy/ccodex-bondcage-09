#!/usr/bin/env python3
"""越权出金复现夹具（甲路径取证用）。

本夹具故意用「无出金写权」的 clerk 令牌去打解笼写口，验证当前代码是否
会真实落一条正式拨付。它跑在本机文件库的副本上，不碰 data/app.db 原件。

用法：
    python scripts/repro_unauthorized_release.py
    python scripts/repro_unauthorized_release.py --db /path/to/copy.db

退出码：
    0  复现/拒绝结果与 --expect 一致（默认 auto：任一结果都打印）
    1  与 --expect 不一致
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default=None,
        help="本机文件库路径；缺省复制 data/app.db 到临时目录后跑，不污染原件",
    )
    parser.add_argument(
        "--expect",
        choices=("exploit", "denied", "auto"),
        default="auto",
        help="exploit=期望越权成功(修复前假绿)；denied=期望鉴权门闸拒绝(修复后)",
    )
    args = parser.parse_args()

    tmpdir: tempfile.TemporaryDirectory | None = None
    if args.db:
        db_path = Path(args.db).resolve()
    else:
        tmpdir = tempfile.TemporaryDirectory(prefix="bondcage-repro-")
        db_path = Path(tmpdir.name) / "app.db"
        shutil.copy2(ROOT / "data" / "app.db", db_path)

    import db

    db.DB_PATH = db_path
    db.init_db()

    from fastapi.testclient import TestClient

    from app import app

    client = TestClient(app)

    def login(username: str) -> dict:
        r = client.post(
            "/api/login", json={"username": username, "password": "123456"}
        )
        r.raise_for_status()
        return {"Authorization": "Bearer " + r.json()["token"]}

    admin = login("admin")
    clerk = login("clerk")

    party = "P-REPRO-OVERREACH"
    cage_code = "CG-REPRO-OVERREACH-001"
    client.post(
        "/api/bonds",
        headers=admin,
        json={"party_key": party, "party_name": "越权复现方", "initial_deposit": 20000},
    )
    cage = client.post(
        "/api/cages/freeze",
        headers=admin,
        json={
            "party_key": party,
            "contract_no": "HT-REPRO-OVERREACH",
            "amount": 10000,
            "beneficiary": "复现受益人",
            "cage_code": cage_code,
        },
    ).json()
    client.post(
        "/api/attestations",
        headers=admin,
        json={"cage_id": cage["id"], "outcome": "通过", "evidence": "复现预置"},
    )

    def snap() -> dict:
        with db.connect() as conn:
            return {
                "releases": conn.execute(
                    "SELECT COUNT(*) c FROM releases WHERE cage_id=?", (cage["id"],)
                ).fetchone()["c"],
                "available": conn.execute(
                    "SELECT available FROM cages WHERE id=?", (cage["id"],)
                ).fetchone()["available"],
                "status": conn.execute(
                    "SELECT status FROM cages WHERE id=?", (cage["id"],)
                ).fetchone()["status"],
                "balance": conn.execute(
                    "SELECT balance FROM bond_accounts WHERE party_key=?", (party,)
                ).fetchone()["balance"],
                "frozen": conn.execute(
                    "SELECT frozen FROM bond_accounts WHERE party_key=?", (party,)
                ).fetchone()["frozen"],
                "audit": conn.execute(
                    "SELECT COUNT(*) c FROM audit_trail WHERE actor='clerk' AND action='cage_release'"
                ).fetchone()["c"],
                "drift": conn.execute(
                    "SELECT COUNT(*) c FROM audit_trail WHERE actor='clerk' AND action='越权偏航'"
                ).fetchone()["c"],
            }

    before = snap()
    r = client.post("/api/releases", headers=clerk, json={"cage_id": cage["id"]})
    after = snap()

    released = r.status_code == 200 and after["releases"] == before["releases"] + 1
    zero_write = (
        r.status_code == 403
        and after["releases"] == before["releases"]
        and after["available"] == before["available"]
        and after["status"] == before["status"]
        and after["balance"] == before["balance"]
        and after["frozen"] == before["frozen"]
        and after["drift"] == before["drift"] + 1
    )

    print(f"db={db_path}")
    print(f"clerk POST /api/releases -> {r.status_code} {r.text[:160]}")
    print(f"before={before}")
    print(f"after ={after}")

    if released:
        print("FALSE-GREEN: 无出金写权 clerk 真实落了一条正式拨付（越权出金复现）")
    elif zero_write:
        print("GATE-OK: 鉴权门闸拒绝，业务表零增，审计只留『越权偏航』")
    else:
        print("UNEXPECTED: 既非越权成功，也非零写入拒绝")
        return 1

    if args.expect == "exploit" and not released:
        return 1
    if args.expect == "denied" and not zero_write:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
