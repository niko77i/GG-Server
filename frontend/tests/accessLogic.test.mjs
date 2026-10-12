// 纯逻辑用例。运行：cd frontend && npm test
// 扩展名必须是 .mjs —— package.json 没有 "type": "module"，.js 会被当 CJS 解析。
//
// 背景（2026-10-12）：普通用户（role='user'）此前进不了「广告账户 / MCC 管理 / 设置」三页
// —— 挡住他们的是前端路由 meta.admin。现放开，但**不能**顺手放开 canManageAccounts：
// 那个 getter 是「跨用户管账户」开关（归属人下拉、批量导入逐行编辑、MCC 行内编辑按钮、
// FB 字典写入…共 20 处在用），放开等于把别人的数据也给了普通用户。
// 故把判据拆成三条独立的，本文件钉住它们的分工。
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  ACCOUNT_PAGE_ROLES, CROSS_USER_ACCOUNT_ROLES, GLOBAL_OPTION_ROLES,
  canAccessAccountPages, canEditGlobalOptions, canManageOthersAccounts,
} from '../src/utils/accessLogic.mjs'

const ALL_ROLES = ['developer', 'admin', 'huguan', 'user', 'viewer']

test('canAccessAccountPages：普通用户可进账户区三页（本需求的核心）', () => {
  assert.equal(canAccessAccountPages('user'), true)
  for (const r of ['developer', 'admin', 'huguan']) {
    assert.equal(canAccessAccountPages(r), true, `${r} 应可进账户区`)
  }
})

test('canAccessAccountPages：viewer 仍被挡在账户区外', () => {
  // viewer 只到 /accounts/products，router 守卫另有硬拦（第 215 行）。这里必须一致，
  // 否则 Tab 会渲染出来、点进去被弹回。
  assert.equal(canAccessAccountPages('viewer'), false)
})

test('canEditGlobalOptions：普通用户与 viewer 都不能改全局字典', () => {
  assert.equal(canEditGlobalOptions('user'), false)
  assert.equal(canEditGlobalOptions('viewer'), false)
  for (const r of ['developer', 'admin', 'huguan']) {
    assert.equal(canEditGlobalOptions(r), true, `${r} 应可改全局字典`)
  }
})

test('canManageOthersAccounts：普通用户与 viewer 都不能跨用户管账户', () => {
  // ⚠️ 这条**不许**因为「放开账户区」而放宽 —— MccPanel 的
  // `row.is_owner || canManageAccounts` 靠它决定要不要显示编辑别人的 MCC。
  assert.equal(canManageOthersAccounts('user'), false)
  assert.equal(canManageOthersAccounts('viewer'), false)
  for (const r of ['developer', 'admin', 'huguan']) {
    assert.equal(canManageOthersAccounts(r), true, `${r} 应可跨用户管账户`)
  }
})

test('核心不变式：能进页面 ≠ 能改全局配置（user 恰好在两条线的两侧）', () => {
  assert.ok(ACCOUNT_PAGE_ROLES.includes('user'), 'user 必须能进账户区')
  assert.ok(!GLOBAL_OPTION_ROLES.includes('user'), 'user 必须不能改全局字典')
  assert.ok(!CROSS_USER_ACCOUNT_ROLES.includes('user'), 'user 必须不能跨用户管账户')
})

test('核心不变式：viewer 三条全否', () => {
  assert.ok(!ACCOUNT_PAGE_ROLES.includes('viewer'))
  assert.ok(!GLOBAL_OPTION_ROLES.includes('viewer'))
  assert.ok(!CROSS_USER_ACCOUNT_ROLES.includes('viewer'))
})

test('未知 / 缺失角色一律为否（不 fail-open）', () => {
  for (const bad of [undefined, null, '', 'hidden', 'Developer', '超级管理员', 0, {}]) {
    assert.equal(canAccessAccountPages(bad), false, `${String(bad)} 不该进账户区`)
    assert.equal(canEditGlobalOptions(bad), false, `${String(bad)} 不该改全局字典`)
    assert.equal(canManageOthersAccounts(bad), false, `${String(bad)} 不该跨用户管账户`)
  }
})

test('三个常量本身：viewer 三档全排除，user 只在「能进账户区」那一档', () => {
  for (const list of [ACCOUNT_PAGE_ROLES, GLOBAL_OPTION_ROLES, CROSS_USER_ACCOUNT_ROLES]) {
    assert.ok(!list.includes('viewer'), 'viewer 不该出现在任何一档')
  }
  assert.ok(ACCOUNT_PAGE_ROLES.includes('user'), 'user 恰好在「能进账户区」这一档')
  assert.ok(!GLOBAL_OPTION_ROLES.includes('user'))
  assert.ok(!CROSS_USER_ACCOUNT_ROLES.includes('user'))
  // 跨用户管账户 ⊆ 改全局字典 ⊆ 能进账户区
  for (const r of CROSS_USER_ACCOUNT_ROLES) assert.ok(GLOBAL_OPTION_ROLES.includes(r), `${r}`)
  for (const r of GLOBAL_OPTION_ROLES) assert.ok(ACCOUNT_PAGE_ROLES.includes(r), `${r}`)
  // 只有 user 是「进得去、改不了」的那一档
  assert.deepEqual(
    ACCOUNT_PAGE_ROLES.filter(r => !GLOBAL_OPTION_ROLES.includes(r)), ['user'])
})

test('全角色穷举：三条判据的完整真值表', () => {
  const expected = {
    developer: [true, true, true],
    admin: [true, true, true],
    huguan: [true, true, true],
    user: [true, false, false],
    viewer: [false, false, false],
  }
  for (const r of ALL_ROLES) {
    assert.deepEqual(
      [canAccessAccountPages(r), canEditGlobalOptions(r), canManageOthersAccounts(r)],
      expected[r], r)
  }
})
