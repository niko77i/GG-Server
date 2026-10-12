// 角色 → 权限判据（纯函数，供 Pinia getter 与前端测试共用）。
// 扩展名是 .mjs 以便 `node --test` 直接 import（同 columnPrefsLogic / platformPrefs）。
//
// ⚠️ 这三条常量**镜像后端** py/routes/helpers.py 的同名常量。改这里必须同步改后端，
// 反之亦然；只改一侧的后果是「前端放出去了、后端 403」或反向的越权。
//
// 为什么拆成三条而不是一条（2026-10-12）：
//   原先只有 canManageAccounts（= 下面第三条），被当成了「privileged 角色」的万能判据 ——
//   账户区 Tab 可见性、MCC 行内编辑按钮、归属人下拉、批量导入逐行编辑、FB 字典写入
//   全用它。于是「放开普通用户的账户区」这个需求无法用同一条表达：放宽它，等于把
//   编辑**别人** MCC/账户的能力一并给了普通用户（MccPanel:34 的
//   `row.is_owner || canManageAccounts` 会立刻对所有人显示编辑按钮）。
//   故按「能进页面 / 能改全局配置 / 能管别人的数据」三档拆开，逐条独立演进。

/** 能进入账户区三页（广告账户 / MCC 管理 / 设置）。
 *  ⚠️ 刻意不含 viewer —— viewer 的账户区止步于 /accounts/products，
 *  router 守卫（frontend/src/router/index.js）另有硬拦。两处必须同口径：
 *  此处放行而路由拦下，会渲染出点了就被弹回的 Tab。 */
export const ACCOUNT_PAGE_ROLES = ['developer', 'admin', 'huguan', 'user']

/** 能改**全局共享**的字典表。
 *  ⚠️ 五张字典表里只有 **地区（regions）** 落在这条线上 —— 它是全平台共享、一改对所有人生效，
 *  故后端对写操作硬校验 `GLOBAL_OPTION_ROLES` 回 403。
 *  代理 / 账户状态 / MCC 等级 / 商务人员四张是 **owner 隔离**的（`_list` 按 `owner_id` 过滤、
 *  `create` 无闸门、改名删除限本人），普通用户本就能增删改**自己的**，故不设前端闸门。
 *  曾经把这条误当成「五张字典的写权限」而藏掉那四张卡片的写入口，结果是普通用户
 *  连自己的 MCC 等级都建不了 —— 详见 docs/.../2026-10-12-open-account-area-...md。
 *  此处只用于**隐藏前端写入口**，拦截的权威在后端。 */
export const GLOBAL_OPTION_ROLES = ['developer', 'admin', 'huguan']

/** 能跨用户管账户 / MCC（读改删**别人**的行、按归属人筛选、认领转移）。
 *  普通用户的账户操作仍按 owner_id 隔离，后端逐条校验归属。 */
export const CROSS_USER_ACCOUNT_ROLES = ['developer', 'admin', 'huguan']

export const canAccessAccountPages = (role) => ACCOUNT_PAGE_ROLES.includes(role)
export const canEditGlobalOptions = (role) => GLOBAL_OPTION_ROLES.includes(role)
export const canManageOthersAccounts = (role) => CROSS_USER_ACCOUNT_ROLES.includes(role)
