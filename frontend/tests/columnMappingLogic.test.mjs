import test from 'node:test'
import assert from 'node:assert/strict'
import { rowsFromColumns, columnsFromRows } from '../src/utils/columnMapping.mjs'

// 三值约定：字段key = 采集 / "" = 刻意不采集 / null = 不写覆盖（未识别列的默认态）
test('rowsFromColumns: 四档 via 各自映射到正确的显示值与自动值', () => {
  const rows = rowsFromColumns([
    { header: '账户ID', field: 'advertiser_id', via: 'alias' },
    { header: '备注二', field: 'remark', via: 'override' },
    { header: '位置', field: '', via: 'ignored' },
    { header: '陌生列', field: null, via: 'none' },
  ])
  assert.deepEqual(rows, [
    { header: '账户ID', via: 'alias', auto: 'advertiser_id', selected: 'advertiser_id', touched: false },
    { header: '备注二', via: 'override', auto: 'remark', selected: 'remark', touched: false },
    { header: '位置', via: 'ignored', auto: '', selected: '', touched: false },
    { header: '陌生列', via: 'none', auto: null, selected: null, touched: false },
  ])
})

test('columnsFromRows: 没碰过的行一个键都不写', () => {
  const rows = rowsFromColumns([{ header: '陌生列', field: null, via: 'none' }])
  assert.deepEqual(columnsFromRows(rows, {}), {})
  // 关键回归：未识别列的默认态**不能**写成空串 —— 那等于声明「刻意不采集」，
  // 同步报告的「未采集」提示会因此消失。
})

test('columnsFromRows: 没碰过的既有覆盖原样保留（打开面板不该悄悄撤掉它）', () => {
  const rows = rowsFromColumns([{ header: '备注二', field: 'remark', via: 'override' }])
  assert.deepEqual(columnsFromRows(rows, { 备注二: 'remark' }), { 备注二: 'remark' })
})

test('columnsFromRows: 碰过并改了 ⇒ 写入', () => {
  const rows = rowsFromColumns([{ header: '陌生列', field: null, via: 'none' }])
  rows[0].touched = true
  rows[0].selected = 'remark'
  assert.deepEqual(columnsFromRows(rows, {}), { 陌生列: 'remark' })
})

test('columnsFromRows: 显式选「（不采集）」⇒ 写空串；改回自动值 ⇒ 撤掉覆盖', () => {
  const rows = rowsFromColumns([{ header: '陌生列', field: null, via: 'none' },
                                { header: '日期', field: 'acquired_date', via: 'alias' }])
  rows[0].touched = true
  rows[0].selected = ''
  rows[1].touched = true
  rows[1].selected = 'acquired_date'   // 与 auto 相同 = 改回自动
  assert.deepEqual(columnsFromRows(rows, { 日期: 'remark' }), { 陌生列: '' })
})

test('columnsFromRows: 已有但已不在表头里的键必须保留（表头以后再加）', () => {
  const rows = rowsFromColumns([{ header: '账户ID', field: 'advertiser_id', via: 'alias' }])
  assert.deepEqual(columnsFromRows(rows, { 未来列: 'remark' }), { 未来列: 'remark' })
})

test('rowsFromColumns: 判据只看 field 不看 via —— 未知 via 带 field:null 仍是「不写覆盖」', () => {
  // 回归钉子：旧写法是 `c.via === 'none' ? null : (c.field ?? '')`，任何将来新增的 via
  // 只要带 field:null，就被 `?? ''` 兜成空串 = 替用户声明「刻意不采集」，
  // 同步报告的「未采集」提示会静默消失。判据必须是 field 本身。
  const rows = rowsFromColumns([{ header: '将来列', field: null, via: '将来才有的档位' }])
  assert.deepEqual(rows, [
    { header: '将来列', via: '将来才有的档位', auto: null, selected: null, touched: false },
  ])
  assert.notEqual(rows[0].auto, '', '未知 via + field:null 绝不能被兜成空串')
  // 而且它默认不落盘（touched=false），不会写成空串覆盖
  assert.deepEqual(columnsFromRows(rows, {}), {})
})
