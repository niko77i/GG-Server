<template>
  <div class="user-manage">
    <h3 style="margin:0 0 16px;font-size:18px;font-weight:600;color:#111827;">用户管理</h3>
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
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
</template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="160" />
      <el-table-column prop="last_login" label="最后登录" width="160" />
      <el-table-column label="操作" min-width="200">
        <template #default="{ row }">
          <el-dropdown v-if="row.role !== 'developer'" trigger="click" @command="(v) => handleRoleChange(row.id, v)">
            <el-button size="small" link>切换角色</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="user" :disabled="row.role === 'user'">普通用户</el-dropdown-item>
                <el-dropdown-item command="admin" :disabled="row.role === 'admin'">管理员</el-dropdown-item>
                <el-dropdown-item command="hidden" :disabled="row.role === 'hidden'">禁用</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-popconfirm v-if="row.role !== 'developer'" title="确定删除该用户？" @confirm="handleDelete(row.id)">
            <template #reference>
              <el-button size="small" link type="danger" style="margin-left:8px;">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
    <div style="display:flex;justify-content:center;padding:16px 0;">
      <el-pagination v-if="total > pageSize" background layout="prev,pager,next" :total="total" :page-size="pageSize" :current-page="currentPage" @current-change="handlePageChange" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { adminApi } from '../api/admin'
import { ElMessage } from 'element-plus'

const users = ref([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

function roleType(role) {
  const m = { developer: 'danger', admin: 'warning', user: 'success', hidden: 'info' }
  return m[role] || 'info'
}
function roleLabel(role) {
  const m = { developer: '开发者', admin: '管理员', user: '用户', hidden: '已禁用' }
  return m[role] || role
}

async function fetchUsers() {
  loading.value = true
  try {
    const res = await adminApi.listUsers({ search: search.value, page: currentPage.value, page_size: pageSize.value })
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

async function handleRoleChange(uid, role) {
  try {
    await adminApi.updateRole(uid, role)
    ElMessage.success('角色已更新')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '操作失败')
  }
}

async function handleDelete(uid) {
  try {
    await adminApi.deleteUser(uid)
    ElMessage.success('用户已删除')
    fetchUsers()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '删除失败')
  }
}

onMounted(() => fetchUsers())

const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({
  username: "",
  password: "",
  display_name: "",
  role: "user"
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
    createForm.value = { username: "", password: "", display_name: "", role: "user" }
    fetchUsers()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || "创建失败")
  } finally {
    creating.value = false
  }
}
</script>