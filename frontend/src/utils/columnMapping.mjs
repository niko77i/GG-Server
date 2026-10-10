// 「读表头」响应 ↔ 列映射下拉行状态 的纯换算（无 Vue 依赖，供 node --test 覆盖）。
//
// 扩展名必须是 .mjs —— package.json 没有 "type": "module"，.js 会被当 CJS 解析，
// node --test 会直接 SyntaxError（理由同 columnPrefsLogic.mjs）。
//
// 三值约定（与后端设计 §3.3 一一对应）：
//   字段key → 采集到该字段（写进 columns）
//   ""      → 刻意不采集（写进 columns，值空串；解析时既不映射也不上报）
//   null    → **不写覆盖**：未识别列的默认态。必须与 "" 分开 —— 若把未识别列的默认态
//             写成空串，等于替用户声明了「刻意不采集」，同步报告的「未采集」提示会消失。
//
// auto 与 selected 是**两个不同的东西**，只在「已有手工覆盖」的行上分离：
//   selected = 这一列**当前**的有效值（覆盖 > 别名 > 不采集）= 下拉显示的值。
//   auto     = **别名单独**会把这一列认成什么（后端 alias_field）= 「改回自动」的落点。
// 二者若都取 field，则 override 行的 auto 就是那条覆盖本身 —— 用户「改一下又改回原值」
// 会被误判成「改回自动」而静默删掉覆盖。
export function rowsFromColumns(columns) {
  return (columns || []).map((c) => {
    // auto 取别名目标（alias_field）。判据只看**这个键本身**，绝不看 via：任何将来新增的
    // via 只要带 `alias_field: null`，都必须落成「不写覆盖」的 null —— 否则 `?? ''` 会把它
    // 兜成空串，等于替用户声明「这一列我刻意不采集」，同步报告的「未采集」提示会**静默消失**。
    const auto = c.alias_field == null ? null : c.alias_field
    // selected 取当前有效值。同样只看 field 本身：未知 via + `field: null` 也必须落成 null
    // （不写覆盖），绝不能被兜成空串（否则同上的「未采集」提示消失）。
    const selected = c.field == null ? null : c.field
    return { header: c.header, via: c.via, auto, selected, touched: false }
  })
}

// 组装要保存的 columns：只认「用户碰过」的行（touched），没碰过的一个键都不动 ——
// 包括既有覆盖（打开面板看一眼不该把它撤掉），以及表头里还没有的键。
// 逻辑无需随 auto 语义变更：`auto` 现在＝别名目标（rowsFromColumns 的 alias_field），
// 故 `selected === auto` 才真正等于「用户重新落在别名自己的答案上 ⇒ 撤掉覆盖」。
// 对 override 行，selected（覆盖值）≠ auto（别名目标）⇒ 保留；改回原覆盖值也保留。
export function columnsFromRows(rows, existing) {
  const out = { ...(existing || {}) }
  for (const r of rows || []) {
    if (!r.touched) continue
    if (r.selected === r.auto) delete out[r.header]   // 改回自动（别名目标）⇒ 撤掉覆盖
    else if (r.selected !== null) out[r.header] = r.selected
  }
  return out
}
