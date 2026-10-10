// 运行方式：cd frontend && npm test（= node --test tests/，覆盖本目录下所有 *.test.*）
import test from 'node:test'
import assert from 'node:assert/strict'
import { DEFAULT_PREVIEW_LIMIT, slicePreview, groupWarnings, selectedIds } from '../src/utils/previewRows.mjs'

// ===== slicePreview：只渲染前 N 行 =====

test('slicePreview: 少于 limit ⇒ 全出、hiddenCount=0', () => {
  const r = slicePreview([1, 2, 3], 10)
  assert.deepEqual(r.shown, [1, 2, 3])
  assert.equal(r.hiddenCount, 0)
  assert.equal(r.total, 3)
})

test('slicePreview: 等于 limit ⇒ hiddenCount=0', () => {
  const r = slicePreview([1, 2, 3], 3)
  assert.equal(r.shown.length, 3)
  assert.equal(r.hiddenCount, 0)
  assert.equal(r.total, 3)
})

test('slicePreview: 多于 limit ⇒ shown.length === limit、hiddenCount === 总数-limit、total 正确', () => {
  const items = Array.from({ length: 15035 }, (_, i) => i)
  const r = slicePreview(items, DEFAULT_PREVIEW_LIMIT)
  assert.equal(r.shown.length, DEFAULT_PREVIEW_LIMIT)
  assert.equal(r.hiddenCount, 15035 - DEFAULT_PREVIEW_LIMIT)
  assert.equal(r.total, 15035)
  // 必须是**前** limit 行（顺序不乱）
  assert.equal(r.shown[0], 0)
  assert.equal(r.shown[DEFAULT_PREVIEW_LIMIT - 1], DEFAULT_PREVIEW_LIMIT - 1)
})

test('slicePreview: 非数组 / undefined ⇒ 空结果', () => {
  for (const bad of [undefined, null, 'x', 42, {}]) {
    assert.deepEqual(slicePreview(bad, 5), { shown: [], hiddenCount: 0, total: 0 })
  }
})

test('slicePreview: limit <= 0 ⇒ shown 为空但 hiddenCount === 总数', () => {
  for (const lim of [0, -1, -100]) {
    const r = slicePreview([1, 2, 3, 4], lim)
    assert.deepEqual(r.shown, [])
    assert.equal(r.hiddenCount, 4)
    assert.equal(r.total, 4)
  }
})

test('slicePreview: 不修改入参', () => {
  const items = [1, 2, 3, 4, 5]
  slicePreview(items, 2)
  assert.equal(items.length, 5)
  assert.deepEqual(items, [1, 2, 3, 4, 5])
})

// ===== groupWarnings：上千条重复警告压成可读的几条 =====

test('groupWarnings: 空数组 / 非数组 ⇒ []', () => {
  assert.deepEqual(groupWarnings([]), [])
  for (const bad of [undefined, null, 'x', 42, {}]) {
    assert.deepEqual(groupWarnings(bad), [])
  }
})

test('groupWarnings: 两条完全相同 ⇒ 一条、count=2、sampleRow 是第一条的 row', () => {
  const out = groupWarnings([
    { row: 3, message: '运营「张三」无法识别，已跳过归属变更' },
    { row: 7, message: '运营「张三」无法识别，已跳过归属变更' },
  ])
  assert.equal(out.length, 1)
  assert.equal(out[0].count, 2)
  assert.equal(out[0].sampleRow, 3)
})

test('groupWarnings: 同模板不同值（张三/李四）⇒ 两条，且都 count=1', () => {
  const out = groupWarnings([
    { row: 1, message: '运营「张三」无法识别，已跳过归属变更' },
    { row: 2, message: '运营「李四」无法识别，已跳过归属变更' },
  ])
  assert.equal(out.length, 2)
  assert.deepEqual(out.map((g) => g.count), [1, 1])
  // 值不同 ⇒ 分组不同，两组的 label 各自保留真实姓名
  assert.deepEqual(out.map((g) => g.label).sort(),
    ['运营「张三」无法识别，已跳过归属变更', '运营「李四」无法识别，已跳过归属变更'].sort())
})

test('groupWarnings: 无变量的文案 ⇒ 相同原文归一组', () => {
  const out = groupWarnings([
    { row: 1, message: '账户ID为空，跳过' },
    { row: 2, message: '账户ID为空，跳过' },
    { row: 3, message: '账户ID为空，跳过' },
  ])
  assert.equal(out.length, 1)
  assert.equal(out[0].count, 3)
  assert.equal(out[0].label, '账户ID为空，跳过')
})

test('groupWarnings: 排序按 count 降序', () => {
  const out = groupWarnings([
    { row: 1, message: '少量A' },
    { row: 2, message: '大量B' },
    { row: 3, message: '大量B' },
    { row: 4, message: '大量B' },
    { row: 5, message: '中等C' },
    { row: 6, message: '中等C' },
  ])
  assert.deepEqual(out.map((g) => g.label), ['大量B', '中等C', '少量A'])
  assert.deepEqual(out.map((g) => g.count), [3, 2, 1])
})

test('groupWarnings: rows 是该组原始条目、label 保留真实值', () => {
  const a = { row: 3, message: '运营「张三」无法识别，已跳过归属变更' }
  const b = { row: 9, message: '运营「张三」无法识别，已跳过归属变更' }
  const out = groupWarnings([a, b])
  assert.equal(out.length, 1)
  assert.equal(out[0].label, '运营「张三」无法识别，已跳过归属变更')
  assert.equal(out[0].rows.length, 2)
  assert.equal(out[0].rows[0], a)
  assert.equal(out[0].rows[1], b)
  assert.ok(out[0].label.includes('张三'), 'label 必须保留真实值')
})

test('groupWarnings: 不修改入参', () => {
  const warnings = [
    { row: 1, message: '运营「张三」无法识别，已跳过归属变更' },
    { row: 2, message: '运营「张三」无法识别，已跳过归属变更' },
  ]
  const copy = JSON.parse(JSON.stringify(warnings))
  groupWarnings(warnings)
  assert.deepEqual(warnings, copy)
})

// ===== selectedIds：全量 − 排除集 =====

test('selectedIds: excludedIds 空 ⇒ 返回全部', () => {
  assert.deepEqual(selectedIds(['a', 'b', 'c'], null), ['a', 'b', 'c'])
  assert.deepEqual(selectedIds(['a', 'b', 'c'], undefined), ['a', 'b', 'c'])
  assert.deepEqual(selectedIds(['a', 'b', 'c'], []), ['a', 'b', 'c'])
  assert.deepEqual(selectedIds(['a', 'b', 'c'], new Set()), ['a', 'b', 'c'])
})

test('selectedIds: 排除一个 ⇒ 结果少一个', () => {
  const all = ['a', 'b', 'c']
  assert.deepEqual(selectedIds(all, ['b']), ['a', 'c'])
  assert.deepEqual(selectedIds(all, new Set(['b'])), ['a', 'c'])
  // 顺序与 allIds 一致
  assert.deepEqual(selectedIds(all, new Set(['a'])), ['b', 'c'])
})

test('selectedIds: 排除集里有不存在的 id ⇒ 不影响', () => {
  assert.deepEqual(selectedIds(['a', 'b'], ['zzz', 'b']), ['a'])
})

test('selectedIds: allIds 空 ⇒ []', () => {
  assert.deepEqual(selectedIds([], ['a']), [])
  for (const bad of [undefined, null, 'x', {}]) {
    assert.deepEqual(selectedIds(bad, ['a']), [])
  }
})

test('selectedIds: 不修改入参', () => {
  const all = ['a', 'b', 'c']
  const ex = ['b']
  selectedIds(all, ex)
  assert.deepEqual(all, ['a', 'b', 'c'])
  assert.deepEqual(ex, ['b'])
})
