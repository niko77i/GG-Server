"""薪资计算路由（工具集 → 薪资计算）。

两个端点，职责分开：

- `GET  /api/salary/overview`：读一次表（用户配置里的某张做表），把 A–N 聚合成
  代投费 / 纯增值 / 消耗 / 最新日期，并附一份「默认参数」下的薪资明细
  （成本 0、底薪按基数自动判档、汇率 6.6）。
- `POST /api/salary/compute`：页面改底薪 / 成本 / 汇率时重算，**不再读表**。

计算口径全部在 `salary_calc.py`（纯函数），读表与聚合在 `salary_service.py`。
本文件只做参数校验、归属校验和 JSON 组装。

归属校验：`spreadsheet_id` 必须落在**当前用户自己配置的表格列表**里 —— 服务账号
对这些表格有读权限，不校验的话任何登录用户都能拿别人的表格 ID 读数据。
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

import salary_calc
import salary_service

salary_bp = Blueprint("salary", __name__)

# 错误文案用中文标签：前端直接展示，别把 `spend` 这种字段名丢给用户
_FIELD_LABELS = {
    "agency_fee": "代投费",
    "net_value": "纯增值",
    "spend": "消耗",
    "cost": "成本",
    "usdt_rate": "USDT 汇率",
}


def _to_float(data: dict, key: str, default: float = 0.0, allow_negative: bool = False):
    """取一个数值字段；非法返回 (None, 错误信息)。"""
    label = _FIELD_LABELS.get(key, key)
    raw = data.get(key, None)
    if raw is None or raw == "":
        return default, None
    if isinstance(raw, bool):
        return None, f"{label}必须是数字"
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, f"{label}必须是数字"
    if value != value or value in (float("inf"), float("-inf")):
        return None, f"{label}必须是有效数字"
    if not allow_negative and value < 0:
        return None, f"{label}不能为负数"
    return value, None


def _resolve_sheet(user_id: int, spreadsheet_id: str):
    """按用户配置解析目标表格。返回 (sheet 配置项, 错误响应)。"""
    from main import _get_user_sheets_config

    sheets, active = _get_user_sheets_config(user_id)
    if not sheets:
        return None, (jsonify({
            "success": False,
            "error": "还没有配置 Google 表格，请先到个人中心添加做表",
        }), 400)

    if spreadsheet_id:
        target = next((s for s in sheets if (s.get("spreadsheet_id") or "") == spreadsheet_id), None)
        if target is None:
            # 不区分「不存在」与「无权」：统一 403，别让调用方拿别人的 ID 试探
            return None, (jsonify({
                "success": False,
                "error": "该表格不在你的配置里，请从下拉框选择",
            }), 403)
        return target, None

    return (active or sheets[0]), None


@salary_bp.route("/api/salary/overview", methods=["GET"])
@jwt_required()
def salary_overview():
    """读取指定（或当前激活）做表，返回聚合结果与默认薪资明细。"""
    user_id = int(get_jwt_identity())
    spreadsheet_id = (request.args.get("spreadsheet_id") or "").strip()

    target, err = _resolve_sheet(user_id, spreadsheet_id)
    if err:
        return err

    sid = (target.get("spreadsheet_id") or "").strip()
    if not sid:
        return jsonify({"success": False, "error": "表格 ID 为空，请检查个人中心配置"}), 400

    import google_sheets_service as gs

    try:
        agg = salary_service.read_and_aggregate(sid)
    except gs.GoogleSheetsServiceError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception:
        # 异常原文可能带服务端路径 / 库名，固定文案，详情进日志
        from main import log
        log.exception("薪资计算读表失败 spreadsheet_id=%s", sid)
        return jsonify({"success": False, "error": "读取表格失败，详情见服务端日志"}), 500

    salary = salary_calc.compute_salary(
        agency_fee=agg["agency_fee"],
        net_value=agg["net_value"],
        spend=agg["spend"],
        cost=0.0,
        # 页面默认选中 6000（用户 2026-11-04 指定），不按基数自动预选；
        # 自动判档结果仍随 `base_salary_auto` 返回，前端作为提示展示。
        base_salary=salary_calc.DEFAULT_BASE_SALARY,
        usdt_rate=salary_calc.DEFAULT_USDT_RATE,
    )

    return jsonify({
        "success": True,
        "spreadsheet_id": sid,
        "spreadsheet_name": target.get("spreadsheet_name", "") or "",
        "sheet_name": agg.get("sheet_name", ""),
        "spreadsheet_title": agg.get("spreadsheet_title", ""),
        "aggregates": agg,
        "salary": salary,
        "defaults": {
            "cost": 0.0,
            "usdt_rate": salary_calc.DEFAULT_USDT_RATE,
            "base_salary": salary_calc.DEFAULT_BASE_SALARY,
            "base_salary_options": list(salary_calc.BASE_SALARY_OPTIONS),
        },
    })


@salary_bp.route("/api/salary/compute", methods=["POST"])
@jwt_required()
def salary_compute():
    """按页面参数重算薪资（不读表）。"""
    # ⚠️ `or {}` 兜不住「非空但不是对象」的请求体（`[1,2]` / `"abc"`）：
    # 它们在布尔判断上是真值，`data.get` 直接 AttributeError → 500。
    # 同族端点已踩过（sheet_write_routes / fb_routes），这里显式判 dict。
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "请求体必须是 JSON 对象"}), 400

    # 代投费 / 消耗虽然理论上非负，但它们是**从表格聚合出来的**：表里出现负的 K
    # 或手工负数时，收紧成 400 会让页面「换个成本就报错、一直卡在旧数字」。
    # 这里放行负数，把判断留给数据本身（明细里照实显示）。
    agency_fee, err = _to_float(data, "agency_fee", allow_negative=True)
    if err:
        return jsonify({"success": False, "error": err}), 400
    net_value, err = _to_float(data, "net_value", allow_negative=True)
    if err:
        return jsonify({"success": False, "error": err}), 400
    spend, err = _to_float(data, "spend", allow_negative=True)
    if err:
        return jsonify({"success": False, "error": err}), 400
    cost, err = _to_float(data, "cost")
    if err:
        return jsonify({"success": False, "error": err}), 400
    usdt_rate, err = _to_float(data, "usdt_rate", default=salary_calc.DEFAULT_USDT_RATE)
    if err:
        return jsonify({"success": False, "error": err}), 400
    if usdt_rate <= 0:
        return jsonify({"success": False, "error": "USDT 汇率必须大于 0"}), 400

    raw_base = data.get("base_salary", None)
    base_salary = None
    if raw_base not in (None, ""):
        try:
            base_salary = int(float(raw_base))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "底薪必须是数字"}), 400
        if base_salary not in salary_calc.BASE_SALARY_OPTIONS:
            return jsonify({
                "success": False,
                "error": f"底薪只能是 {'/'.join(str(x) for x in salary_calc.BASE_SALARY_OPTIONS)}",
            }), 400

    salary = salary_calc.compute_salary(
        agency_fee=agency_fee,
        net_value=net_value,
        spend=spend,
        cost=cost,
        base_salary=base_salary,
        usdt_rate=usdt_rate,
    )
    return jsonify({"success": True, "salary": salary})
