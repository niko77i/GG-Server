<template>
  <div class="user-manage">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
      <h3 style="margin:0;font-size:18px;font-weight:600;color:#111827;">用户管理</h3>
      <el-button @click="$router.push('/profile')">👤 个人信息</el-button>
    </div>

    <!-- 平台切换 Tab -->
    <el-tabs v-model="platformFilter" @tab-change="onPlatformChange" style="margin-bottom:8px;">
      <el-tab-pane label="全部" name="" />
      <el-tab-pane label="GG" name="gg" />
      <el-tab-pane label="FB" name="fb" />
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
      <el-button type="primary" @click="showCreateDialog = true">+ 创建用户</el-button>
    </div>

    <el-table :data="users" stripe style="width:100%" v-loading="loading" height="calc(100vh - 220px)">
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
          <el-tag :type="row.platform === 'fb' ? 'primary' : 'success'" size="small">
            {{ row.platform === 'fb' ? 'FB' : 'GG' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="160" />
      <el-table-column prop="last_login" label="最后登录" width="160" />
      <el-table-column label="操作" width="360" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="showImportDialog(row)">📥 导入数据</el-button>
          <template v-if="canModify(row)">
            <el-button size="small" @click="showEditDialog(row)">✏️ 编辑</el-button>
            <el-button size="small" @click="showPwdDialog(row)">🔑 改密</el-button>
            <el-dropdown trigger="click" @command="(v) => handleRoleChange(row.id, v)">
              <el-button size="small" link>切换角色</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="user" :disabled="row.role === 'user'">普通用户</el-dropdown-item>
                  <el-dropdown-item command="viewer" :disabled="row.role === 'viewer'">观察者</el-dropdown-item>
                  <el-dropdown-item command="admin" :disabled="row.role === 'admin'">管理员</el-dropdown-item>
                  <el-dropdown-item command="hidden" :disabled="row.role === 'hidden'">禁用</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-popconfirm title="确定删除该用户？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button size="small" link type="danger" style="margin-left:8px;">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
          <el-tooltip v-if="!canModify(row)" :content="'不能操作' + (row.role === 'developer' ? '开发者' : '同级管理员')" placement="top">
            <span style="color:#999;font-size:12px;margin-left:4px;">🔒</span>
          </el-tooltip>
        </template>
      </el-table-column>
    </el-table>
    <div style="display:flex;justify-content:center;padding:16px 0;">
      <el-pagination v-if="total > pageSize" background layout="prev,pager,next" :total="total" :page-size="pageSize" :current-page="currentPage" @current-change="handlePageChange" />
    </div>

    <!-- 创建用户弹窗 -->
    <el-dialog v-model="showCreateDialog" title="创建用户" width="400px">
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
          <el-select v-model="createForm.role" style="width:100%">
            <el-option label="普通用户" value="user" />
            <el-option label="观察者" value="viewer" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="平台">
          <el-select v-model="createForm.platform" style="width:100%">
            <el-option label="GG (Google Ads)" value="gg" />
            <el-option label="FB (Facebook)" value="fb" />
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
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { adminApi } from '../api/admin'
import { adminDataApi } from '@/api/data'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'

const authStore = useAuthStore()

const users = ref([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const platformFilter = ref('')

function isSelf(uid) {
  return authStore.user?.id === uid
}

function canModify(row) {
  if (isSelf(row.id)) return false
  if (authStore.isDeveloper) return true
  // 管理员只能操作普通用户、观察者和已禁用用户，不能操作其他管理员
  return ['user', 'viewer', 'hidden'].includes(row.role)
}

function roleType(role) {
  const m = { developer: 'danger', admin: 'warning', viewer: '', user: 'success', hidden: 'info' }
  return m[role] || 'info'
}
function roleLabel(role) {
  const m = { developer: '开发者', admin: '管理员', viewer: '观察者', user: '用户', hidden: '已禁用' }
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

onMounted(() => fetchUsers())

// ---- 创建用户 ----
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({
  username: "",
  password: "",
  display_name: "",
  role: "user",
  platform: "gg"
})

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
    createForm.value = { username: "", password: "", display_name: "", role: "user", platform: "gg" }
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
