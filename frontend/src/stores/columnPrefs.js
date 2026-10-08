import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { columnPrefsApi } from '@/api/columnPrefs'
import {
  registryKeys, resolveOrder, resolveVisible, applyToggle, applyMove, isOnlyVisible,
} from '@/utils/columnPrefsLogic.mjs'
import { useAuthStore } from '@/stores/auth'

// 保存去抖窗口。拖一次会连发十几个变更，不防抖就是一串请求。
const SAVE_DEBOUNCE_MS = 400

export const useColumnPrefsStore = defineStore('columnPrefs', () => {
  const prefs = ref({})           // 服务端原始 JSON：{panel: {order, hidden}}
  const ready = ref(false)        // 首次拉取是否已落定（成功或失败都置 true）

  let loadPromise = null          // 启动预拉的单例，避免多个面板各拉一次
  const saveTimers = {}           // panelKey -> timer
  const saveGen = {}              // panelKey -> 代际号：每次本地变更 +1（见 scheduleSave）

  // 没有配置的面板用空 pref，纯函数会走注册表默认顺序
  function prefOf(panelKey) {
    return prefs.value?.[panelKey] ?? null
  }

  /**
   * 可见性谓词。**必须在这里把列自身的 `available` 闸门折算进来** ——
   * columnPrefsLogic 里的 `available()` 只做 `isAvailable(col)` 透传，
   * 不再兜底判断列的闸门（那种兜底会让严格谓词失效，见该模块的注释）。
   * 漏掉这里的 `!col.available ||` 会让「户归属」这类仅户管可见的列对所有人显示。
   */
  function isAvailable() {
    const auth = useAuthStore()
    return (col) => !col.available || col.available(auth)
  }

  function visibleOrder(panelKey, registry) {
    return resolveVisible(prefOf(panelKey), registry, isAvailable())
  }

  /** 设置弹层用：完整顺序（含隐藏列），每项带上 label 与 hidden 标记。 */
  function settingsList(panelKey, registry) {
    const order = resolveOrder(prefOf(panelKey), registry, isAvailable())
    const hidden = new Set(prefOf(panelKey)?.hidden ?? [])
    const byKey = Object.fromEntries(registry.map((c) => [c.key, c]))
    return order.map((key) => ({
      key,
      label: byKey[key]?.label ?? key,
      hidden: hidden.has(key),
    }))
  }

  // 服务端已确认的状态，回滚用
  let lastConfirmed = {}

  async function ensureLoaded() {
    if (ready.value) return
    if (loadPromise) return loadPromise
    loadPromise = (async () => {
      try {
        const resp = await columnPrefsApi.get()
        // 取 resp.prefs，**不是** resp.data.prefs —— client.js:34 的响应拦截器是
        // `return resp.data`，已经把响应体解包了；后端 ok({"prefs": ...}) 又把 dict
        // 平铺，所以这里 resp 就是 {success, prefs}。写成 resp.data?.prefs 会恒为
        // undefined，用户配置永远读不回来（功能整个失效，且静态检查抓不到）。
        prefs.value = resp.prefs ?? {}
        lastConfirmed = JSON.parse(JSON.stringify(prefs.value))
      } catch (e) {
        // 拉不到就退回默认列。**绝不能让 ready 停在 false** —— 面板的表格
        // 等 ready 才挂载，卡住就是整张表永远不显示，比列序不对严重得多。
        ElMessage.error('列配置加载失败，已使用默认列')
      } finally {
        ready.value = true
      }
    })()
    return loadPromise
  }

  function scheduleSave(panelKey, registry) {
    clearTimeout(saveTimers[panelKey])
    const gen = saveGen[panelKey] ?? 0     // 这次保存属于哪一代
    saveTimers[panelKey] = setTimeout(() => {
      const pref = prefOf(panelKey) ?? { order: registryKeys(registry), hidden: [] }
      columnPrefsApi.save(panelKey, pref.order, pref.hidden).then((resp) => {
        // **代际守卫**：只有在途期间该面板没有更新的本地改动（也没换过账号）时，
        // 才应用响应。少了这道守卫会静默丢改动：
        //   t=0   勾 A → 本地 {hidden:[A]}，排定 t=400 保存
        //   t=400 防抖到期，PUT 发出（内容 [A]）
        //   t=450 勾 B → 本地 {hidden:[A,B]}，排定 t=850 保存
        //   t=451 A 的响应回来 → 无条件回写会把 B 悄悄抹掉
        //   t=850 保存发出，内容是 [A] → B 在服务端也丢了
        // 窗口 = 防抖触发后一个往返。clear() 也会 bump 代际，
        // 于是上一个用户的在途响应回来时同样被丢弃（跨账号串写一并关闭）。
        if ((saveGen[panelKey] ?? 0) !== gen) return
        prefs.value = resp.prefs ?? prefs.value
        lastConfirmed = JSON.parse(JSON.stringify(prefs.value))
      }).catch(() => {
        // 同上：新一代已接管，别用陈旧快照去回滚它的状态
        if ((saveGen[panelKey] ?? 0) !== gen) return
        // 失败回滚到上次服务端确认的状态，不留「界面显示已保存、其实没存上」的假象
        ElMessage.error('列配置保存失败，已还原')
        prefs.value = JSON.parse(JSON.stringify(lastConfirmed))
      })
    }, SAVE_DEBOUNCE_MS)
  }

  function commit(panelKey, registry, next) {
    saveGen[panelKey] = (saveGen[panelKey] ?? 0) + 1
    prefs.value = { ...prefs.value, [panelKey]: next }
    scheduleSave(panelKey, registry)
  }

  function toggle(panelKey, registry, key, checked) {
    commit(panelKey, registry, applyToggle(prefOf(panelKey), registry, isAvailable(), key, checked))
  }

  function move(panelKey, registry, fromIndex, toIndex) {
    commit(panelKey, registry, applyMove(prefOf(panelKey), registry, isAvailable(), fromIndex, toIndex))
  }

  function reset(panelKey, registry) {
    commit(panelKey, registry, { order: registryKeys(registry), hidden: [] })
  }

  /** 取消勾选这一列会不会让表格一列数据都不剩（UI 据此禁用勾选框）。 */
  function onlyVisible(panelKey, registry, key) {
    return isOnlyVisible(prefOf(panelKey), registry, isAvailable(), key)
  }

  /**
   * 登出 / 换号时清空。
   *
   * 必须清四样，少一样都会串号：
   *   - prefs：否则 B 看到 A 的列
   *   - ready：否则 ensureLoaded 被 `if (ready.value) return` 挡住，B 永远不会重拉
   *   - loadPromise：否则 B 拿到的是 A 那次请求的 promise
   *   - 未落地的防抖定时器：**最隐蔽的一样**。A 改完列 400ms 内登出、B 立刻登录，
   *     那个定时器会带着 B 的新 token 把 A 的配置写进 B 的 key。
   *   - **代际号**：定时器只能取消「还没发出」的保存；**已经在途**的 PUT 取消不了，
   *     它的响应回来时若不带守卫就会把 A 的 prefs 写进已清空的 store。
   *     故这里 bump 所有已知面板的代际，让那些在途响应被丢弃。
   */
  function clear() {
    for (const key of Object.keys(saveTimers)) {
      clearTimeout(saveTimers[key])
      delete saveTimers[key]
    }
    for (const key of Object.keys(saveGen)) saveGen[key] = (saveGen[key] ?? 0) + 1
    prefs.value = {}
    lastConfirmed = {}
    ready.value = false
    loadPromise = null
  }

  return {
    prefs, ready,
    visibleOrder, settingsList, onlyVisible,
    toggle, move, reset, clear,
    ensureLoaded,
  }
})
