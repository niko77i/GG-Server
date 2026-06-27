<template>
  <div style="max-width:600px;margin:0 auto;">
    <h3 style="margin:0 0 20px;font-size:18px;font-weight:600;color:#111827;">👤 个人信息</h3>

    <!-- 基本信息卡片 -->
    <el-card shadow="never" style="margin-bottom:16px;">
      <template #header>
        <span style="font-weight:600;">基本信息</span>
      </template>
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="用户 ID">{{ user?.id }}</el-descriptions-item>
        <el-descriptions-item label="用户名">{{ user?.username }}</el-descriptions-item>
        <el-descriptions-item label="显示名">{{ user?.display_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="角色">
          <el-tag :type="roleType(user?.role)" size="small">{{ roleLabel(user?.role) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ user?.created_at || '-' }}</el-descriptions-item>
        <el-descriptions-item label="最后登录">{{ user?.last_login || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 编辑显示名 -->
    <el-card shadow="never" style="margin-bottom:16px;">
      <template #header>
        <span style="font-weight:600;">编辑显示名</span>
      </template>
      <el-form :model="profileForm" label-width="80px" size="small">
        <el-form-item label="显示名">
          <el-input v-model="profileForm.display_name" placeholder="输入新的显示名" />
        </el-form-item>
      </el-form>
      <el-button type="primary" size="small" :loading="savingProfile" @click="saveProfile">保存</el-button>
    </el-card>

    <!-- 修改密码 -->
    <el-card shadow="never">
      <template #header>
        <span style="font-weight:600;">修改密码</span>
      </template>
      <el-form :model="pwdForm" label-width="80px" size="small">
        <el-form-item label="旧密码">
          <el-input v-model="pwdForm.old_password" type="password" placeholder="输入当前密码" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.new_password" type="password" placeholder="至少6位" show-password />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="pwdForm.confirm_password" type="password" placeholder="再次输入新密码" show-password />
        </el-form-item>
      </el-form>
      <el-button type="primary" size="small" :loading="changingPwd" @click="changePwd">修改密码</el-button>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/auth'
import { ElMessage } from 'element-plus'

const authStore = useAuthStore()
const user = ref(null)

const profileForm = ref({ display_name: "" })
const savingProfile = ref(false)

const pwdForm = ref({ old_password: "", new_password: "", confirm_password: "" })
const changingPwd = ref(false)

function roleType(role) {
  const m = { developer: 'danger', admin: 'warning', user: 'success', hidden: 'info' }
  return m[role] || 'info'
}
function roleLabel(role) {
  const m = { developer: '开发者', admin: '管理员', user: '用户', hidden: '已禁用' }
  return m[role] || role
}

onMounted(async () => {
  // 从服务端获取最新用户信息
  const u = await authStore.fetchMe()
  user.value = u
  profileForm.value.display_name = u?.display_name || ""
})

async function saveProfile() {
  savingProfile.value = true
  try {
    const res = await authApi.updateProfile({ display_name: profileForm.value.display_name })
    user.value = res.user
    // 同步更新 store
    authStore.user = res.user
    localStorage.setItem('user', JSON.stringify(res.user))
    ElMessage.success('显示名已更新')
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '更新失败')
  } finally {
    savingProfile.value = false
  }
}

async function changePwd() {
  if (!pwdForm.value.old_password) {
    ElMessage.warning('请输入旧密码')
    return
  }
  if (!pwdForm.value.new_password || pwdForm.value.new_password.length < 6) {
    ElMessage.warning('新密码至少6位')
    return
  }
  if (pwdForm.value.new_password !== pwdForm.value.confirm_password) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  changingPwd.value = true
  try {
    await authApi.changePassword(pwdForm.value.old_password, pwdForm.value.new_password)
    ElMessage.success('密码已修改，请重新登录')
    pwdForm.value = { old_password: "", new_password: "", confirm_password: "" }
    // 密码修改后需要重新登录
    setTimeout(() => authStore.logout(), 1500)
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '修改失败')
  } finally {
    changingPwd.value = false
  }
}
</script>
