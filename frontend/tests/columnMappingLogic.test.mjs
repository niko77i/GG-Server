import test from 'node:test'
import assert from 'node:assert/strict'
import { rowsFromColumns, columnsFromRows } from '../src/utils/columnMapping.mjs'

// 三值约定：字段key = 采集 / "" = 刻意不采集 / null = 不写覆盖（未识别列的默认态）
// auto = 「别名单独会把这一列认成什么」（后端 alias_field）= 改回自动的落点；
// selected = 这一列当前的有效值（field）= 下拉显示的值。二者只在「已有手工覆盖」的行上分离。
test('rowsFromColumns: 四档 via 各自映射到正确的当前值与自动值', () => {
  const rows = rowsFromColumns([
    { header: '账户ID', field: 'advertiser_id', via: 'alias', alias_field: 'advertiser_id' },
    { header: '备注二', field: 'remark', via: 'override', alias_field: null },
    { header: '位置', field: '', via: 'ignored', alias_field: '' },
    { header: '陌生列', field: null, via: 'none', alias_field: null },
  ])
  assert.deepEqual(rows, [
    { header: '账户ID', via: 'alias', auto: 'advertiser_id', selected: 'advertiser_id', touched: false },
    { header: '备注二', via: 'override', auto: null, selected: 'remark', touched: false },
    { header: '位置', via: 'ignored', auto: '', selected: '', touched: false },
    { header: '陌生列', via: 'none', auto: null, selected: null, touched: false },
  ])
})

// auto 必须取 alias_field（别名单独认出的目标），**不是**当前 field ——
// 否则 override 行的 auto 就是那条覆盖本身。
test('rowsFromColumns: auto 取别名目标，override 行不被当期值冒充', () => {
  const rows = rowsFromColumns([
    { header: '日期', field: 'remark', via: 'override', alias_field: 'acquired_date' },
  ])
  assert.equal(rows[0].auto, 'acquired_date', 'auto 应是别名单独认出的目标')
  assert.equal(rows[0].selected, 'remark', 'selected 应是这一列当前的有效值（覆盖值）')
})

test('columnsFromRows: 没碰过的行一个键都不写', () => {
  const rows = rowsFromColumns([{ header: '陌生列', field: null, via: 'none', alias_field: null }])
  assert.deepEqual(columnsFromRows(rows, {}), {})
  // 关键回归：未识别列的默认态**不能**写成空串 —— 那等于声明「刻意不采集」，
  // 同步报告的「未采集」提示会因此消失。
})

test('columnsFromRows: 没碰过的既有覆盖原样保留（打开面板不该悄悄撤掉它）', () => {
  const rows = rowsFromColumns([{ header: '备注二', field: 'remark', via: 'override', alias_field: null }])
  assert.deepEqual(columnsFromRows(rows, { 备注二: 'remark' }), { 备注二: 'remark' })
})

test('columnsFromRows: 碰过并改了 ⇒ 写入', () => {
  const rows = rowsFromColumns([{ header: '陌生列', field: null, via: 'none', alias_field: null }])
  rows[0].touched = true
  rows[0].selected = 'remark'
  assert.deepEqual(columnsFromRows(rows, {}), { 陌生列: 'remark' })
})

test('columnsFromRows: 显式选「（不采集）」⇒ 写空串；改回自动值 ⇒ 撤掉覆盖', () => {
  const rows = rowsFromColumns([{ header: '陌生列', field: null, via: 'none', alias_field: null },
                                { header: '日期', field: 'acquired_date', via: 'alias', alias_field: 'acquired_date' }])
  rows[0].touched = true
  rows[0].selected = ''
  rows[1].touched = true
  rows[1].selected = 'acquired_date'   // 与 auto 相同 = 改回自动
  assert.deepEqual(columnsFromRows(rows, { 日期: 'remark' }), { 陌生列: '' })
})

test('columnsFromRows: 已有但已不在表头里的键必须保留（表头以后再加）', () => {
  const rows = rowsFromColumns([{ header: '账户ID', field: 'advertiser_id', via: 'alias', alias_field: 'advertiser_id' }])
  assert.deepEqual(columnsFromRows(rows, { 未来列: 'remark' }), { 未来列: 'remark' })
})

// ===== I1 回归：override 行「改一下又改回原值」不得静默丢掉手工覆盖 =====

test('columnsFromRows: I1 既有覆盖行改到别处再改回原值 ⇒ 覆盖必须保留', () => {
  // 「备注二」是别名不认识的表头，已存手工覆盖 → 产品信息（remark）。
  const rows = rowsFromColumns([{ header: '备注二', field: 'remark', via: 'override', alias_field: null }])
  const existing = { 备注二: 'remark' }
  // 用户把下拉改成别的字段……
  rows[0].touched = true
  rows[0].selected = 'cost'
  assert.deepEqual(columnsFromRows(rows, existing), { 备注二: 'cost' })
  // ……又改回**原来的覆盖值**（不是别名目标 —— 别名根本不认这列）。
  rows[0].selected = 'remark'
  assert.deepEqual(columnsFromRows(rows, existing), { 备注二: 'remark' },
    '改回原覆盖值不得被当成「改回自动」而删掉覆盖')
})

test('columnsFromRows: I1 空串覆盖行改到别处再改回别名目标 ⇒ 撤掉覆盖、回落别名', () => {
  // 「日期」别名会认成入库时间（acquired_date），但用户存了空串覆盖＝刻意不采集。
  const rows = rowsFromColumns([{ header: '日期', field: '', via: 'ignored', alias_field: 'acquired_date' }])
  const existing = { 日期: '' }
  // 先改成别的字段……
  rows[0].touched = true
  rows[0].selected = 'remark'
  assert.deepEqual(columnsFromRows(rows, existing), { 日期: 'remark' })
  // ……再改回**别名自己的答案**（acquired_date）＝真正回到自动 ⇒ 覆盖应被撤掉。
  rows[0].selected = 'acquired_date'
  assert.deepEqual(columnsFromRows(rows, existing), {},
    '改回别名目标应撤掉空串覆盖，回落别名')
})

test('rowsFromColumns: 未识别列（via:none）不写覆盖的不变量仍然成立', () => {
  // 未知 via + field:null / alias_field:null 绝不能被兜成空串。
  const rows = rowsFromColumns([{ header: '将来列', field: null, via: '将来才有的档位', alias_field: null }])
  assert.deepEqual(rows, [
    { header: '将来列', via: '将来才有的档位', auto: null, selected: null, touched: false },
  ])
  assert.notEqual(rows[0].selected, '', '未知 via + field:null 绝不能被兜成空串')
  // 而且它默认不落盘（touched=false），不会写成空串覆盖
  assert.deepEqual(columnsFromRows(rows, {}), {})
})
