// 纯逻辑用例。运行：cd frontend && npm test
// 背景：整页刷新后可切换平台的角色（户管/开发者）会静默掉回 GG —— 本文件钉住修好后的判据。
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  PLATFORMS, PLATFORM_KEY, sanitizePlatform, platformFromPath, platformFamily,
  resolvePlatform,
} from '../src/utils/platformPrefs.mjs'

test('sanitizePlatform：合法平台原样返回', () => {
  for (const p of PLATFORMS) assert.equal(sanitizePlatform(p), p)
})

test('sanitizePlatform：非法 / 缺失 / 非字符串一律回落 gg', () => {
  assert.equal(sanitizePlatform('GG'), 'gg')      // 大小写不宽容：脏值不放过
  assert.equal(sanitizePlatform(''), 'gg')
  assert.equal(sanitizePlatform(null), 'gg')
  assert.equal(sanitizePlatform(undefined), 'gg')
  assert.equal(sanitizePlatform(0), 'gg')
  assert.equal(sanitizePlatform({ platform: 'tt' }), 'gg')
})

test('platformFromPath（请求层）：平台族各有归属，其余一律 gg（请求必须有默认值）', () => {
  assert.equal(platformFromPath('/tt/accounts'), 'tt')
  assert.equal(platformFromPath('/fb/data-manage'), 'fb')
  assert.equal(platformFromPath('/accounts/ads'), 'gg')
  assert.equal(platformFromPath('/profile'), 'gg', '请求层不区分中性页：带 gg 是刻意的默认')
  assert.equal(platformFromPath(''), 'gg')
  assert.equal(platformFromPath('/'), 'gg')
})

test('platformFromPath（请求层）：/admin/users 返回 null = 不带该参数', () => {
  assert.equal(platformFromPath('/admin/users'), null,
    '用户管理页有自己的平台 Tab；带 gg 会让「全部」看不到其它平台')
  assert.equal(platformFromPath('/admin/users/123'), null)
})

test('platformFamily（store 用）：只认路由声明的平台族，中性路由返回 null', () => {
  assert.equal(platformFamily('tt'), 'tt')
  assert.equal(platformFamily('gg'), 'gg')
  assert.equal(platformFamily('fb'), 'fb')
  // 下面这些正是「不能按成 gg」的中性路由（它们的 meta 没有 platform）：
  assert.equal(platformFamily(undefined), null, '/profile、/analysis、/toolkit/*、/admin/* 都属于这类')
  assert.equal(platformFamily(null), null)
  assert.equal(platformFamily(''), null)
  assert.equal(platformFamily('GG'), null, '大小写不宽容：脏 meta 不认')
  assert.equal(platformFamily({ platform: 'tt' }), null)
})

test('resolvePlatform：可切换角色用存储（刷新不改平台）', () => {
  assert.equal(resolvePlatform({ stored: 'tt', canSwitch: true, userPlatform: 'gg' }), 'tt')
  assert.equal(resolvePlatform({ stored: 'fb', canSwitch: true, userPlatform: 'gg' }), 'fb')
})

test('resolvePlatform：可切换角色存储缺失/脏值时回落 gg', () => {
  assert.equal(resolvePlatform({ stored: null, canSwitch: true, userPlatform: 'tt' }), 'gg',
    '不拿 user.platform 顶替 —— 那是非切换角色的口径')
  assert.equal(resolvePlatform({ stored: '  ', canSwitch: true, userPlatform: 'tt' }), 'gg')
})

test('resolvePlatform：不可切换的角色无视存储，以 user.platform 为准', () => {
  assert.equal(resolvePlatform({ stored: 'tt', canSwitch: false, userPlatform: 'gg' }), 'gg',
    '同一浏览器换号时，存储里可能留着上一个人的平台')
  assert.equal(resolvePlatform({ stored: null, canSwitch: false, userPlatform: 'fb' }), 'fb')
  assert.equal(resolvePlatform({ stored: 'tt', canSwitch: false, userPlatform: null }), 'gg')
})

test('PLATFORM_KEY 是固定字符串（store 与测试共用，改名要一起改）', () => {
  assert.equal(PLATFORM_KEY, 'currentPlatform')
})
