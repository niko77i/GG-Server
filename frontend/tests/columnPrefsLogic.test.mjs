// 纯逻辑用例。运行：cd frontend && npm test
// 用 Node 18 内置的 node --test，不引入任何依赖。
// 扩展名必须是 .mjs —— package.json 没有 "type": "module"，.js 会被当 CJS 解析。
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  registryKeys, indexByKey, resolveOrder, resolveVisible,
  applyToggle, applyMove, isOnlyVisible,
} from '../src/utils/columnPrefsLogic.mjs'

// 三列注册表：b 带角色闸门
const REG = [
  { key: 'a', label: 'A', minWidth: 100 },
  { key: 'b', label: 'B', width: 54, align: 'center', available: (auth) => auth.isHuguan },
  { key: 'c', label: 'C', minWidth: 120 },
]
// isAvailable 是谓词 (col) => boolean，接收注册表里的一项。三种口径：
const ALL = () => true                              // 谁都能看
const noGate = (col) => !col.available              // 只看不带闸门的列（模拟非户管的普通用户）
const gateOnly = (col) => Boolean(col.available)    // 只看带闸门的列（反向构造用）

test('registryKeys 返回数组声明顺序', () => {
  assert.deepEqual(registryKeys(REG), ['a', 'b', 'c'])
})

test('indexByKey 剔除 key 与 available，只留可 v-bind 的属性', () => {
  assert.deepEqual(indexByKey(REG), {
    a: { label: 'A', minWidth: 100 },
    b: { label: 'B', width: 54, align: 'center' },
    c: { label: 'C', minWidth: 120 },
  })
})

test('resolveOrder: 无配置时用注册表默认顺序', () => {
  assert.deepEqual(resolveOrder(null, REG, ALL), ['a', 'b', 'c'])
})

test('resolveOrder: 保留用户顺序（含隐藏列）', () => {
  const pref = { order: ['c', 'a', 'b'], hidden: ['a'] }
  assert.deepEqual(resolveOrder(pref, REG, ALL), ['c', 'a', 'b'])
})

test('resolveOrder: 剔除陈旧 key（列已从代码删除）', () => {
  const pref = { order: ['c', 'ghost', 'a', 'b'], hidden: [] }
  assert.deepEqual(resolveOrder(pref, REG, ALL), ['c', 'a', 'b'])
})

test('resolveOrder: 新列追加到末尾（这是「新列默认显示」策略的落点）', () => {
  const pref = { order: ['a', 'c'], hidden: [] }   // 用户配置里没有 b
  assert.deepEqual(resolveOrder(pref, REG, ALL), ['a', 'c', 'b'])
})

test('resolveOrder: 角色闸门过滤掉不可见的列', () => {
  const pref = { order: ['c', 'b', 'a'], hidden: [] }
  assert.deepEqual(resolveOrder(pref, REG, noGate), ['c', 'a'])
})

test('resolveVisible: 减去 hidden', () => {
  const pref = { order: ['c', 'a', 'b'], hidden: ['a'] }
  assert.deepEqual(resolveVisible(pref, REG, ALL), ['c', 'b'])
})

test('resolveVisible: 隐藏的列不会被新列策略弹回来（本设计自审抓出的缺陷）', () => {
  // 用户把 c 藏了。下次加载时 c 既在 order 里也在 hidden 里 —— 必须保持隐藏。
  const pref = { order: ['a', 'c'], hidden: ['c'] }
  assert.deepEqual(resolveVisible(pref, REG, ALL), ['a', 'b'])
})

test('applyToggle 隐藏：只往 hidden 加，order 原样不动', () => {
  const pref = { order: ['c', 'a', 'b'], hidden: [] }
  assert.deepEqual(applyToggle(pref, REG, ALL, 'a', false), {
    order: ['c', 'a', 'b'], hidden: ['a'],
  })
})

test('applyToggle 显示：从 hidden 移除，回到原位（不是末尾）', () => {
  const pref = { order: ['c', 'a', 'b'], hidden: ['a'] }
  assert.deepEqual(applyToggle(pref, REG, ALL, 'a', true), {
    order: ['c', 'a', 'b'], hidden: [],
  })
})

test('applyToggle 在无配置时也能工作', () => {
  assert.deepEqual(applyToggle(null, REG, ALL, 'b', false), {
    order: ['a', 'b', 'c'], hidden: ['b'],
  })
})

test('applyMove 把第 0 项移到第 2 位', () => {
  const pref = { order: ['a', 'b', 'c'], hidden: [] }
  assert.deepEqual(applyMove(pref, REG, ALL, 0, 2).order, ['b', 'c', 'a'])
})

test('applyMove 把第 2 项移到第 0 位', () => {
  const pref = { order: ['a', 'b', 'c'], hidden: [] }
  assert.deepEqual(applyMove(pref, REG, ALL, 2, 0).order, ['c', 'a', 'b'])
})

test('applyMove 不动 hidden', () => {
  const pref = { order: ['a', 'b', 'c'], hidden: ['b'] }
  assert.deepEqual(applyMove(pref, REG, ALL, 0, 2).hidden, ['b'])
})

test('applyMove 在无配置时以默认顺序为基准', () => {
  assert.deepEqual(applyMove(null, REG, ALL, 0, 1).order, ['b', 'a', 'c'])
})

test('applyMove 下标越界时原样返回，不抛异常', () => {
  const pref = { order: ['a', 'b', 'c'], hidden: [] }
  assert.deepEqual(applyMove(pref, REG, ALL, 0, 9).order, ['a', 'b', 'c'])
  assert.deepEqual(applyMove(pref, REG, ALL, -1, 0).order, ['a', 'b', 'c'])
})

test('isOnlyVisible: 还有别的可见列时返回 false', () => {
  const pref = { order: ['a', 'c'], hidden: ['c'] }   // 可见的是 a，加上新列的 b 共两列
  assert.equal(isOnlyVisible(pref, REG, ALL, 'a'), false)
})

test('isOnlyVisible: 只剩一列可见时返回 true', () => {
  // 非户管看不到带闸门的 b；c 被用户藏了 —— 可见的只剩 a
  const pref = { order: ['a', 'c'], hidden: ['c'] }
  assert.equal(isOnlyVisible(pref, REG, noGate, 'a'), true)
})

test('isOnlyVisible: 被角色闸门挡掉的列不算「可见」', () => {
  // 反向构造：只有带闸门的 b 可见，a 被挡掉且被用户藏了 —— 可见的只剩 b
  const pref = { order: ['a', 'b'], hidden: ['a'] }
  assert.equal(isOnlyVisible(pref, REG, gateOnly, 'b'), true)
})
