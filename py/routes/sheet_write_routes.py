"""写表失败治理的 HTTP 入口。

设计见 docs/superpowers/specs/2026-10-06-sheet-write-failure-governance-design.md。
本文件只做取参/鉴权/调逻辑层，状态机与执行器都在 py/sheet_write.py。
"""
import json
import logging

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

import sheet_write
from .helpers import ok, err, get_uid, get_db

sheet_write_bp = Blueprint("sheet_write", __name__)

log = logging.getLogger("gg-server")

_PLATFORMS = ("gg", "tt", "fb")

# build_sync 抛 KeyError 的语义是「target 不在注册表里」（sheet_write.build_sync）。
# 详情（含客户端入参 target）只落日志；响应回固定文案，不直出 `str(e)`。
_BUILD_SYNC_FAILED_MSG = "未注册的写表目标，详情见服务端日志"


@sheet_write_bp.route("/api/sheet-write/status", methods=["GET"])
@jwt_required()
def sheet_write_status():
    """查当前用户的写表任务。

    带 `business_key` → 回该项（含 pending/failed 中间态），供前端轮询；
    不带           → 只回需要提示的终态，供列表标记。

    带 `target`（三期新增）→ 把结果限定在该写表目标上。多个 target 的 `business_key`
    常常是同一个 `account_id`（三期的 4 个 target 全是），不过滤就只能看到 `updated_at`
    最新的一行 —— 一个 target 的行会遮住另一个，静默漏报。**不传时行为与加该参数前
    完全一致**，故一期 TT / 二期 GG 的既有前端不受影响。

    隔离约束写在 SQL 的 `WHERE user_id=?` 里，不在 Python 侧过滤。
    """
    db = get_db()
    uid = get_uid()
    platform = (request.args.get("platform") or "").strip()
    business_key = (request.args.get("business_key") or "").strip()
    # 三期新增：按 target 过滤。4 个 target 的 business_key 都是 account_id，
    # 同一账户同时有两条（如 huguan_dashboard + operator_dashboard_remark）正常；
    # 不过滤会让一个 target 的行遮住另一个 ⇒ 静默漏报。
    # **不传时行为与改动前完全一致**（向后兼容一期 TT / 二期 GG 的前端）。
    target = (request.args.get("target") or "").strip()
    if platform not in _PLATFORMS:
        db.close()
        return err("platform 必须是 gg / tt / fb", 400)

    # 惰性收敛：把超时停在中间态的任务按当前用户收敛为终态，使它们立刻可见且可重试。
    # 放在 SELECT 之前 —— 同一次轮询里，卡住的行就能出现在下面的 ATTENTION 列表里。
    sheet_write.sweep_stale(db, user_id=uid)

    sql = ("SELECT business_key, target, status, error_msg, created_at, updated_at, settled_at "
           "FROM sheet_write_log WHERE user_id=? AND platform=?")
    params = [uid, platform]
    if target:
        sql += " AND target=?"
        params.append(target)
    if business_key:
        sql += " AND business_key=?"
        params.append(business_key)
    sql += " ORDER BY updated_at DESC"
    items = [dict(r) for r in db.execute(sql, params).fetchall()]
    db.close()

    if business_key:
        return ok({"item": items[0] if items else None})
    return ok({"items": [i for i in items if i["status"] in sheet_write.ATTENTION]})


@sheet_write_bp.route("/api/sheet-write/retry", methods=["POST"])
@jwt_required()
def sheet_write_retry():
    """重试一次失败的写表。

    只有**需要提示的终态**才可重试 —— pending 还在途、synced 已成功，都不该
    被重复提交（重复提交会对同一个账户写第二行）。
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return err("请求体必须是 JSON 对象", 400)
    platform = str(data.get("platform") or "").strip()
    target = str(data.get("target") or "").strip()
    business_key = str(data.get("business_key") or "").strip()
    if platform not in _PLATFORMS or not target or not business_key:
        return err("platform / target / business_key 均为必填", 400)

    db = get_db()
    uid = get_uid()
    row = db.execute(
        "SELECT * FROM sheet_write_log WHERE user_id=? AND platform=? AND target=? "
        "AND business_key=?", (uid, platform, target, business_key)).fetchone()
    if row is None:
        db.close()
        return err("没有找到该写表记录", 404)

    def _load(raw):
        try:
            v = json.loads(raw or "{}")
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}

    payload = _load(row["payload_json"])
    snapshot = _load(row["snapshot_json"])

    # 先构造 sync_fn、再动 status：build_sync 是纯工厂，rebuild 工厂必须无副作用
    # （纯构造，见 sheet_write.register_target），所以放在 claim 之前零成本。否则
    # 未注册 / 配置错的目标要到 claim **之后**才炸，行已被置为 pending 且无人推进
    # —— pending 不在 ATTENTION 里，标记不显示、轮询静默超时，闸门只放行
    # ATTENTION，该任务永久不可重试（正是本功能要消灭的静默卡住）。
    try:
        sync_fn = sheet_write.build_sync(target, uid, business_key, payload)
    except KeyError as e:
        db.close()
        log.warning("写表重试：构建同步器失败 target=%s：%s", target, e)
        return err(_BUILD_SYNC_FAILED_MSG, 400)

    # 原子闸门：把「检查状态」与「置为 pending」合成一条守卫式 UPDATE，
    # 按 rowcount 决定是否放行。原来是 check-then-act，两个并发 POST 会双双
    # 通过检查、双双起后台写 → 同一账户在回收清单里写进两行。
    cur = db.execute(
        "UPDATE sheet_write_log SET status='pending', settled_at=NULL, "
        "updated_at=datetime('now','localtime') "
        "WHERE user_id=? AND platform=? AND target=? AND business_key=? "
        "AND status IN (?,?,?)",
        (uid, platform, target, business_key, *sheet_write.ATTENTION))
    db.commit()
    if cur.rowcount != 1:
        db.close()
        return err("该写表任务当前不需要重试（可能已在同步中或已成功）", 400)

    # 沿用上轮的 snapshot：回滚要撤销的仍是同一次业务变更，不能因为重试而丢掉守卫依据
    sheet_write.run_write(db, user_id=uid, platform=platform, target=target,
                          business_key=business_key, sync_fn=sync_fn,
                          payload=payload, snapshot=snapshot)
    db.close()
    return ok({"message": "已重新提交，请稍后查看结果"})
