<template>
  <div>
    <h1>🎬 AI 视频生成</h1>
    <p style="color:#888;margin-bottom:20px;">从已爬取的图片生成视频，可选 Logo 水印与 AI 动态效果</p>

    <div style="display:flex;gap:12px;align-items:flex-start;">
      <div style="flex:1;min-width:0;">

        <!-- 选择目录 -->
        <el-form-item label="📂 选择图片目录">
          <div style="display:flex;gap:8px;">
            <el-input v-model="videoDir" placeholder="例如：F:\images\google_ads\com.spotify.music" style="flex:1;min-width:0;" />
            <el-button @click="browseFolder" style="width:44px;">📂</el-button>
            <el-button type="primary" @click="scanDir" :loading="scanning">🔍 扫描</el-button>
          </div>
          <span class="hint">选择已爬取的包名文件夹（包含 PNG 图片和 包logo 子目录）</span>
        </el-form-item>

        <!-- 图片列表 -->
        <div v-if="images.length" style="margin-bottom:16px;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <span>🖼️ 图片列表（共 {{ images.length }} 张）</span>
            <div style="display:flex;gap:8px;align-items:center;">
              <el-checkbox v-model="randomOrder" size="small">随机排序</el-checkbox>
              <el-button link size="small" @click="toggleSelectAll">{{ allSelected ? '☑ 取消全选' : '☑ 全选' }}</el-button>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">
            <div v-for="img in images" :key="img.filename" class="img-card" :class="{ selected: selectedImgs[img.filename] }" @click="toggleImg(img.filename)">
              <el-image :src="'/api/image?path=' + encodeURIComponent(img.path)" fit="cover" style="aspect-ratio:16/10;border-radius:4px 4px 0 0;" />
              <div style="padding:4px 8px;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ img.filename }}</div>
            </div>
          </div>
        </div>

        <!-- Logo 叠加 -->
        <div v-if="logo" style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:12px;margin-bottom:16px;">
          <el-checkbox v-model="useLogo">🏷️ Logo 叠加 — 检测到: {{ logo.filename }}</el-checkbox>
          <div v-if="useLogo" style="display:flex;gap:12px;margin-top:8px;">
            <el-form-item label="位置" style="flex:1;margin-bottom:0;">
              <el-select v-model="logoPosition" size="small">
                <el-option label="右上" value="top-right" /><el-option label="左上" value="top-left" />
                <el-option label="左下" value="bottom-left" /><el-option label="右下" value="bottom-right" />
                <el-option label="浮动" value="floating" />
              </el-select>
            </el-form-item>
            <el-form-item label="效果" style="flex:1;margin-bottom:0;">
              <el-select v-model="logoEffect" size="small">
                <el-option label="静态" value="static" /><el-option label="淡入淡出" value="fade" />
                <el-option label="浮动弹跳" value="bounce" /><el-option label="放大进入" value="zoom-in" />
                <el-option label="从右滑入" value="slide-right" /><el-option label="脉冲缩放" value="pulse" />
              </el-select>
            </el-form-item>
          </div>
        </div>

        <!-- AI 动态化 -->
        <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:12px;margin-bottom:16px;">
          <el-checkbox v-model="useAI">🤖 使用 AI 将静态图片转为短视频（可选，需 API Key）</el-checkbox>
          <div v-if="useAI">
            <div style="display:flex;gap:8px;margin-top:8px;">
              <el-form-item label="API 服务" style="flex:1;margin-bottom:0;">
                <el-select v-model="aiService" size="small">
                  <el-option label="豆包 Seedance 1.5 Pro（推荐）" value="doubao" />
                  <el-option label="豆包 Seedance 1.0 Pro Fast（⚡极速）" value="doubao-fast" />
                  <el-option label="Seedance 2.0（每日免费积分）" value="seedance" />
                  <el-option label="Veo 3.1 Lite（免费·需代理）" value="veo" />
                  <el-option label="Atlas Cloud（多模型网关）" value="atlas" />
                </el-select>
              </el-form-item>
              <el-form-item label="每段时长（秒）" style="width:120px;margin-bottom:0;">
                <el-select v-model="aiDuration" size="small">
                  <el-option label="3" :value="3" /><el-option label="4" :value="4" />
                  <el-option label="5" :value="5" /><el-option label="8（仅Veo）" :value="8" />
                </el-select>
              </el-form-item>
            </div>
            <el-form-item label="API Key" style="margin-bottom:4px;">
              <el-input v-model="aiApiKey" type="password" size="small" placeholder="输入 API Key" />
            </el-form-item>
            <el-form-item label="🎨 视频效果描述（可选）" style="margin-bottom:0;">
              <el-input v-model="aiPrompt" size="small" placeholder="例如：镜头缓慢推进，光影柔和，电影级质感" />
            </el-form-item>
          </div>
        </div>

        <!-- 视频设置 -->
        <h3 style="margin-bottom:12px;">⚙️ 视频设置</h3>

        <el-form-item label="🖼️ 背景图片（可选）">
          <div style="display:flex;gap:6px;">
            <el-input v-model="bgImage" placeholder="留空则使用纯色背景" style="flex:1;min-width:0;" />
            <el-button @click="browseBgImage" style="width:44px;">📂</el-button>
          </div>
        </el-form-item>

        <div v-if="!bgImage" style="display:flex;gap:12px;">
          <el-form-item label="背景颜色" style="flex:1;">
            <div style="display:flex;align-items:center;gap:8px;">
              <el-color-picker v-model="bgColor" size="small" />
              <el-checkbox v-model="dynamicBg" size="small">动态背景</el-checkbox>
              <el-select v-if="dynamicBg" v-model="dynamicBgMode" size="small" style="width:120px;">
                <el-option label="呼吸" value="breathe" /><el-option label="波浪" value="wave" />
                <el-option label="律动" value="beat" /><el-option label="流光" value="flow" />
              </el-select>
            </div>
          </el-form-item>
          <el-form-item label="内容缩放" style="width:120px;">
            <el-select v-model="contentScale" size="small">
              <el-option label="70%" value="0.70" /><el-option label="82%" value="0.82" />
              <el-option label="92%" value="0.92" /><el-option label="100%" value="1.00" />
            </el-select>
          </el-form-item>
        </div>

        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">
          <el-form-item label="单帧时长"><el-select v-model="frameDuration" size="small" style="width:100%;"><el-option v-for="d in [3,4,5]" :key="d" :label="d+'秒'" :value="d" /></el-select></el-form-item>
          <el-form-item label="转场效果"><el-select v-model="transition" size="small" style="width:100%;">
            <el-option label="淡入淡出" value="fade" /><el-option label="黑场过渡" value="fadeblack" /><el-option label="白场过渡" value="fadewhite" />
            <el-option label="向右滑动" value="slideright" /><el-option label="向左滑动" value="slideleft" />
            <el-option label="向上滑动" value="slideup" /><el-option label="向下滑动" value="slidedown" />
            <el-option label="缩放" value="zoomin" /><el-option label="溶解" value="dissolve" />
            <el-option label="像素化" value="pixelize" /><el-option label="圆形展开" value="circleopen" /><el-option label="圆形收缩" value="circleclose" />
            <el-option label="擦除" value="wiperight" /><el-option label="无" value="none" />
          </el-select></el-form-item>
          <el-form-item label="输出分辨率"><el-select v-model="resolution" size="small" style="width:100%;"><el-option label="9:16 竖屏" value="1080:1920" /><el-option label="1:1 方形" value="1080:1080" /></el-select></el-form-item>
          <el-form-item label="背景音乐（可选.mp3）">
            <div style="display:flex;gap:4px;"><el-input v-model="musicPath" size="small" placeholder="F:\music\bg.mp3" style="flex:1;min-width:0;" /><el-button @click="browseMusic" size="small" style="width:36px;flex-shrink:0;">📂</el-button></div>
          </el-form-item>
        </div>

        <!-- 输出路径 -->
        <el-form-item label="输出路径">
          <div style="display:flex;gap:6px;">
            <el-input v-model="outputPath" placeholder="例如：F:\output\video.mp4" @blur="outputPath = ensureMp4(outputPath)" style="flex:1;min-width:0;" />
            <el-button @click="browseSave" style="width:44px;">📂</el-button>
          </div>
          <span class="hint">必须包含 .mp4 扩展名，选择保存路径后自动补全</span>
        </el-form-item>

        <!-- 文案浮层 -->
        <el-form-item label="📝 文案浮层（最多两条）">
          <el-input v-model="text1" placeholder="文案 1（留空不显示）" size="small" style="margin-bottom:6px;" />
          <el-input v-model="text2" placeholder="文案 2（留空不显示）" size="small" style="margin-bottom:6px;" />
          <div style="display:flex;gap:6px;align-items:center;">
            <span style="font-size:11px;">字体</span>
            <el-select v-model="textFont" size="small" style="flex:1;" @change="updateFontPreview">
              <el-option v-for="f in fonts" :key="f.id" :label="f.name" :value="f.id" />
            </el-select>
            <el-button size="small" @click="importFont" style="width:36px;">📂</el-button>
          </div>
          <span class="hint" style="font-size:11px;color:#888;">每条随机浮现 2-3 秒，淡入淡出 + 阴影描边</span>
        </el-form-item>

        <!-- 操作按钮 -->
        <el-checkbox v-model="overwrite" size="small" style="margin-bottom:12px;">覆盖已有视频</el-checkbox>
        <div style="display:flex;gap:8px;">
          <el-button @click="addToQueue" style="flex:1;">📋 添加到队列</el-button>
          <el-button type="primary" @click="startGenerate" style="flex:1;">🎬 生成视频</el-button>
        </div>

        <!-- 任务队列 -->
        <div v-if="taskQueue.length" style="margin-top:16px;">
          <h3>📋 等待中（{{ taskQueue.length }}）</h3>
          <el-tag v-for="(t,i) in taskQueue" :key="i" size="small" style="margin:2px;" closable @close="removeFromQueue(i)">{{ t.name || '任务 '+(i+1) }}</el-tag>
          <el-button type="success" @click="generateAll" size="small" style="margin-top:8px;">⚡ 一键生成全部</el-button>
        </div>

        <!-- 进度 -->
        <div v-if="progressMsg" style="margin-top:16px;">
          <el-progress :percentage="Math.round(progressPct * 100)" />
          <span style="font-size:12px;color:#888;">{{ progressMsg }}</span>
        </div>
      </div>

      <!-- 历史侧边栏 -->
      <div style="width:220px;flex-shrink:0;border:1px solid #eee;border-radius:8px;padding:12px;max-height:calc(100vh - 100px);overflow-y:auto;position:sticky;top:20px;">
        <h4 style="font-size:12px;margin-bottom:8px;">📋 历史设置</h4>
        <div v-if="!Object.keys(history).length" style="font-size:10px;color:#999;">暂无历史</div>
        <div v-for="(entries, pkg) in history" :key="pkg" style="margin-bottom:8px;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <strong style="font-size:10px;color:#666;">{{ pkg }}</strong>
            <el-button link size="small" type="danger" @click="deleteHistoryPkg(pkg)" title="删除整包">✕</el-button>
          </div>
          <div v-for="(e,i) in (Array.isArray(entries) ? entries : [])" :key="i"
            style="font-size:10px;padding:2px 4px;cursor:pointer;border-radius:3px;display:flex;justify-content:space-between;align-items:center;"
            :style="{ background: e._id === activeHistoryId ? '#e6f7ff' : 'transparent' }">
            <span @click="applyHistory(e)" style="flex:1;">{{ e.name || e._saved_at || '-' }}</span>
            <el-button link size="small" type="danger" @click.stop="deleteHistoryEntry(pkg, i)" style="font-size:9px;">✕</el-button>
          </div>
        </div>
        <el-button size="small" @click="saveHistory" style="width:100%;margin-top:8px;">💾 保存当前设置</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useVideoStore } from '@/stores/video'
import { videoApi } from '@/api/video'
import { browseApi } from '@/api/browse'
import { ElMessage } from 'element-plus'

const store = useVideoStore()

// 目录 + 图片
const videoDir = ref('')
const scanning = ref(false)
const images = ref([])
const logo = ref(null)
const selectedImgs = ref({})
const allSelected = ref(true)
const randomOrder = ref(false)

// Logo
const useLogo = ref(false)
const logoPosition = ref('top-right')
const logoEffect = ref('static')

// AI
const useAI = ref(false)
const aiService = ref('doubao')
const aiDuration = ref(4)
const aiApiKey = ref('')
const aiPrompt = ref('')

// 视频设置
const bgImage = ref('')
const bgColor = ref('#f0ebe0')
const dynamicBg = ref(false)
const dynamicBgMode = ref('breathe')
const contentScale = ref('0.82')
const frameDuration = ref(3)
const transition = ref('fade')
const resolution = ref('1080:1920')
const musicPath = ref('')
const outputPath = ref('')
const overwrite = ref(false)

// 文案
const text1 = ref('')
const text2 = ref('')
const textFont = ref('simhei')
const fonts = ref([])

// 进度
const progressMsg = ref('')
const progressPct = ref(0)
const generating = ref(false)
let pollTimer = null

// 任务队列
const taskQueue = ref([])

// 历史
const history = ref({})
const activeHistoryId = ref(null)

onMounted(async () => {
  await store.loadFonts()
  fonts.value = store.fonts || []
  await loadHistory()
})

async function loadHistory() {
  await store.loadHistory()
  history.value = store.history
}

// 文件浏览
async function browseFolder() {
  try {
    const initial_dir = videoDir.value || null
    const res = await browseApi.folder({ initial_dir })
    if (res.path) videoDir.value = res.path
  } catch(e) { ElMessage.error('选择文件夹失败: ' + e.message) }
}
async function browseBgImage() {
  try {
    const res = await browseApi.file({ type: 'image', initial_dir: bgImage.value ? bgImage.value.substring(0, Math.max(bgImage.value.lastIndexOf('/'), bgImage.value.lastIndexOf('\\'))) : null })
    if (res.path) bgImage.value = res.path
  } catch(e) { ElMessage.error('选择文件失败: ' + e.message) }
}
async function browseMusic() {
  try {
    const res = await browseApi.file({ type: 'audio', initial_dir: musicPath.value ? musicPath.value.substring(0, Math.max(musicPath.value.lastIndexOf('/'), musicPath.value.lastIndexOf('\\'))) : null })
    if (res.path) musicPath.value = res.path
  } catch(e) { ElMessage.error('选择文件失败: ' + e.message) }
}
async function browseSave() {
  try {
    let p = outputPath.value
    let initial_dir = null
    if (p) {
      const idx = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'))
      if (idx > -1) initial_dir = p.substring(0, idx)
    }
    const res = await browseApi.save({ initial_dir })
    if (res.path) {
      p = res.path
      if (!p.toLowerCase().endsWith('.mp4')) p += '.mp4'
      outputPath.value = p
    }
  } catch(e) { ElMessage.error('选择保存路径失败: ' + e.message) }
}

// 扫描
async function scanDir() {
  if (!videoDir.value) return
  scanning.value = true
  try {
    const res = await store.scanDir(videoDir.value)
    images.value = res.images || []
    logo.value = res.logo
    toggleSelectAll(true)
    // 自动填充输出路径：{输入目录上一级}/ai/{包名}.mp4
    if (!outputPath.value) {
      const clean = videoDir.value.replace(/[\\/]+$/, '').replace(/\\/g, '/')
      const parts = clean.split('/')
      const pkg = parts[parts.length - 1]
      const parent = parts.slice(0, -1).join('/')
      let outPath = parent + '/ai/' + pkg + '.mp4'
      // 检查不覆盖
      try {
        const check = await videoApi.nextFilename({ output_path: outPath })
        if (check.path) outPath = check.path
      } catch(e) {}
      outputPath.value = outPath
    }
  } catch(e) { ElMessage.error(e.message) }
  scanning.value = false
}

// 接收来自爬取页面的目录跳转
onMounted(async () => {
  await store.loadFonts()
  fonts.value = store.fonts || []
  await loadHistory()
  // 检查是否有从爬取页面传来的目录
  const bridgeDir = sessionStorage.getItem('bridgeVideoDir')
  if (bridgeDir) {
    videoDir.value = bridgeDir
    sessionStorage.removeItem('bridgeVideoDir')
    await scanDir()
  }
})

// 选择图片
function toggleImg(filename) {
  selectedImgs.value = { ...selectedImgs.value, [filename]: !selectedImgs.value[filename] }
  allSelected.value = Object.keys(selectedImgs.value).length === images.value.length
}
function toggleSelectAll(force) {
  const s = {}
  const val = force !== undefined ? force : !allSelected.value
  if (val) images.value.forEach(img => s[img.filename] = true)
  selectedImgs.value = s
  allSelected.value = val
}

// 生成
function getSettings() {
  const sel = images.value.filter(img => selectedImgs.value[img.filename])
  return {
    images: sel.map(img => img.path),
    random_order: randomOrder.value,
    settings: {
      output_path: outputPath.value,
      use_logo: useLogo.value,
      logo_position: logoPosition.value,
      logo_effect: logoEffect.value,
      frame_duration: frameDuration.value,
      transition: transition.value,
      resolution: resolution.value,
      bg_image: bgImage.value || undefined,
      bg_color: bgColor.value,
      dynamic_bg: dynamicBg.value,
      dynamic_bg_mode: dynamicBgMode.value,
      content_scale: contentScale.value,
      music_path: musicPath.value || undefined,
      text1: text1.value || undefined,
      text2: text2.value || undefined,
      text_font: textFont.value,
      overwrite: overwrite.value,
    },
    ai: useAI.value ? {
      enabled: true, service: aiService.value, duration: aiDuration.value,
      api_key: aiApiKey.value, prompt: aiPrompt.value || undefined,
    } : { enabled: false },
  }
}

async function doGenerate(settings) {
  generating.value = true
  progressPct.value = 0
  progressMsg.value = '提交中...'
  try {
    const res = await store.generate(settings)
    const tid = res.task_id
    pollTimer = setInterval(async () => {
      const p = await store.checkProgress(tid)
      progressPct.value = p.progress || 0
      progressMsg.value = p.message || '处理中...'
      if (p.status === 'completed') {
        clearInterval(pollTimer); generating.value = false
        progressMsg.value = '✅ 完成: ' + (p.output || '')
        ElMessage.success('视频生成完成')
        // 自动保存设置到历史
        autoSaveHistory()
      }
      if (p.status === 'error') { clearInterval(pollTimer); generating.value = false; progressMsg.value = '❌ ' + (p.message || '未知错误'); ElMessage.error(p.message) }
    }, 2000)
  } catch(e) { generating.value = false; ElMessage.error(e.message) }
}

async function autoSaveHistory() {
  try {
    if (!videoDir.value || !images.value.length) return
    const s = getSettings()
    s.videoDir = videoDir.value
    s.name = (logo.value ? logo.value.filename : (images.value[0]?.filename || ''))
    delete s.images
    await store.saveHistory(s)
    await loadHistory()
  } catch(e) { /* 静默 */ }
}

function ensureMp4(p) {
  if (!p) return p
  return p.toLowerCase().endsWith('.mp4') ? p : p + '.mp4'
}

async function startGenerate() {
  outputPath.value = ensureMp4(outputPath.value)
  const s = getSettings()
  s.settings.output_path = outputPath.value
  if (!s.images.length) { ElMessage.warning('请选择图片'); return }
  if (!outputPath.value) { ElMessage.warning('请输入输出路径'); return }
  if (!overwrite.value) {
    try {
      const n = await videoApi.nextFilename({ output_path: outputPath.value })
      if (n.path) outputPath.value = n.path
    } catch(e) {}
  }
  await doGenerate(s)
}

function addToQueue() {
  outputPath.value = ensureMp4(outputPath.value)
  const s = getSettings()
  s.settings.output_path = outputPath.value
  if (!s.images.length) { ElMessage.warning('请选择图片'); return }
  const name = (logo.value ? logo.value.filename : (images.value[0]?.filename || ''))
  taskQueue.value.push({ ...s, name })
  ElMessage.success('已加入队列')
}

function removeFromQueue(i) { taskQueue.value.splice(i, 1) }

async function generateAll() {
  for (const t of taskQueue.value) {
    await doGenerate(t)
    await new Promise(r => setTimeout(r, 1000))
  }
  taskQueue.value = []
}

// 历史
async function saveHistory() {
  if (!videoDir.value) { ElMessage.warning('请先选择图片目录'); return }
  if (!images.value.length) { ElMessage.warning('请先扫描图片'); return }
  const s = getSettings()
  s.videoDir = videoDir.value
  s.name = (logo.value ? logo.value.filename : (images.value[0]?.filename || ''))
  delete s.images  // 不保存图片列表（数据量大，从目录重新扫描即可）
  await store.saveHistory(s)
  await loadHistory()
  ElMessage.success('已保存')
}

async function deleteHistoryEntry(pkg, index) {
  await store.deleteHistory(pkg, [index])
  await loadHistory()
  ElMessage.success('已删除')
}

async function deleteHistoryPkg(pkg) {
  await store.deleteHistory(pkg, null)  // null = 删整包
  await loadHistory()
  ElMessage.success('已删除整包')
}

function applyHistory(e) {
  activeHistoryId.value = e._id
  if (e.videoDir) videoDir.value = e.videoDir
  if (e.settings) {
    const s = e.settings
    if (s.output_path) outputPath.value = s.output_path
    if (s.frame_duration) frameDuration.value = s.frame_duration
    if (s.transition) transition.value = s.transition
    if (s.resolution) resolution.value = s.resolution
    if (s.bg_color != null) bgColor.value = s.bg_color
    if (s.content_scale) contentScale.value = s.content_scale
    if (s.music_path != null) musicPath.value = s.music_path
    if (s.text_font) textFont.value = s.text_font
    if (s.text1 != null) text1.value = s.text1
    if (s.text2 != null) text2.value = s.text2
    // Logo
    if (s.use_logo != null) useLogo.value = s.use_logo
    if (s.logo_position) logoPosition.value = s.logo_position
    if (s.logo_effect) logoEffect.value = s.logo_effect
    // 背景
    if (s.bg_image != null) bgImage.value = s.bg_image
    if (s.dynamic_bg != null) dynamicBg.value = s.dynamic_bg
    if (s.dynamic_bg_mode) dynamicBgMode.value = s.dynamic_bg_mode
    // 其他
    if (s.overwrite != null) overwrite.value = s.overwrite
    if (s.random_order != null) randomOrder.value = s.random_order
  }
  if (e.ai?.enabled) {
    useAI.value = true
    if (e.ai.service) aiService.value = e.ai.service
    if (e.ai.duration) aiDuration.value = e.ai.duration
    if (e.ai.api_key) aiApiKey.value = e.ai.api_key
    if (e.ai.prompt) aiPrompt.value = e.ai.prompt
  } else if (e.ai && e.ai.enabled === false) {
    useAI.value = false
  }

  // 如果有目录，自动扫描
  if (e.videoDir) scanDir()
  ElMessage.success('已应用历史设置')
}

// 字体
function updateFontPreview() {}
async function importFont() {
  const res = await browseApi.file({ type: 'all' })
  if (res.path) {
    await videoApi.fontsImport({ source: res.path })
    await store.loadFonts()
    fonts.value = store.fonts || []
    ElMessage.success('字体已导入')
  }
}
</script>

<style scoped>
.hint { font-size:11px;color:#888;margin-top:4px;display:block; }
.img-card { border:2px solid transparent;border-radius:8px;cursor:pointer;transition:all .15s; }
.img-card:hover { border-color:#0891b2; }
.img-card.selected { border-color:#0891b2;background:rgba(8,145,178,.08); }
</style>
