/**
 * 账户看板三张表的列注册表 —— 列清单的唯一真相源。
 *
 * 设计见 docs/superpowers/specs/2026-10-08-account-column-prefs-design.md。
 * - 数组声明顺序 = 默认显示顺序（不依赖对象 key 顺序语义）
 * - 每项的宽度属性逐字沿用各面板改造前模板里写死的值，
 *   保证零配置时视觉与改造前逐像素一致
 * - available 承接原有的角色闸门（原先散落在模板里的 v-if="authStore.isHuguan"）
 *
 * panel key 必须与 py/column_prefs.py 的 PANELS 逐字一致。
 */

export const PANEL_KEYS = {
  GG_ADS: 'gg_ads',
  TT_ADS: 'tt_ads',
  FB_ADS: 'fb_ads',
}

export const GG_ADS_COLUMNS = [
  { key: 'name', label: '账号名称', minWidth: 140 },
  { key: 'account_id', prop: 'account_id', label: '账号 ID', minWidth: 140, showOverflowTooltip: true },
  { key: 'sheet_write', label: '写表', width: 54, align: 'center' },
  { key: 'mcc', label: '所属 MCC', minWidth: 140 },
  { key: 'timezone', label: '时区', minWidth: 120 },
  { key: 'agent', label: '代理', minWidth: 140 },
  { key: 'status', label: '状态', minWidth: 120 },
  { key: 'acquired_date', prop: 'acquired_date', label: '到手时间', minWidth: 100, showOverflowTooltip: true },
  { key: 'status_changed', label: '状态变更时间', minWidth: 110, showOverflowTooltip: true },
  { key: 'owner', label: '户归属', width: 160, align: 'center', available: (auth) => auth.isHuguan },
]

export const TT_ADS_COLUMNS = [
  { key: 'advertiser_id', prop: 'advertiser_id', label: '广告账户 ID', minWidth: 150, showOverflowTooltip: true },
  { key: 'sheet_write', label: '写表', width: 54, align: 'center' },
  { key: 'bc', label: '所属 BC', minWidth: 160 },
  { key: 'timezone', label: '时区', minWidth: 120 },
  { key: 'agent', label: '代理', minWidth: 140 },
  { key: 'status', label: '状态', minWidth: 120 },
  { key: 'country', label: '国家', minWidth: 110 },
  { key: 'consumption', label: '消耗情况', minWidth: 120 },
  { key: 'remark', label: '备注', minWidth: 160 },
  { key: 'acquired_date', prop: 'acquired_date', label: '到手时间', minWidth: 100, showOverflowTooltip: true },
  { key: 'status_changed', label: '状态变更时间', minWidth: 110, showOverflowTooltip: true },
  { key: 'owner', label: '户归属', width: 160, align: 'center', available: (auth) => auth.isHuguan },
  { key: 'owner_change_note', prop: 'owner_change_note', label: '换绑情况', minWidth: 160, showOverflowTooltip: true, available: (auth) => auth.isHuguan },
]

export const FB_ADS_COLUMNS = [
  { key: 'name', prop: 'name', label: '账户名', minWidth: 120 },
  { key: 'account_id', prop: 'account_id', label: '账户ID', width: 160 },
  { key: 'sheet_write', label: '写表', width: 54, align: 'center' },
  { key: 'bms', label: '所属BM', minWidth: 140 },
  { key: 'location', label: '位置', minWidth: 120 },
  { key: 'channel', label: '所属渠道', width: 110 },
  { key: 'asset_type', label: '资产类型', width: 110 },
  { key: 'status', label: '状态', width: 100 },
  { key: 'operator', prop: 'operator', label: '操作人', width: 100 },
  { key: 'timezone', prop: 'timezone', label: '时区', width: 100 },
  { key: 'acquired_date', prop: 'acquired_date', label: '到手时间', width: 110 },
]
