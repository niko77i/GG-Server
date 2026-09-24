/**
 * 「户归属」列 composable —— 账户面板（GG / TT）共用。
 *
 * 拥有：下拉数据源（全量用户）、水合感知的惰性加载、逐行改归属的乐观更新 + 回滚 + 反馈。
 * **不**拥有：单元格模板与 CSS —— 两者留在各面板，因为 aria-label 的标识符字段按平台不同
 * （GG 用 `row.account_id`、TT 用 `row.advertiser_id`）。
 *
 * 视觉规格：docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md §5
 * 用法：const { ownerOptions, ..., changeOwner } = useOwnerPicker((id, body) => store.reassignAccount(id, body))
 *
 * @param {(id: number|string, body: {owner_id: number|string}) => Promise<any>} reassign 改归属的提交函数
 */
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { huguanApi } from '@/api/huguan'

export function useOwnerPicker(reassign) {
  const authStore = useAuthStore()

  const ownerOptions = ref([])           // 下拉数据源：全量用户（**编辑**用途）
  const ownerOptionsLoaded = ref(false)  // 请求是否已落定（成功或失败）；落定后不再显示骨架
  const ownerOptionsFailed = ref(false)  // 请求失败：该列所有下拉禁用并提示（§5.6，写操作不许静默失败）
  const ownerPending = ref(new Set())    // 正在提交的行 id，防重入（§5.5）
  const ownerOptionMap = computed(() => Object.fromEntries(ownerOptions.value.map(u => [u.id, u])))

  // 身份由 App.vue 根组件的 onMounted 调 initFromStorage 水合，而子组件 setup/mounted 恒早于
  // 父组件 onMounted，本 composable 若用 onMounted 拉数据，那一刻 authStore.user 仍是 null，
  // isHuguan 为 false，请求不会发出且永不重试 —— 硬刷新（F5）/ 直接进 URL 时这一列会永久停在
  // el-skeleton（户管的落地页正是本面板），且面板在 keep-alive 内，来回切页也不会再跑 onMounted。
  // 故这里在 setup 阶段先幂等补一次水合，再用 watch 盯 user.id 触发首次加载（§7 行 13）。
  // 同类教训与写法见 components/OwnerFilterSelect.vue:22-39。
  if (!authStore.user) authStore.initFromStorage()

  watch(
    () => authStore.user?.id,
    (uid) => { if (uid) loadOwnerOptions() },
    { immediate: true }
  )

  // 数据源必须是户管专用的 owner-options，**不是** /platform/users：后者是给上方「归属人」
  // 筛选器用的，只列**该平台有未删除账户**的用户（那是筛选场景的有意设计，见
  // docs/superpowers/specs/2026-09-23-owner-filter-hide-empty-users-design.md）。拿它当改归属
  // 的选项源，户管就没法把 GG 的户转给一个只在 TT 有户的合法用户（实测缺口）。
  // 依据：docs/superpowers/specs/2026-09-24-huguan-owner-source-and-picker-design.md §2.4
  async function loadOwnerOptions() {
    // 非户管一个请求也不发（§5.6）。这道守卫必须留在 loader 内部：watch 由 user.id 触发，
    // 而 user.id 对任何角色都会有值。
    if (!authStore.isHuguan) return
    try {
      const res = await huguanApi.ownerOptions()
      ownerOptions.value = res.users || []
    } catch (e) {
      ownerOptionsFailed.value = true
      // 这一列是**写**操作，静默失败会让户管以为改成功了（§5.6）
      ElMessage.warning('用户列表加载失败，暂时无法修改户归属。')
    } finally {
      ownerOptionsLoaded.value = true
    }
  }

  // 变更归属：乐观更新 + 提交期间锁住该格（§5.5）。
  // 「锁定」是必要的，不是保险：连续两次快速改动时 prev 会取到上一次乐观更新的值，
  // 第二次失败就会回滚出一个假值；:disabled 从交互层堵住这条路径。
  async function changeOwner(row, newOwnerId) {
    const prev = row.owner_id
    ownerPending.value.add(row.id)
    row.owner_id = newOwnerId
    try {
      await reassign(row.id, { owner_id: newOwnerId })
      const t = ownerOptions.value.find(u => u.id === newOwnerId)
      const who = (t && (t.display_name || t.username)) || `用户 #${newOwnerId}`
      // 成功提示只说「归属变了」（§5.5 短版）：端点不返回「是否回写了看板」，多说的那句
      // 在未配置看板时是假话，而「改这里之后去哪儿了」已由列头 tooltip 承接。
      ElMessage.success(`归属已变更为「${who}」`)
    } catch (e) {
      row.owner_id = prev
      ElMessage.error(e?.response?.data?.error || '归属变更失败，已还原')
    } finally {
      ownerPending.value.delete(row.id)
    }
  }

  return {
    ownerOptions,
    ownerOptionsLoaded,
    ownerOptionsFailed,
    ownerPending,
    ownerOptionMap,
    loadOwnerOptions,
    changeOwner
  }
}
