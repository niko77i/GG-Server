// FB 多表配置 → 渲染用 tables 的摊平/折回（spec §4.3 / §4.7）。
// 运行：cd frontend && npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { seedTables, flattenColumns } from '../src/utils/columnMapping.mjs'

test('fb：后端给 tables ⇒ 逐项复制（不再包成单条空名）', () => {
  const rows = seedTables(
    { spreadsheet_id: 'SS', tables: [
      { name: '加白户', sheet_name: '加白户表', columns: { 时区: 'consumption' } },
      { name: '企业户', sheet_name: '企业户表' }] }, 'fb')
  assert.deepEqual(rows, [
    { name: '加白户', sheet_name: '加白户表', columns: { 时区: 'consumption' } },
    { name: '企业户', sheet_name: '企业户表', columns: {} }])
})

test('fb：折回时产出 tables 数组（不再是扁平 sheet_name + columns）', () => {
  const tables = [
    { name: '加白户', sheet_name: '加白户表', columns: { 时区: 'consumption' } },
    { name: '企业户', sheet_name: '企业户表', columns: {} }]
  assert.deepEqual(flattenColumns('fb', tables),
    [{ name: '加白户', sheet_name: '加白户表', columns: { 时区: 'consumption' } },
     { name: '企业户', sheet_name: '企业户表' }])
})

test('fb：折回时过滤掉没填工作表名的空行', () => {
  const tables = [
    { name: '加白户', sheet_name: '加白户表', columns: {} },
    { name: '', sheet_name: '', columns: {} }]
  assert.deepEqual(flattenColumns('fb', tables),
    [{ name: '加白户', sheet_name: '加白户表' }])
})

test('tt：行为不变（逐项复制 + 折回仍是 tables）', () => {
  const src = [{ name: '加白户', sheet_name: 'S1', columns: { 日期: 'acquired_date' } }]
  assert.deepEqual(seedTables({ tables: src }, 'tt'),
    [{ name: '加白户', sheet_name: 'S1', columns: { 日期: 'acquired_date' } }])
})
