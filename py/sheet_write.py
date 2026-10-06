"""写表失败统一治理：登记任务 → 后台写表 → 按最终结果落状态 / 回滚。

设计见 docs/superpowers/specs/2026-10-06-sheet-write-failure-governance-design.md。

本模块只做编排与状态机，不 import flask；真正的 Sheets I/O 由各 target 的
执行器负责（见 register_target），HTTP 入口在 routes/sheet_write_routes.py。
"""
import json
import logging

log = logging.getLogger("gg-server")

# 终态：settled_at 非空。前端轮询到终态即停。
TERMINAL = ("synced", "retry_failed", "rolled_back", "rollback_abandoned")
# 需要向用户提示的终态（synced 是「没出事」，不打扰）
ATTENTION = ("retry_failed", "rolled_back", "rollback_abandoned")

# 写表窗口 = 首次尝试 + 30s 重试；留 3 倍余量。超过这个时长仍停在中间态，
# 说明推进它的线程已经不在了（进程重启 / 后台线程启动失败），需要惰性收敛。
STALE_AFTER_SECONDS = 90

# target -> {"rebuild": (user_id, business_key, payload) -> sync_fn,
#            "rollback": (db, snapshot) -> bool  |  None}
TARGETS = {}


def register_target(name, rebuild, rollback=None):
    """注册一个写表目标。

    rebuild 必须是**工厂**而不是现成的 zero-arg 函数：重试发生在另一次请求里，
    执行器要在**后台线程内**用 database.get_db() 新建连接、新建 service
    （sqlite 连接与 httplib2 客户端都不可跨线程复用）。

    rebuild 还必须是**纯构造**（无副作用）：不得做 I/O、不得读写数据库。
    重试端点会在「原子 claim」**之前**调用它 —— 若它会失败或产生副作用，
    未注册/配置错的目标会把记录留在 pending 且无人推进（pending 不在
    ATTENTION 里，标记不显示、轮询静默超时，且闸门只放行 ATTENTION，
    该任务从此永久不可重试）。
    """
    TARGETS[name] = {"rebuild": rebuild, "rollback": rollback}


def build_sync(target, user_id, business_key, payload):
    """按注册表构造写表函数。初始写表与重试共用同一条重建路径（DRY）。"""
    entry = TARGETS.get(target)
    if entry is None:
        raise KeyError(f"未注册的写表目标: {target}")
    return entry["rebuild"](user_id, business_key, payload or {})


def record_pending(db, *, user_id, platform, target, business_key,
                   payload=None, snapshot=None):
    """登记一条写表任务。同键 upsert 回 pending 并清空上轮结果。

    在**请求线程**用调用方的 db 执行 —— 前端拿到响应后要立刻能查到这条记录。
    """
    db.execute(
        "INSERT INTO sheet_write_log (user_id, platform, target, business_key, "
        "status, error_msg, payload_json, snapshot_json, settled_at) "
        "VALUES (?,?,?,?,'pending','',?,?,NULL) "
        "ON CONFLICT(user_id, target, business_key) DO UPDATE SET "
        "platform=excluded.platform, status='pending', error_msg='', "
        "payload_json=excluded.payload_json, snapshot_json=excluded.snapshot_json, "
        "settled_at=NULL, updated_at=datetime('now','localtime')",
        (user_id, platform, target, business_key,
         json.dumps(payload or {}, ensure_ascii=False),
         json.dumps(snapshot or {}, ensure_ascii=False)))
    db.commit()


def sweep_stale(db, user_id=None):
    """把长时间停在中间态（pending / failed）的任务收敛为终态。

    这些行没有别的收敛路径：进程重启、后台线程启动失败都会让它们永久停在中间态，
    而中间态既不在 ATTENTION 里（列表不显示）又过不了重试闸门（不可重试）——
    等于失败记录静默丢失，正是本功能要消灭的形态。

    在 status 接口里按当前用户惰性调用，任何进程都能自愈，无需启动钩子。
    """
    sql = ("UPDATE sheet_write_log SET status='retry_failed', "
           "error_msg=(CASE WHEN error_msg IS NULL OR error_msg='' THEN '' "
           "ELSE error_msg || '；' END) || '任务中断：写表未在预期时间内完成', "
           "settled_at=datetime('now','localtime'), "
           "updated_at=datetime('now','localtime') "
           "WHERE status IN ('pending','failed') "
           "AND updated_at < datetime('now','localtime', ?)")
    params = [f"-{STALE_AFTER_SECONDS} seconds"]
    if user_id is not None:
        sql += " AND user_id=?"
        params.append(user_id)
    cur = db.execute(sql, params)
    db.commit()
    return cur.rowcount


def settle(db, *, user_id, target, business_key, status, error_msg=""):
    """落状态。settled_at 只在终态置上。"""
    db.execute(
        "UPDATE sheet_write_log SET status=?, error_msg=?, "
        "settled_at=CASE WHEN ? THEN datetime('now','localtime') ELSE settled_at END, "
        "updated_at=datetime('now','localtime') "
        "WHERE user_id=? AND target=? AND business_key=?",
        (status, error_msg, 1 if status in TERMINAL else 0,
         user_id, target, business_key))
    db.commit()


def _apply_final(db, row, err_msg):
    """写表最终失败后的处置：先试条件回滚，再决定落哪个终态。

    三种结局必须区分，因为用户的后续动作完全不同：
      retry_failed        镜像类，无回滚 —— 业务变更仍生效，用户需自己处理
      rolled_back         已撤销 —— 用户无需再做任何事
      rollback_abandoned  未能自动撤销 —— 用户需手工核对
    """
    entry = TARGETS.get(row["target"]) or {}
    rollback_fn = entry.get("rollback")
    if rollback_fn is None:
        settle(db, user_id=row["user_id"], target=row["target"],
               business_key=row["business_key"], status="retry_failed",
               error_msg=err_msg)
        return

    try:
        snapshot = json.loads(row["snapshot_json"] or "{}")
    except Exception:
        snapshot = {}
    rolled = False
    rb_error = None
    try:
        rolled = bool(rollback_fn(db, snapshot))
    except Exception as e:
        log.error("写表回滚异常 target=%s key=%s: %s",
                  row["target"], row["business_key"], e)
        rb_error = str(e)[:200]

    if rolled:
        settle(db, user_id=row["user_id"], target=row["target"],
               business_key=row["business_key"], status="rolled_back",
               error_msg=err_msg)
    else:
        if rb_error is not None:
            # 回滚器自己炸了 —— 不能断言「账户被再次修改」，那是另一回事
            note = f"自动撤销失败（回滚过程出错：{rb_error}），业务变更仍生效，请手工核对"
        else:
            note = "该账户在写表期间被再次修改，未自动撤销，请手工核对"
        settle(db, user_id=row["user_id"], target=row["target"],
               business_key=row["business_key"], status="rollback_abandoned",
               error_msg=f"{err_msg}（{note}）")


def run_write(db, *, user_id, platform, target, business_key, sync_fn,
              payload=None, snapshot=None):
    """统一写表入口。绝不抛异常 —— 写表是业务端点的副作用，不得影响主流程。

    调用方在**请求线程**传入 db（仅用于登记 pending），随后写表在线程内进行；
    线程内的一切 DB 操作由本函数用 database.get_db() 另建连接。
    """
    try:
        record_pending(db, user_id=user_id, platform=platform, target=target,
                       business_key=business_key, payload=payload, snapshot=snapshot)
    except Exception as e:
        # 登记失败不该阻断写表本身，但必须有痕迹 —— 否则前端永远查不到这次任务
        log.error("写表任务登记失败 target=%s key=%s: %s", target, business_key, e)

    def _on_result(status, err_msg):
        import database
        _db = None
        try:
            _db = database.get_db()
            row = _db.execute(
                "SELECT * FROM sheet_write_log WHERE user_id=? AND target=? AND business_key=?",
                (user_id, target, business_key)).fetchone()
            if row is None:
                return
            if status == "synced":
                settle(_db, user_id=user_id, target=target, business_key=business_key,
                       status="synced", error_msg="")
            elif status == "failed":
                # 中间态：30s 重试在途。前端据此继续轮询，但**不提示**。
                settle(_db, user_id=user_id, target=target, business_key=business_key,
                       status="failed", error_msg=(err_msg or "")[:500])
            else:
                _apply_final(_db, row, (err_msg or "")[:500])
        except Exception as e:
            log.error("写表状态落库失败 target=%s key=%s: %s", target, business_key, e)
        finally:
            if _db is not None:
                try:
                    _db.close()
                except Exception:
                    pass

    try:
        from main import _sync_sheets_background
        _sync_sheets_background(sync_fn, _on_result)
    except Exception as e:
        log.error("写表后台任务启动失败 target=%s key=%s: %s", target, business_key, e)
