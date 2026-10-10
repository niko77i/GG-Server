// 纯逻辑用例。运行：cd frontend && npm test
// 背景：整页刷新后可切换平台的角色（户管/开发者）会静默掉回 GG —— 本文件钉住修好后的判据。
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  PLATFORMS, PLATFORM_KEY, sanitizePlatform, platformOnHydrate,
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

test('platformOnHydrate：可切换角色用存下来的平台（刷新不改平台）', () => {
  assert.equal(platformOnHydrate({ stored: 'tt', canSwitch: true, userPlatform: 'gg' }), 'tt')
  assert.equal(platformOnHydrate({ stored: 'fb', canSwitch: true, userPlatform: 'gg' }), 'fb')
})

test('platformOnHydrate：可切换角色存储为空 / 脏值时回落 gg', () => {
  assert.equal(platformOnHydrate({ stored: null, canSwitch: true, userPlatform: 'tt' }), 'gg',
    '存储缺失时回落 gg —— 而不是拿 user.platform 顶替（那是另一套口径）')
  assert.equal(platformOnHydrate({ stored: '  ', canSwitch: true, userPlatform: 'tt' }), 'gg')
})

test('platformOnHydrate：不可切换的角色无视存储，以 user.platform 为准', () => {
  assert.equal(platformOnHydrate({ stored: 'tt', canSwitch: false, userPlatform: 'gg' }), 'gg',
    '同一浏览器换号时，存储里可能留着上一个人的平台')
  assert.equal(platformOnHydrate({ stored: null, canSwitch: false, userPlatform: 'fb' }), 'fb')
  assert.equal(platformOnHydrate({ stored: 'tt', canSwitch: false, userPlatform: null }), 'gg')
})

test('PLATFORM_KEY 是固定字符串（store 与测试共用，改名要一起改）', () => {
  assert.equal(PLATFORM_KEY, 'currentPlatform')
})
