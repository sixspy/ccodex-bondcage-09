# 保证金笼

> 遵守 `ops/底座生成前必读_效率与技术栈.md`（≥2000 行像产品）。  
> FastAPI + Vue 3 + SQLite；`docker compose up -d --build` 一键起。  
> **禁止同构换皮**：主链路不是「占位→确认入册」也不是「入轨→裁定赔付」也不是「业务窗裁切物化」。

## 骨架一句话

保证金先入笼冻结，履约核验通过才解笼拨付，违约进罚没册，笼代与拨付罚没对账。

## 基本信息

| 项 | 值 |
|----|-----|
| 产品名 | 保证金笼 |
| 目录 | `11-bondcage` |
| 接口 | http://127.0.0.1:11319 |
| 库 | `data/app.db` |
| 账号 | admin / clerk / viewer ，密码均为 123456（viewer 只读；clerk 无出金写权） |

## 越权写闸（2026-11-22 锁定）

见 `ops/越权写闸纪要.md`。口径：**乙路径——审批影子 + 服务端代写**。

- 出金类写口（`/api/releases`、`/api/forfeits`、`/api/topup-stub`、`/api/split-stub`）仅 `admin` 可直接写。
- `clerk` / `viewer` 在鉴权层被拒（403），业务表零增，只落审计 `越权偏航`；可建审批影子单（`/api/approvals`）。
- 管理员批准后由服务端在同一事务内代写正式拨付/罚没；驳回则影子作废、正式表零改。
- 两写角色同笼争用：后到 409，仅留 `contention_log` 争用痕，业务零增。
- 复现夹具：`python scripts/repro_unauthorized_release.py --expect denied`（跑本机文件库副本）。

## 厚度

| 项 | 内容 |
|----|------|
| 业务 LOC | **≥2900**（py+前端，不含 vue.global / Docker / README；自检约 2984） |
| 后端模块 | db / auth / locks / bonds_svc / cages_svc / attest_svc / release_svc / forfeit_svc / reconcile_svc / audit_svc / approval_svc / topup_svc / split_svc |
| 前端视图 | 保证金户 / 入笼冻结 / 履约核验 / 解笼拨付 / 罚没册 / 对账互证 / 审计争用 / 增补拆笼空桩（8 页） |
| 空桩 | topup（增补入笼）、split（拆笼分拨）——前后端均有 |

## 主链路

开户入金 → 按合约入笼冻结（笼代）→ 履约核验通过 → 解笼拨付到收款方 / 违约罚没 → 笼代余额与拨付+罚没对账

## 互斥切口候选

- 解笼失败整笔回滚 vs 影子拨付后晋升
- 罚没立即入册 vs 影子罚没待复核晋升
- 增补同笼扩代 vs 新笼桥接双写
- 拆笼整笔事务切分 vs 影子子笼后晋升

## 启动

```powershell
cd projects/11-bondcage
docker compose up -d --build
```

浏览器：http://127.0.0.1:11319/

本机开发：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 10608
python -m pytest -q
```
