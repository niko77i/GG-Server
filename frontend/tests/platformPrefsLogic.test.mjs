// 纯逻辑用例。运行：cd frontend && npm test
// 背景：整页刷新后可切换平台的角色（户管/开发者）会静默掉回 GG —— 本文件钉住修好后的判据。
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  PLATFORMS, PLATFORM_KEY, sanitizePlatform, platformFromPath, resolvePlatform,
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

test('platformFromPath：平台族路径各有归属，gg 族（/accounts 等）算 gg', () => {
  assert.equal(platformFromPath('/tt/accounts'), 'tt')
  assert.equal(platformFromPath('/tt'), 'tt')
  assert.equal(platformFromPath('/fb/data-manage'), 'fb')
  assert.equal(platformFromPath('/accounts/ads'), 'gg')
  assert.equal(platformFromPath('/accounts/products'), 'gg')
})

test('platformFromPath：/admin/users 与空/根路径返回 null（路由"没有意见"）', () => {
  assert.equal(platformFromPath('/admin/users'), null,
    '用户管理页有自己的平台 Tab；按路径推会把它按成 gg，害得「全部」看不到其它平台')
  assert.equal(platformFromPath('/admin/users/123'), null)
  assert.equal(platformFromPath(''), null, '首帧路由未解析时不能凭空按 gg')
  assert.equal(platformFromPath('/'), null)
  assert.equal(platformFromPath(null), null)
})

test('resolvePlatform：可切换角色 路由 > 存储（刷新不掉平台）', () => {
  assert.equal(resolvePlatform({ stored: 'tt', routePath: '/tt/accounts', canSwitch: true, userPlatform: 'gg' }), 'tt')
  assert.equal(resolvePlatform({ stored: 'gg', routePath: '/fb/accounts', canSwitch: true, userPlatform: 'gg' }), 'fb',
    '路由压过存储 —— 切平台即导航，URL 才是你在看的那张')
})

test('resolvePlatform：可切换角色、路由没意见时用存储兜底；都没有则 gg', () => {
  assert.equal(resolvePlatform({ stored: 'tt', routePath: '/admin/users', canSwitch: true, userPlatform: 'gg' }), 'tt',
    '/admin/users 上不该把开发者的平台按成 gg')
  assert.equal(resolvePlatform({ stored: 'tt', routePath: '/', canSwitch: true, userPlatform: 'gg' }), 'tt')
  assert.equal(resolvePlatform({ stored: null, routePath: '', canSwitch: true, userPlatform: 'tt' }), 'gg',
    '两处都没有时回落 gg —— 不拿 user.platform 顶替（那是非切换角色的口径）')
  assert.equal(resolvePlatform({ stored: '  ', routePath: null, canSwitch: true, userPlatform: 'tt' }), 'gg')
})

test('resolvePlatform：不可切换的角色无视存储与路由，以 user.platform 为准', () => {
  assert.equal(resolvePlatform({ stored: 'tt', routePath: '/tt/accounts', canSwitch: false, userPlatform: 'gg' }), 'gg',
    '同一浏览器换号时，存储里可能留着上一个人的平台')
  assert.equal(resolvePlatform({ stored: null, routePath: '/tt/accounts', canSwitch: false, userPlatform: 'fb' }), 'fb')
  assert.equal(resolvePlatform({ stored: 'tt', routePath: '/tt/accounts', canSwitch: false, userPlatform: null }), 'gg')
})

test('PLATFORM_KEY 是固定字符串（store 与测试共用，改名要一起改）', () => {
  assert.equal(PLATFORM_KEY, 'currentPlatform')
})
