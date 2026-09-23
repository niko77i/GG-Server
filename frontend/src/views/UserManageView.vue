<template>
  <div class="user-manage">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
      <div>
        <h3 style="margin:0;font-size:18px;font-weight:600;color:#111827;">用户管理</h3>
        <!-- 户管专属说明行：承载「只能操作自己创建的」这条不可见规则（设计文档 §3.1） -->
        <div v-if="authStore.isHuguan" style="font-size:13px;color:#6b7280;margin-top:4px;">仅可管理你创建的户管账号</div>
      </div>
      <el-button @click="$router.push('/profile')">👤 个人信息</el-button>
    </div>

    <!-- 平台切换 Tab — 非开发者只显示自己平台的 Tab；户管列表跨平台，无平台维度可筛，整体隐藏 -->
    <el-tabs v-if="!authStore.isHuguan" v-model="platformFilter" @tab-change="onPlatformChange" style="margin-bottom:8px;">
      <el-tab-pane v-if="authStore.isDeveloper" label="全部" name="" />
      <el-tab-pane v-if="authStore.isDeveloper || authStore.effectivePlatform === 'gg'" label="GG" name="gg" />
      <el-tab-pane v-if="authStore.isDeveloper || authStore.effectivePlatform === 'fb'" label="FB" name="fb" />
      <el-tab-pane v-if="authStore.isDeveloper || authStore.effectivePlatform === 'tt'" label="TT" name="tt" />
    </el-tabs>
    <el-card shadow="never" style="margin-bottom:16px;">
      <el-row :gutter="12" align="middle">
        <el-col :span="8">
          <el-input v-model="search" placeholder="搜索用户名或显示名" clearable @input="handleSearch" />
        </el-col>
        <el-col :span="4">
          <span style="font-size:13px;color:#6b7280;">共 {{ total }} 个用户</span>
        </el-col>
      </el-row>
    </el-card>
    <div style="margin-bottom:12px;">
      <el-button type="primary" @click="openCreateDialog">{{ authStore.isHuguan ? '+ 创建户管' : '+ 创建用户' }}</el-button>
    </div>

    <el-table :data="users" stripe style="width:100%" v-loading="loading" height="calc(100vh - 220px)">
      <!-- 户管空状态：替换默认「暂无数据」，给出其唯一职责的入口（设计文档 §3.1）；非户管不提供该插槽 -->
      <template v-if="authStore.isHuguan" #empty>
        <div style="padding:24px 0 12px;color:#6b7280;">你还没有创建任何户管账号</div>
        <el-button type="primary" @click="openCreateDialog">创建户管</el-button>
      </template>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="username" label="用户名" width="150" />
      <el-table-column prop="display_name" label="显示名" width="150" />
      <el-table-column label="角色" width="120">
        <template #default="{ row }">
          <el-tag :type="roleType(row.role)" size="small">{{ roleLabel(row.role) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="平台" width="70">
        <template #default="{ row }">
          <el-tag :type="row.platform === 'fb' ? 'primary' : row.platform === 'tt' ? 'warning' : 'success'" size="small">
            {{ row.platform === 'fb' ? 'FB' : row.platform === 'tt' ? 'TT' : 'GG' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="160" />
      <el-table-column prop="last_login" label="最后登录" width="160" />
      <el-table-column label="操作" width="360" fixed="right">
        <template #default="{ row }">
          <el-button v-if="!authStore.isHuguan" size="small" @click="showImportDialog(row)">📥 导入数据</el-button>
          <template v-if="canModify(row)">
            <el-button size="small" @click="showEditDialog(row)">✏️ 编辑</el-button>
            <el-button size="small" @click="showPwdDialog(row)">🔑 改密</el-button>
            <el-dropdown trigger="click" @command="(v) => handleRoleChange(row.id, v)">
              <el-button size="small" link>切换角色</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <template v-if="authStore.isHuguan">
                    <el-dropdown-item command="huguan" :disabled="row.role === 'huguan'">户管</el-dropdown-item>
                    <el-dropdown-item command="hidden" :disabled="row.role === 'hidden'">禁用</el-dropdown-item>
                  </template>
                  <template v-else>
                    <el-dropdown-item command="user" :disabled="row.role === 'user'">普通用户</el-dropdown-item>
                    <el-dropdown-item command="viewer" :disabled="row.role === 'viewer'">观察者</el-dropdown-item>
                    <el-dropdown-item command="admin" :disabled="row.role === 'admin'">管理员</el-dropdown-item>
                    <el-dropdown-item v-if="authStore.isDeveloper" command="huguan" :disabled="row.role === 'huguan'">户管</el-dropdown-item>
                    <el-dropdown-item command="hidden" :disabled="row.role === 'hidden'">禁用</el-dropdown-item>
                  </template>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-popconfirm title="确定删除该用户？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button size="small" link type="danger" style="margin-left:8px;">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
          <el-tooltip v-if="!canModify(row)" :content="'不能操作' + (row.role === 'developer' ? '开发者' : (authStore.isHuguan ? '其他户管（只能操作自己创建的）' : '同级管理员'))" placement="top">
            <span style="color:#999;font-size:12px;margin-left:4px;">🔒</span>
          </el-tooltip>
        </template>
      </el-table-column>
    </el-table>
    <div style="display:flex;justify-content:center;padding:16px 0;">
      <el-pagination v-if="total > pageSize" background layout="prev,pager,next" :total="total" :page-size="pageSize" :current-page="currentPage" @current-change="handlePageChange" />
    </div>

    <!-- 创建用户弹窗 -->
    <el-dialog v-model="showCreateDialog" :title="authStore.isHuguan ? '创建户管' : '创建用户'" width="400px">
      <el-form :model="createForm" label-width="80px" size="small">
        <el-form-item label="用户名">
          <el-input v-model="createForm.username" placeholder="4-20个字符" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="createForm.password" type="password" placeholder="至少6位" show-password />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="createForm.display_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="createForm.role" :disabled="authStore.isHuguan" style="width:100%">
            <!-- 户管只能创建户管（后端 ALLOWED_CREATE_ROLES 同口径）：只给一个选项，不暗示还有其它可选范围 -->
            <template v-if="authStore.isHuguan">
              <el-option label="户管" value="huguan" />
            </template>
            <template v-else>
              <el-option label="普通用户" value="user" />
              <el-option label="观察者" value="viewer" />
              <el-option label="管理员" value="admin" />
              <el-option v-if="authStore.isDeveloper" label="户管" value="huguan" />
            </template>
          </el-select>
        </el-form-item>
        <el-form-item v-if="authStore.isDeveloper" label="平台">
          <el-select v-model="createForm.platform" style="width:100%">
            <el-option label="GG (Google Ads)" value="gg" />
            <el-option label="FB (Facebook)" value="fb" />
            <el-option label="TT (TikTok)" value="tt" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 编辑用户弹窗 -->
    <el-dialog v-model="editDialogVisible" title="编辑用户" width="400px">
      <el-form :model="editForm" label-width="80px" size="small">
        <el-form-item label="用户名">
          <el-input v-model="editForm.username" placeholder="4-20个字符" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="editForm.display_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="Telegram">
          <el-input v-model="editForm.telegram_username" placeholder="用户名（不带 @）" />
        </el-form-item>
        <el-form-item v-if="authStore.isDeveloper" label="平台">
          <el-select v-model="editForm.platform" style="width:100%">
            <el-option label="GG (Google Ads)" value="gg" />
            <el-option label="FB (Facebook)" value="fb" />
            <el-option label="TT (TikTok)" value="tt" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="handleEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 改密弹窗 -->
    <el-dialog v-model="pwdDialogVisible" title="重置密码" width="400px">
      <el-form :model="pwdForm" label-width="80px" size="small">
        <el-form-item label="用户">
          <span>{{ pwdTargetUser?.display_name || pwdTargetUser?.username }}</span>
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.password" type="password" placeholder="至少6位" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="handleResetPwd">确认</el-button>
      </template>
    </el-dialog>

    <!-- 导入数据弹窗 -->
    <el-dialog v-model="importDialogVisible" title="导入数据" width="400px">
      <p>为 <b>{{ importTargetUser?.display_name || importTargetUser?.username }}</b> 导入数据</p>
      <el-upload
        :auto-upload="false"
        :on-change="onAdminFileChange"
        :limit="1"
        accept=".db,.json"
        drag
      >
        <el-icon><UploadFilled /></el-icon>
        <div>拖拽或点击上传 .db / .json 文件</div>
      </el-upload>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="adminConfirmImport" :loading="adminImporting" :disabled="!adminImportFile">
          确认导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { adminApi } from '../api/admin'
import { adminDataApi } from '@/api/data'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'

const authStore = useAuthStore()

const users = ref([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
// 平台筛选：developer 默认「全部」(空)，非开发者锁定自己平台。
// 注意：不能在 ref 初始值里读 authStore —— App.vue 的 initFromStorage/fetchMe 在
// 父组件 onMounted 才执行（晚于本组件），此刻 user 必为 null，会把身份错判成「非开发者/gg」。
// 故初始留空，等身份就绪后由下方 watch 同步。
const platformFilter = ref('')

function isSelf(uid) {
  return authStore.user?.id === uid
}

function canModify(row) {
  if (isSelf(row.id)) return false
  if (authStore.isDeveloper) return true
  // 户管只能操作自己创建的户管（与后端 _check_modify_user 同口径）
  if (authStore.isHuguan) {
    return row.role === 'huguan' && row.created_by === authStore.user?.id
  }
  // 管理员只能操作普通用户、观察者和已禁用用户，不能操作其他管理员
  return ['user', 'viewer', 'hidden'].includes(row.role)
}

function roleType(role) {
  const m = { developer: 'danger', admin: 'warning', viewer: '', user: 'success', hidden: 'info', huguan: 'primary' }
  return m[role] || 'info'
}
function roleLabel(role) {
  const m = { developer: '开发者', admin: '管理员', viewer: '观察者', user: '用户', hidden: '已禁用', huguan: '户管' }
  return m[role] || role
}

async function fetchUsers() {
  loading.value = true
  try {
    const res = await adminApi.listUsers({ search: search.value, page: currentPage.value, page_size: pageSize.value, platform: platformFilter.value || undefined })
    users.value = res.users
    total.value = res.total
  } catch (e) {
    ElMessage.error('加载用户列表失败')
  } finally {
    loading.value = false
  }
}

let searchTimer = null
function handleSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { currentPage.value = 1; fetchUsers() }, 300)
}
function handlePageChange(page) {
  currentPage.value = page
  fetchUsers()
}
function onPlatformChange() {
  currentPage.value = 1
  fetchUsers()
}

async function handleRoleChange(uid, role) {
  if (isSelf(uid)) {
    ElMessage.warning('不能修改自己的角色')
    return
  }
  // 户管：禁用后该账号会从户管列表消失且自己无法切回（只有开发者能恢复），切换前明确告知
  if (authStore.isHuguan && role === 'hidden') {
    try {
      await ElMessageBox.confirm(
        '禁用后该账号将从你的户管列表中消失，你无法再把它切回户管。如需恢复请联系开发者。确定禁用？',
        '确认禁用户管',
        { type: 'warning', confirmButtonText: '确定禁用', cancelButtonText: '取消' }
      )
    } catch {
      return
    }
  }
  try {
    await adminApi.updateRole(uid, role)
    ElMessage.success('角色已更新')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '操作失败')
  }
}

async function handleDelete(uid) {
  if (isSelf(uid)) {
    ElMessage.warning('不能删除自己')
    return
  }
  try {
    await adminApi.deleteUser(uid)
    ElMessage.success('用户已删除')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '删除失败')
  }
}

// 身份就绪后再定筛选值并拉数据（App.vue fetchMe 完成后 user 才有值）
watch(() => authStore.user?.id, (uid) => {
  if (!uid) return
  platformFilter.value = authStore.isDeveloper ? '' : authStore.effectivePlatform
  fetchUsers()
}, { immediate: true })

// ---- 创建用户 ----
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({
  username: "",
  password: "",
  display_name: "",
  role: authStore.isHuguan ? "huguan" : "user",
  platform: authStore.isDeveloper ? (platformFilter.value || 'gg') : authStore.effectivePlatform
})

// 打开创建弹窗时按当前身份重定默认角色与平台：户管只能建户管；非开发者锁定自己平台；
// developer 跟随当前 Tab（「全部」时默认 gg）。
// 必须在这里重算而不能只依赖 ref 初始值 —— 与上方 platformFilter 同理，本组件 setup 早于
// App.vue 的 initFromStorage/fetchMe，此刻 user 可能仍为 null，会把户管误判成普通用户。
function openCreateDialog() {
  if (authStore.isHuguan) createForm.value.role = 'huguan'
  createForm.value.platform = authStore.isDeveloper
    ? (platformFilter.value || 'gg')
    : authStore.effectivePlatform
  showCreateDialog.value = true
}

async function handleCreate() {
  if (!createForm.value.username || createForm.value.username.length < 4) {
    ElMessage.warning("用户名至少4个字符")
    return
  }
  if (!createForm.value.password || createForm.value.password.length < 6) {
    ElMessage.warning("密码至少6位")
    return
  }
  creating.value = true
  try {
    await adminApi.createUser(createForm.value)
    ElMessage.success("用户创建成功")
    showCreateDialog.value = false
    // role / platform 留待下次打开弹窗时由 openCreateDialog 按身份重算
    createForm.value = {
      username: "", password: "", display_name: "",
      role: authStore.isHuguan ? "huguan" : "user",
      platform: authStore.isDeveloper ? (platformFilter.value || 'gg') : authStore.effectivePlatform
    }
    fetchUsers()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || "创建失败")
  } finally {
    creating.value = false
  }
}

// ---- 编辑用户 ----
const editDialogVisible = ref(false)
const editing = ref(false)
const editTargetId = ref(null)
const editForm = ref({ username: "", display_name: "", telegram_username: "", platform: "gg" })

function showEditDialog(row) {
  editTargetId.value = row.id
  editForm.value = { username: row.username, display_name: row.display_name || "", telegram_username: row.telegram_username || "", platform: row.platform || "gg" }
  editDialogVisible.value = true
}

async function handleEdit() {
  if (!editForm.value.username || editForm.value.username.length < 4 || editForm.value.username.length > 20) {
    ElMessage.warning("用户名需 4-20 个字符")
    return
  }
  editing.value = true
  try {
    const updateData = { username: editForm.value.username, display_name: editForm.value.display_name }
    if (authStore.isDeveloper && editForm.value.platform !== undefined) updateData.platform = editForm.value.platform
    await adminApi.updateUser(editTargetId.value, updateData)
    await adminApi.updateUserTelegram(editTargetId.value, editForm.value.telegram_username)
    ElMessage.success("用户信息已更新")
    editDialogVisible.value = false
    fetchUsers()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || "更新失败")
  } finally {
    editing.value = false
  }
}

// ---- 改密 ----
const pwdDialogVisible = ref(false)
const resetting = ref(false)
const pwdTargetUser = ref(null)
const pwdForm = ref({ password: "" })

function showPwdDialog(row) {
  pwdTargetUser.value = row
  pwdForm.value.password = ""
  pwdDialogVisible.value = true
}

async function handleResetPwd() {
  if (!pwdForm.value.password || pwdForm.value.password.length < 6) {
    ElMessage.warning("密码至少6位")
    return
  }
  resetting.value = true
  try {
    await adminApi.resetPassword(pwdTargetUser.value.id, pwdForm.value.password)
    ElMessage.success("密码已重置")
    pwdDialogVisible.value = false
  } catch (e) {
    ElMessage.error(e.response?.data?.error || "重置失败")
  } finally {
    resetting.value = false
  }
}

// ---- 管理员导入 ----
const importDialogVisible = ref(false)
const importTargetUser = ref(null)
const adminImportFile = ref(null)
const adminImporting = ref(false)

function showImportDialog(user) {
  importTargetUser.value = user
  importDialogVisible.value = true
}

function onAdminFileChange(file) {
  adminImportFile.value = file.raw
}

async function adminConfirmImport() {
  if (!adminImportFile.value || !importTargetUser.value) return
  adminImporting.value = true
  try {
    await adminDataApi.importForUser(adminImportFile.value, importTargetUser.value.id)
    ElMessage.success('导入完成')
    importDialogVisible.value = false
    adminImportFile.value = null
  } catch (e) {
    ElMessage.error('导入失败: ' + (e.response?.data?.error || e.message))
  }
  adminImporting.value = false
}
</script>
