<template>
  <div class="share-page">
    <div class="page-head">
      <h3>🔗 共享账号</h3>
      <span class="sub">同事用他自己的 GG-Server 账号打开本页，点「打开」即可，不需要你发链接；会话失效时由管理员重新登录一次。</span>
    </div>

    <el-alert v-if="loadError" type="warning" :closable="false" show-icon style="margin-bottom:16px;">
      <template #title>共享账号列表加载失败：{{ loadError }}</template>
    </el-alert>

    <div class="site-list">
      <el-card v-for="site in sites" :key="site.id" shadow="never" class="site-card">
        <div class="site-row">
          <div class="site-main">
            <div class="site-title">
              <span class="site-name">{{ site.name }}</span>
              <span class="site-host">{{ hostOf(site) }}</span>
              <el-tag :type="statusMeta(site.status).type" size="small" effect="light">
                {{ statusMeta(site.status).label }}
              </el-tag>
            </div>
            <div class="site-desc">{{ statusMeta(site.status).desc }}</div>
            <div class="site-meta">
              <span v-if="site.expires_at">会话有效期：{{ site.expires_at }}</span>
              <span v-else>会话有效期：—</span>
              <span>今日 {{ site.today_users }} 人使用</span>
              <span v-if="site.last_access">
                上次：{{ site.last_access.created_at }} · {{ site.last_access.username }}
              </span>
            </div>
            <div v-if="site.last_error" class="site-error">{{ site.last_error }}</div>
            <div class="site-share-tip">「复制本机链接」是 60 秒内有效、只能用一次的链接，只适合在本机换浏览器打开；发给同事请让他在本页点「打开」（链接绑定你自己的账号，发给别人会提示失效）。</div>
          </div>

          <div class="site-actions">
            <el-button type="primary" :disabled="!canOpen(site)" :loading="busy === site.id" @click="openSite(site)">
              打开
            </el-button>
            <el-button :disabled="!canOpen(site)" @click="copyLink(site)">复制本机链接</el-button>
            <el-dropdown v-if="site.can_manage" trigger="click" @command="(cmd) => onCommand(site, cmd)">
              <el-button>管理 ⋯</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="check">立即检测</el-dropdown-item>
                  <el-dropdown-item command="reset">清空会话（重新登录）</el-dropdown-item>
                  <el-dropdown-item command="logs">访问日志</el-dropdown-item>
                  <el-dropdown-item command="toggle" divided>{{ site.enabled ? '停用本站点' : '启用本站点' }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <div v-if="!site.enabled" class="site-note">站点已停用：同事无法打开；端口与上游地址在 config.json 的 share_gateway 里配置。</div>
      </el-card>

      <div v-if="!loading && sites.length === 0" class="share-empty">
        <div class="empty-icon">🔗</div>
        <div class="empty-title">还没有配置共享站点</div>
        <div class="empty-desc">联系开发者在 config.json 的 share_gateway.sites 里添加站点，并放行对应端口。</div>
      </div>
    </div>

    <el-dialog v-model="logVisible" title="共享账号访问日志" width="680px">
      <el-table :data="logs" size="small" height="360" empty-text="暂无记录">
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column prop="username" label="用户" width="160" />
        <el-table-column prop="ip" label="IP" />
      </el-table>
      <div class="log-tip">只记录「进入共享页面」这个动作，不记录浏览内容。</div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { shareApi } from '../api/share'

const sites = ref([])
const loading = ref(false)
const loadError = ref('')
const busy = ref('')
const logs = ref([])
const logVisible = ref(false)
let timer = null

const STATUS = {
  ok: { label: '可用', type: 'success', desc: '会话已就绪，点「打开」即可使用。' },
  expired: { label: '需重新登录', type: 'warning', desc: '会话已过期。管理员打开本站点、在页面里登录一次即可，其他人无需操作。' },
  unknown: { label: '未登录', type: 'info', desc: '还没有人登录过。管理员打开本站点登录一次即可。' },
  down: { label: '网关未启动', type: 'danger', desc: '网关端口没有监听：检查服务是否启动、端口是否被占用/被防火墙拦截。' },
  disabled: { label: '未启用', type: 'info', desc: '站点已停用。' },
}

function statusMeta(status) {
  return STATUS[status] || { label: status || '未知', type: 'info', desc: '' }
}

function hostOf(site) {
  return (site.upstream || '').replace(/^https?:\/\//, '').replace(/\/$/, '')
}

function canOpen(site) {
  return site.enabled && site.running
}

async function loadSites() {
  loading.value = true
  try {
    const res = await shareApi.listSites()
    sites.value = res.sites || []
    loadError.value = ''
  } catch (e) {
    loadError.value = e?.response?.data?.error || e?.message || '网络错误'
  } finally {
    loading.value = false
  }
}

async function openSite(site) {
  if (!canOpen(site) || busy.value) return
  // 先开窗口（用户手势内），再等接口返回票据，避免被弹窗拦截
  const win = window.open('', '_blank')
  busy.value = site.id
  try {
    const res = await shareApi.enter(site.id)
    if (win) {
      win.location.href = res.url
    } else {
      ElMessage.warning('浏览器拦截了新窗口，请允许弹出窗口后重试')
    }
  } catch (e) {
    if (win) win.close()
    ElMessage.error(e?.response?.data?.error || '打开失败')
  } finally {
    busy.value = ''
  }
}

async function copyLink(site) {
  if (!canOpen(site) || busy.value) return
  busy.value = site.id
  try {
    const res = await shareApi.enter(site.id)
    await copyText(res.url)
    ElMessage.success('已复制：60 秒内有效、只能用一次，只适合本机换浏览器打开')
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '复制失败')
  } finally {
    busy.value = ''
  }
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
    return
  }
  // 局域网 http 下 clipboard API 不可用，退回 textarea + execCommand
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try {
    document.execCommand('copy')
  } finally {
    document.body.removeChild(ta)
  }
}

async function onCommand(site, cmd) {
  if (cmd === 'check') return runCheck(site)
  if (cmd === 'reset') return resetSession(site)
  if (cmd === 'logs') return showLogs(site)
  if (cmd === 'toggle') return toggleSite(site)
}

async function runCheck(site) {
  try {
    const res = await shareApi.check(site.id)
    ElMessage.success(`检测完成：${statusMeta(res.status).label}`)
    await loadSites()
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '检测失败')
  }
}

async function resetSession(site) {
  try {
    await ElMessageBox.confirm(
      '清空后所有人都无法使用，需要管理员在共享页面里重新登录一次。确定清空？',
      '清空会话',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await shareApi.reset(site.id)
    ElMessage.success('已清空会话')
    await loadSites()
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '清空失败')
  }
}

async function toggleSite(site) {
  try {
    await shareApi.update(site.id, { enabled: !site.enabled })
    ElMessage.success(site.enabled ? '已停用' : '已启用')
    await loadSites()
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '操作失败')
  }
}

async function showLogs(site) {
  try {
    const res = await shareApi.logs(site.id)
    logs.value = res.logs || []
    logVisible.value = true
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '读取日志失败')
  }
}

onMounted(() => {
  loadSites()
  timer = setInterval(() => {
    if (document.visibilityState === 'visible') loadSites()
  }, 30000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.share-page { padding: 4px 2px; }
.page-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.page-head h3 { margin: 0; font-size: 18px; font-weight: 600; color: #111827; }
.page-head .sub { font-size: 13px; color: #6b7280; }
.site-list { display: flex; flex-direction: column; gap: 14px; }
.site-card :deep(.el-card__body) { padding: 18px 20px; }
.site-row { display: flex; justify-content: space-between; gap: 20px; flex-wrap: wrap; }
.site-main { min-width: 280px; flex: 1; }
.site-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.site-name { font-size: 16px; font-weight: 600; color: #111827; }
.site-host { font-size: 12px; color: #6b7280; background: #f3f4f6; border-radius: 4px; padding: 1px 6px; }
.site-desc { margin-top: 6px; font-size: 13px; color: #4b5563; }
.site-meta { margin-top: 8px; display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: #9ca3af; }
.site-error { margin-top: 8px; font-size: 12px; color: #b45309; }
.site-share-tip { margin-top: 10px; font-size: 12px; color: #9ca3af; line-height: 1.6; }
.site-actions { display: flex; align-items: flex-start; gap: 8px; flex-wrap: wrap; }
.site-note { margin-top: 12px; padding-top: 10px; border-top: 1px dashed #e5e7eb; font-size: 12px; color: #9ca3af; }
.share-empty { text-align: center; padding: 64px 0; background: #fff; border-radius: 8px; border: 1px dashed #e5e7eb; }
.empty-icon { font-size: 36px; }
.empty-title { margin-top: 10px; font-size: 15px; font-weight: 600; color: #374151; }
.empty-desc { margin-top: 6px; font-size: 13px; color: #9ca3af; }
.log-tip { margin-top: 10px; font-size: 12px; color: #9ca3af; }
</style>
