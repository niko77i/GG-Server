// FB 配置 → 渲染用 tables 的摊平/折回（设计 §4.9）。
// 运行：cd frontend && npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { seedTables, flattenColumns } from '../src/utils/columnMapping.mjs'

test('fb：存量扁平配置（legacy 过渡态）摊成一条 table', () => {
  const rows = seedTables(
    { spreadsheet_id: 'SS', sheet_name: '账户管理分配', columns: { 时区: 'consumption' } }, 'fb')
  assert.deepEqual(rows, [{ name: '', sheet_name: '账户管理分配',
                            columns: { 时区: 'consumption' } }])
})

test('fb：没配过也给一条空行（用户得有地方填工作表名）', () => {
  assert.deepEqual(seedTables({}, 'fb'), [{ name: '', sheet_name: '', columns: {} }])
})

test('fb：columns 形状不对时兜成空对象', () => {
  assert.deepEqual(seedTables({ sheet_name: 'S', columns: 'garbage' }, 'fb'),
    [{ name: '', sheet_name: 'S', columns: {} }])
})

test('tt：认后端给的 tables，并复制 columns', () => {
  const src = [{ name: '加白户', sheet_name: 'S1', columns: { 日期: 'acquired_date' } }]
  const rows = seedTables({ tables: src }, 'tt')
  assert.deepEqual(rows, [{ name: '加白户', sheet_name: 'S1',
                            columns: { 日期: 'acquired_date' } }])
  assert.notEqual(rows[0].columns, src[0].columns)   // 必须是副本，不能共享引用
})

test('tt：后端没给 tables ⇒ 空列表', () => {
  assert.deepEqual(seedTables({}, 'tt'), [])
})

test('gg：既没有 tables 也不摊平（该分支不渲染表格列表）', () => {
  assert.deepEqual(seedTables({ sheet_name: 'X' }, 'gg'), [])
})

test('fb：折回时产出 tables 数组（空行过滤、空 columns 不上送）', () => {
  assert.deepEqual(
    flattenColumns('fb', [{ name: '加白户', sheet_name: ' 账户管理分配 ',
                            columns: { 时区: 'consumption' } }]),
    [{ name: '加白户', sheet_name: '账户管理分配', columns: { 时区: 'consumption' } }])
  assert.deepEqual(
    flattenColumns('fb', [{ name: '加白户', sheet_name: 'S', columns: {} }]),
    [{ name: '加白户', sheet_name: 'S' }])            // 空 columns 不上送（配置文本逐字节不变）
  assert.deepEqual(
    flattenColumns('fb', [{ name: '', sheet_name: 'S', columns: {} }]),
    [])                                               // 没填户类型名的空行被过滤
})
