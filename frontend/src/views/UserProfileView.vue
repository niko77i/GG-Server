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

    <!-- 自定义后缀 -->
    <el-card shadow="never" style="margin-bottom:16px;">
      <template #header>
        <span style="font-weight:600;">自定义后缀</span>
      </template>
      <p style="font-size:12px;color:#888;margin-bottom:8px;">复制系列名时自动拼接，格式：系列名-后缀</p>
      <el-form :model="customNameForm" label-width="80px" size="small">
        <el-form-item label="后缀">
          <el-input v-model="customNameForm.custom_name" placeholder="例如 Carl" />
        </el-form-item>
      </el-form>
      <el-button type="primary" size="small" :loading="savingCustomName" @click="saveCustomName">保存</el-button>
    </el-card>

    <!-- 邮箱通知 -->
    <el-card shadow="never" style="margin-bottom:16px;">
      <template #header>
        <span style="font-weight:600;">📧 邮箱通知</span>
      </template>
      <p style="font-size:12px;color:#888;margin-bottom:8px;">
        填写 QQ 邮箱，检测到掉包时自动发邮件通知（微信可收到 QQ 邮箱提醒）
      </p>
      <el-form :model="emailForm" label-width="80px" size="small">
        <el-form-item label="QQ 邮箱">
          <el-input v-model="emailForm.email" placeholder="例如 123456@qq.com" />
        </el-form-item>
      </el-form>
      <el-button type="primary" size="small" :loading="savingEmail" @click="saveEmail">保存</el-button>
    </el-card>

    <!-- Telegram 通知 -->
    <el-card shadow="never" style="margin-bottom:16px;">
      <template #header>
        <span style="font-weight:600;">📱 Telegram 通知</span>
      </template>
      <p style="font-size:12px;color:#888;margin-bottom:8px;">
        填写 Telegram 用户名（不带 @），掉包时会在群组中 @ 你。留空则不接收群组 @ 通知。
      </p>
      <el-form :model="tgForm" label-width="100px" size="small">
        <el-form-item label="Telegram 用户名">
          <el-input v-model="tgForm.telegram_username" placeholder="例如 carl567" />
        </el-form-item>
      </el-form>
      <el-button type="primary" size="small" :loading="savingTg" @click="saveTelegramUsername">保存</el-button>
    </el-card>

    <!-- Google Sheets 配置 -->
    <el-card shadow="never" style="margin-bottom:16px;">
      <template #header>
        <span style="font-weight:600;">📊 Google Sheets 配置</span>
      </template>
      <p style="font-size:12px;color:#888;margin-bottom:8px;">
        配置你的 Google 在线表格，用于做表数据的读取和写入。每月使用新表时添加即可，点击 ● 切换当前激活。
      </p>

      <!-- 表格列表 -->
      <div v-if="gsSheets.length" style="margin-bottom:12px;">
        <div v-for="s in gsSheets" :key="s.id"
          style="display:flex;align-items:center;gap:8px;padding:6px 8px;margin-bottom:4px;border-radius:6px;"
          :style="{ background: s.id === gsActiveId ? '#ecf5ff' : '#fafafa', border: s.id === gsActiveId ? '1px solid #409eff' : '1px solid #eee' }">
          <el-radio :model-value="gsActiveId" :value="s.id" @change="setActive(s.id)" style="margin-right:0;" />
          <div style="flex:1;min-width:0;">
            <div style="font-size:13px;font-weight:500;">{{ s.spreadsheet_name || '(未命名)' }}</div>
            <div style="font-size:11px;color:#999;">{{ s.spreadsheet_id }}</div>
          </div>
          <el-button link size="small" type="primary" @click="startEdit(s)">编辑</el-button>
          <el-popconfirm title="确定删除此表格配置？" @confirm="deleteSheet(s.id)">
            <template #reference><el-button link size="small" type="danger">删除</el-button></template>
          </el-popconfirm>
        </div>
      </div>
      <div v-else style="font-size:12px;color:#bbb;text-align:center;padding:12px 0;">暂无表格配置，点击下方按钮添加</div>

      <!-- 添加 / 编辑表单 -->
      <div v-if="gsShowForm" style="background:#f9fafb;padding:10px;border-radius:6px;margin-bottom:10px;">
        <el-form :model="gsForm" label-width="90px" size="small">
          <el-form-item label="表格网址/ID">
            <el-input v-model="gsForm.urlOrId" placeholder="粘贴完整网址或直接填 spreadsheet ID" @blur="onGsUrlBlur" />
          </el-form-item>
          <el-form-item label="表格名称">
            <el-input v-model="gsForm.spreadsheet_name" placeholder="例如 2026-07 做表数据" />
          </el-form-item>
        </el-form>
        <div style="display:flex;gap:8px;">
          <el-button size="small" type="primary" :loading="savingGs" @click="saveSheet">
            {{ gsEditingId ? '更新' : '添加' }}
          </el-button>
          <el-button size="small" @click="cancelEdit">取消</el-button>
        </div>
      </div>

      <el-button v-if="!gsShowForm" size="small" @click="startEdit(null)">+ 添加表格</el-button>

      <!-- 列映射参考 -->
      <div style="font-size:11px;color:#999;margin-top:12px;background:#f9fafb;padding:8px;border-radius:6px;">
        <div style="font-weight:600;margin-bottom:4px;">📋 表格列映射参考：</div>
        <table style="width:100%;border-collapse:collapse;font-size:11px;">
          <tr style="background:#e5e7eb;"><td style="padding:2px 6px;">A 列</td><td style="padding:2px 6px;">B 列</td><td style="padding:2px 6px;">C 列</td><td style="padding:2px 6px;">D 列</td></tr>
          <tr><td style="padding:2px 6px;">账号名称</td><td style="padding:2px 6px;">广告账户id</td><td style="padding:2px 6px;">账号消耗</td><td style="padding:2px 6px;">渠道号</td></tr>
          <tr style="color:#666;"><td style="padding:2px 6px;">→ 账号</td><td style="padding:2px 6px;">→ 客户ID</td><td style="padding:2px 6px;">→ 费用</td><td style="padding:2px 6px;">→ 广告系列</td></tr>
        </table>
      </div>
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
import { googleSheetsApi } from '@/api/google-sheets'
import { ElMessage } from 'element-plus'
import api from '@/api/client'

const authStore = useAuthStore()
const user = ref(null)

const profileForm = ref({ display_name: "" })
const savingProfile = ref(false)

const customNameForm = ref({ custom_name: "" })
const savingCustomName = ref(false)

const emailForm = ref({ email: "" })
const savingEmail = ref(false)

const tgForm = ref({ telegram_username: "" })
const savingTg = ref(false)

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
  const u = await authStore.fetchMe()
  user.value = u
  profileForm.value.display_name = u?.display_name || ""
  // 加载 custom_name
  try {
    const res = await api.get('/auth/custom-name')
    customNameForm.value.custom_name = res.custom_name || ''
  } catch {}
  // 加载邮箱
  try {
    const res = await api.get('/auth/email')
    emailForm.value.email = res.email || ''
  } catch {}
  // 加载 telegram_username（/auth/me 已返回此字段）
  tgForm.value.telegram_username = u?.telegram_username || ''
  // 加载 Google Sheets 配置
  loadGsConfig()
})

async function saveCustomName() {
  savingCustomName.value = true
  try {
    await api.put('/auth/custom-name', { custom_name: customNameForm.value.custom_name })
    ElMessage.success('后缀已更新')
  } catch (e) {
    ElMessage.error('更新失败')
  } finally {
    savingCustomName.value = false
  }
}

async function saveEmail() {
  savingEmail.value = true
  try {
    await api.put('/auth/email', { email: emailForm.value.email })
    ElMessage.success('邮箱已更新')
  } catch (e) {
    ElMessage.error('更新失败')
  } finally {
    savingEmail.value = false
  }
}

async function saveTelegramUsername() {
  savingTg.value = true
  try {
    await api.put('/auth/telegram-username', { telegram_username: tgForm.value.telegram_username })
    ElMessage.success('Telegram 用户名已更新')
  } catch (e) {
    ElMessage.error('更新失败')
  } finally {
    savingTg.value = false
  }
}

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

// ===== Google Sheets 配置 =====

const gsSheets = ref([])       // 表格列表
const gsActiveId = ref('')     // 当前激活的表格 id
const gsShowForm = ref(false)  // 是否展开表单
const gsEditingId = ref(null)  // 正在编辑的 id（null = 新增模式）
const gsForm = ref({ urlOrId: '', spreadsheet_name: '' })
const savingGs = ref(false)
let _gsGid = '0'  // 当前编辑中提取的 gid

function parseSheetsUrl(input) {
  const trimmed = (input || '').trim()
  if (trimmed && !trimmed.includes('/') && !trimmed.includes(' ')) {
    return { spreadsheet_id: trimmed, gid: '0' }
  }
  const mId = trimmed.match(/spreadsheets\/d\/([a-zA-Z0-9_-]+)/)
  const mGid = trimmed.match(/[?&#]gid=(\d+)/)
  return {
    spreadsheet_id: mId ? mId[1] : '',
    gid: mGid ? mGid[1] : '0'
  }
}

function onGsUrlBlur() {
  const parsed = parseSheetsUrl(gsForm.value.urlOrId)
  if (parsed.spreadsheet_id) {
    _gsGid = parsed.gid
    gsForm.value.urlOrId = parsed.spreadsheet_id
  }
}

async function loadGsConfig() {
  try {
    const res = await googleSheetsApi.getConfig()
    gsSheets.value = res.sheets || []
    gsActiveId.value = res.active_id || ''
  } catch { /* 静默失败 */ }
}

function startEdit(sheet) {
  if (sheet) {
    gsEditingId.value = sheet.id
    gsForm.value.urlOrId = sheet.spreadsheet_id
    gsForm.value.spreadsheet_name = sheet.spreadsheet_name
    _gsGid = sheet.sheet_gid || '0'
  } else {
    gsEditingId.value = null
    gsForm.value.urlOrId = ''
    gsForm.value.spreadsheet_name = ''
    _gsGid = '0'
  }
  gsShowForm.value = true
}

function cancelEdit() {
  gsShowForm.value = false
  gsEditingId.value = null
  gsForm.value.urlOrId = ''
  gsForm.value.spreadsheet_name = ''
  _gsGid = '0'
}

async function saveSheet() {
  const parsed = parseSheetsUrl(gsForm.value.urlOrId)
  const finalId = parsed.spreadsheet_id
  if (!finalId) {
    ElMessage.warning('请输入 Google 表格 ID 或完整网址')
    return
  }
  _gsGid = parsed.gid || _gsGid
  gsForm.value.urlOrId = finalId

  const entry = {
    id: gsEditingId.value || ('m' + Date.now()),
    spreadsheet_id: finalId,
    spreadsheet_name: gsForm.value.spreadsheet_name,
    sheet_gid: _gsGid
  }

  let updated
  if (gsEditingId.value) {
    updated = gsSheets.value.map(s => s.id === gsEditingId.value ? entry : s)
  } else {
    updated = [...gsSheets.value, entry]
  }

  savingGs.value = true
  try {
    await googleSheetsApi.saveConfig({ sheets: updated, active_id: gsActiveId.value || entry.id })
    gsSheets.value = updated
    if (!gsActiveId.value) gsActiveId.value = entry.id
    ElMessage.success(gsEditingId.value ? '表格已更新' : '表格已添加')
    cancelEdit()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.error || e.message))
  } finally {
    savingGs.value = false
  }
}

async function setActive(id) {
  gsActiveId.value = id
  try {
    await googleSheetsApi.saveConfig({ sheets: gsSheets.value, active_id: id })
  } catch { /* 静默失败 */ }
}

async function deleteSheet(id) {
  const updated = gsSheets.value.filter(s => s.id !== id)
  const newActive = gsActiveId.value === id ? (updated[0]?.id || '') : gsActiveId.value
  try {
    await googleSheetsApi.saveConfig({ sheets: updated, active_id: newActive })
    gsSheets.value = updated
    gsActiveId.value = newActive
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.error || e.message))
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
