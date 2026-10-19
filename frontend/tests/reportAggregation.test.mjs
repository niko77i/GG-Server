// 纯逻辑用例。运行：cd frontend && npm test
// 数据管理页「按可见维度列自动聚合 + 父子列联动」—— 设计见
// docs/superpowers/specs/2026-10-19-data-manage-auto-aggregation-design.md
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  visibleDimensions, isAggregating, childDisabled, applyLinkage, normalizePrefs,
} from '../src/utils/reportAggregation.mjs'

// FB 的列结构（维度 5 个、数值 6 个；产品名 → 线名）
const FB = {
  columns: [
    { prop: 'report_date', role: 'dimension' },
    { prop: 'product_name', role: 'dimension' },
    { prop: 'line_name', role: 'dimension' },
    { prop: 'account_name', role: 'dimension' },
    { prop: 'account_id', role: 'dimension' },
    { prop: 'cost', role: 'metric' },
    { prop: 'impressions', role: 'metric' },
  ],
  defaultVisible: ['report_date', 'product_name', 'line_name',
                   'account_name', 'account_id', 'cost'],
  links: [{ parent: 'product_name', child: 'line_name' }],
}

const ALL_DIMS = ['report_date', 'product_name', 'line_name', 'account_name', 'account_id']

// ---------- 聚合判定 ----------

test('全部维度可见 ⇒ 不聚合', () => {
  assert.equal(isAggregating([...ALL_DIMS, 'cost'], FB), false)
})

test('隐藏任一维度 ⇒ 聚合', () => {
  const visible = ALL_DIMS.filter(p => p !== 'line_name')
  assert.equal(isAggregating([...visible, 'cost'], FB), true)
})

test('只留日期+账户 ⇒ 聚合（用户场景）', () => {
  assert.equal(isAggregating(['report_date', 'account_id', 'cost'], FB), true)
})

test('用户点了「放弃聚合」⇒ 即使隐藏了维度也不聚合', () => {
  assert.equal(isAggregating(['report_date', 'cost'], FB, true), false)
})

test('只隐藏数值列不触发聚合（维度仍齐全）', () => {
  assert.equal(isAggregating([...ALL_DIMS], FB), false)
})

// ---------- 可见维度 ----------

test('visibleDimensions 只返回可见的维度、并保持声明顺序', () => {
  assert.deepEqual(
    visibleDimensions(['cost', 'account_id', 'report_date'], FB),
    ['report_date', 'account_id'])
})

// ---------- 父子联动 ----------

test('勾产品名 ⇒ 自动带上线名', () => {
  assert.deepEqual(
    applyLinkage(['report_date'], 'product_name', true, FB),
    ['report_date', 'product_name', 'line_name'])
})

test('取消产品名 ⇒ 线名一起取消', () => {
  assert.deepEqual(
    applyLinkage(['report_date', 'product_name', 'line_name'], 'product_name', false, FB),
    ['report_date'])
})

test('勾线名 ⇒ 父列必须在（兜底）', () => {
  assert.deepEqual(
    applyLinkage(['report_date'], 'line_name', true, FB),
    ['report_date', 'product_name', 'line_name'])
})

test('取消线名不影响产品名', () => {
  assert.deepEqual(
    applyLinkage(['product_name', 'line_name'], 'line_name', false, FB),
    ['product_name'])
})

test('结果始终按声明顺序，与勾选次序无关', () => {
  const seq = applyLinkage(['cost'], 'account_id', true, FB)
  assert.deepEqual(seq, ['account_id', 'cost'])
})

test('子列在父列未勾选时 disabled；父列已勾选时可用', () => {
  assert.equal(childDisabled('line_name', ['report_date'], FB), true)
  assert.equal(childDisabled('line_name', ['product_name'], FB), false)
  assert.equal(childDisabled('product_name', [], FB), false) // 非子列永不禁用
})

// ---------- 偏好归一化 ----------

test('归一化：含子列不含父列 ⇒ 补上父列', () => {
  assert.deepEqual(
    normalizePrefs(['report_date', 'line_name'], FB),
    ['report_date', 'product_name', 'line_name'])
})

test('归一化：过滤已不存在的列', () => {
  assert.deepEqual(normalizePrefs(['report_date', 'gone_col'], FB), ['report_date'])
})

test('归一化：读到空数组/坏数据 ⇒ 回落默认可见列', () => {
  assert.deepEqual(normalizePrefs([], FB), FB.defaultVisible)
  assert.deepEqual(normalizePrefs(null, FB), FB.defaultVisible)
  assert.deepEqual(normalizePrefs(['gone_col'], FB), FB.defaultVisible)
})
