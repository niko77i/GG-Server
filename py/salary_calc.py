"""投手薪资计算（2026-11 版）—— 纯函数，不碰 IO，便于单测。

口径（2026-11-04 与用户逐条确认）：

    代投费 = 做表 M 列合计（M = F×L，L 是代投比例）
    纯增值 = Σ(F 列 − K 列)，**只统计 K 列有值的行**
    消耗   = K 列（平台实际）合计，同样只统计 K 有值的行
    基数   = 代投费 + 纯增值（等价于做表 N 列合计，N = F−K+M）
    利润   = 基数 − 成本（成本由页面手填，默认 0）
    总薪资 = 底薪 + (消耗提成 + 利润提成) × USDT 汇率

档位一律**左闭右开**（恰好等于下界时归入下一档）：

| 项 | 判定字段 | 档位 → 结果 |
|---|---|---|
| 底薪（元） | 基数 | <1万→4000；<3万→6000；<4万→8000；≥4万→**10000** |
| 消耗费率 | 消耗 | <20万→0.002；≥20万→0.003（**全额按档位**，非超额累进） |
| 利润提成费率 | 纯增值 | <0→**0.01**；<2万→0.10；<3万→0.12；<4万→0.15；≥4万→0.18 |

两处与旧版（2026-11-03）的差别，均为用户 2026-11-04 明确更正：

1. 底薪 4 万以上由 8000 改为 **10000**（旧版把 3-4万与 4万以上做成同值，等于空档）。
2. 纯增值为负时利润提成费率取 **0.01**（旧版没有负档，会落到 0.10）。

利润为负时提成按 0 计（不倒扣），但明细里照实显示负利润。
"""

# 底薪四档：前端下拉框只给这四个选项
BASE_SALARY_OPTIONS = (4000, 6000, 8000, 10000)

# 下拉框的默认选中项（用户 2026-11-04 指定：默认 6000）。
# ⚠️ 这只是**页面的预选值**，不是判档规则：`compute_salary(base_salary=None)` 仍按基数
# 自动判档（那是口径本身）。页面会把「按基数应落哪档」以提示文字带出来，用户可改选。
DEFAULT_BASE_SALARY = 6000

# 消耗档位分界与费率
SPEND_TIER = 200000
SPEND_RATE_LOW = 0.002
SPEND_RATE_HIGH = 0.003

# 利润提成费率（按纯增值判档）
PROFIT_RATE_NEGATIVE = 0.01
PROFIT_RATE_TIERS = (20000, 30000, 40000)
PROFIT_RATE_VALUES = (0.10, 0.12, 0.15, 0.18)

DEFAULT_USDT_RATE = 6.6


def base_salary_for(core: float) -> tuple[int, str]:
    """按「基数 = 代投费 + 纯增值」返回 (底薪, 档位名)。

    边界：10000 → 6000；30000 → 8000；40000 → 10000（左闭右开）。
    """
    if core < 10000:
        return 4000, "0-1万"
    if core < 30000:
        return 6000, "1-3万"
    if core < 40000:
        return 8000, "3-4万"
    return 10000, "4万以上"


def spend_rate_for(spend: float) -> float:
    """消耗费率。恰好 200000 走 0.003（全额按档位）。"""
    return SPEND_RATE_HIGH if spend >= SPEND_TIER else SPEND_RATE_LOW


def profit_rate_for(net_value: float) -> tuple[float, str]:
    """利润提成费率，按纯增值判档；负增值单独一档 0.01。"""
    if net_value < 0:
        return PROFIT_RATE_NEGATIVE, "负增值"
    if net_value < PROFIT_RATE_TIERS[0]:
        return PROFIT_RATE_VALUES[0], "0-2万"
    if net_value < PROFIT_RATE_TIERS[1]:
        return PROFIT_RATE_VALUES[1], "2-3万"
    if net_value < PROFIT_RATE_TIERS[2]:
        return PROFIT_RATE_VALUES[2], "3-4万"
    return PROFIT_RATE_VALUES[3], "4万以上"


def compute_salary(agency_fee: float, net_value: float, spend: float,
                   cost: float = 0.0, base_salary: int | None = None,
                   usdt_rate: float = DEFAULT_USDT_RATE) -> dict:
    """按现行口径算一份薪资明细。

    Args:
        agency_fee: 代投费合计（USDT，做表 M 列）
        net_value: 纯增值合计（USDT，Σ(F−K)，可为负）
        spend: 消耗合计（USDT，做表 K 列）
        cost: 成本（USDT，页面手填，默认 0）
        base_salary: 底薪覆盖值（下拉框选的四档之一）；None 时按基数自动判档
        usdt_rate: USDT→人民币汇率

    Returns:
        明细字典（金额均为未取整的原始浮点，取整交给展示层）：
        core / base_salary / base_salary_band / spend / spend_rate / spend_bonus
        / profit / profit_base / profit_rate / profit_rate_band / profit_bonus
        / usdt_total / usdt_rmb / total
    """
    agency_fee = float(agency_fee or 0)
    net_value = float(net_value or 0)
    spend = float(spend or 0)
    cost = float(cost or 0)
    usdt_rate = float(usdt_rate if usdt_rate is not None else DEFAULT_USDT_RATE)

    core = agency_fee + net_value  # 基数：底薪只看这个，不扣成本
    auto_base, auto_band = base_salary_for(core)
    if base_salary is None:
        base, band = auto_base, auto_band
    else:
        base = int(base_salary)
        # 手选档位时仍把「按基数应落哪档」带出来，便于页面提示是否偏离
        band = f"手动选择（按基数应为 {auto_base}）"

    spend_rate = spend_rate_for(spend)
    spend_bonus = spend * spend_rate

    profit = core - cost
    profit_base = max(profit, 0.0)  # 负利润不倒扣
    profit_rate, profit_band = profit_rate_for(net_value)
    profit_bonus = profit_base * profit_rate

    usdt_total = spend_bonus + profit_bonus
    usdt_rmb = usdt_total * usdt_rate
    total = base + usdt_rmb

    return {
        "agency_fee": agency_fee,
        "net_value": net_value,
        "spend": spend,
        "cost": cost,
        "core": core,
        "base_salary": base,
        "base_salary_band": band,
        "base_salary_auto": auto_base,
        "base_salary_auto_band": auto_band,
        "manual_base_salary": base_salary is not None,
        "spend_rate": spend_rate,
        "spend_bonus": spend_bonus,
        "profit": profit,
        "profit_base": profit_base,
        "profit_rate": profit_rate,
        "profit_rate_band": profit_band,
        "profit_bonus": profit_bonus,
        "usdt_total": usdt_total,
        "usdt_rmb": usdt_rmb,
        "usdt_rate": usdt_rate,
        "total": total,
    }
