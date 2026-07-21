<template>
  <div>
    <h1>🎬 AI 视频生成</h1>
    <p style="color:#888;margin-bottom:20px;">从已爬取的图片生成视频，可选 Logo 水印与 AI 动态效果</p>

    <div style="display:flex;gap:12px;align-items:flex-start;">
      <div style="flex:1;min-width:0;">

        <!-- 选择目录 -->
        <el-form-item label="📂 选择图片目录">
          <div v-if="isLocalhost()" style="display:flex;gap:8px;">
            <el-input v-model="videoDir" placeholder="例如：F:\images\google_ads\com.spotify.music" style="flex:1;min-width:0;" />
            <el-button @click="browseFolder" style="width:44px;">📂</el-button>
            <el-button type="primary" @click="scanDir" :loading="scanning">🔍 扫描</el-button>
          </div>
          <div v-else style="display:flex;gap:8px;">
            <el-select v-model="selectedPkg" placeholder="选择已爬取包" @change="onPkgSelect" style="flex:1;" filterable>
              <el-option v-for="p in remotePackages" :key="p.path" :label="`${p.name} (${p.image_count}张)`" :value="p.path" />
            </el-select>
          </div>
          <span class="hint">{{ isLocalhost() ? '选择已爬取的包名文件夹（包含 PNG 图片和 包logo 子目录）' : '选择已爬取的包，自动扫描图片' }}</span>
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
          <div v-if="useLogo" style="display:flex;gap:12px;margin-top:8px;flex-wrap:wrap;">
            <el-form-item label="位置" style="flex:1;min-width:120px;margin-bottom:0;">
              <el-select v-model="logoPosition" size="small">
                <el-option label="右上" value="top-right" /><el-option label="左上" value="top-left" />
                <el-option label="左下" value="bottom-left" /><el-option label="右下" value="bottom-right" />
                <el-option label="浮动" value="floating" />
              </el-select>
            </el-form-item>
            <el-form-item label="效果" style="flex:1;min-width:130px;margin-bottom:0;">
              <el-select v-model="logoEffect" size="small">
                <el-option label="静态" value="static" /><el-option label="淡入淡出" value="fade" />
                <el-option label="浮动弹跳" value="bounce" /><el-option label="放大进入" value="zoom-in" />
                <el-option label="从右滑入" value="slide-right" /><el-option label="脉冲缩放" value="pulse" />
              </el-select>
            </el-form-item>
            <el-form-item style="flex:2;min-width:180px;margin-bottom:0;">
              <template #label><span style="font-size:12px;">大小 {{ logoSize }}%</span></template>
              <el-slider v-model="logoSize" :min="8" :max="25" size="small" show-stops />
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
            <el-button v-if="isLocalhost()" @click="browseBgImage" style="width:44px;">📂</el-button>
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
          <el-form-item label="背景音乐（可选）">
            <div v-if="isLocalhost()" style="display:flex;gap:4px;">
              <el-input v-model="musicPath" size="small" placeholder="F:\music\bg.mp3" style="flex:1;min-width:0;" />
              <el-button @click="browseMusic" size="small" style="width:36px;flex-shrink:0;">📂</el-button>
            </div>
            <div v-else>
              <div style="display:flex;gap:6px;align-items:center;">
                <el-select v-model="musicPath" placeholder="选音乐或留空" clearable size="small" style="flex:1;" @change="onMusicSelect">
                  <el-option v-for="m in musicFiles" :key="m.path" :label="m.name" :value="m.path" />
                </el-select>
                <el-button v-if="isPlaying" @click="stopMusic" size="small">⏹</el-button>
              </div>
              <div style="display:flex;gap:6px;margin-top:6px;">
                <input type="file" accept=".mp3,.wav,.aac,.m4a,.ogg,.flac" @change="onMusicFileChange" ref="musicFileInput" style="display:none;" />
                <el-button size="small" @click="$refs.musicFileInput.click()">选择文件</el-button>
                <el-button size="small" type="primary" @click="uploadMusic" :loading="uploadingMusic">上传</el-button>
              </div>
              <audio ref="audioPlayer" style="display:none;" />
            </div>
          </el-form-item>
        </div>

        <!-- 输出路径（远程隐藏，自动生成） -->
        <el-form-item v-if="isLocalhost()" label="输出路径">
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
            <el-button v-if="isLocalhost()" size="small" @click="importFont" style="width:36px;">📂</el-button>
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
          <el-button v-if="generatedPath && !generating" link size="small" type="primary" @click="downloadVideo" style="margin-left:8px;">📥 下载视频</el-button>
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
import { ref, reactive, computed, onMounted, onUnmounted, watch, watchEffect } from 'vue'
import { useVideoStore } from '@/stores/video'
import { useTaskStore } from '@/stores/taskRunner'
import { videoApi } from '@/api/video'
import { browseApi } from '@/api/browse'
import { isLocalhost } from '@/utils/env'
import { ElMessage } from 'element-plus'

const store = useVideoStore()
const taskStore = useTaskStore()

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
const logoSize = ref(16)

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
const generatedPath = ref('')
const generating = ref(false)
let pollTimer = null
let pollAborted = false

// 任务队列
const taskQueue = ref([])

// 历史
const history = ref({})
const activeHistoryId = ref(null)

// 远程用户
const remotePackages = ref([])
const selectedPkg = ref('')
const musicFiles = ref([])
const selectedMusicFile = ref(null)
const uploadingMusic = ref(false)
const isPlaying = ref(false)
const audioPlayer = ref(null)
const musicFileInput = ref(null)

onMounted(async () => {
  await store.loadFonts()
  fonts.value = store.fonts || []
  await loadHistory()
  // 远程用户加载包列表和音乐列表
  if (!isLocalhost()) {
    loadRemotePackages()
    loadMusicList()
  }
  // 1) 首先尝试恢复上次未提交的表单（任何场景都适用）
  await restoreFormState()
  // 2) 爬取页面桥接目录（优先级高于表单恢复）
  const bridgeDir = sessionStorage.getItem('bridgeVideoDir')
  if (bridgeDir) {
    videoDir.value = bridgeDir
    if (!isLocalhost()) selectedPkg.value = bridgeDir
    sessionStorage.removeItem('bridgeVideoDir')
    await scanDir()
  }
  // 3) 活跃任务恢复（优先级最高：用 meta 中的目录覆盖）
  const videoTasks = taskStore.visibleTasks.filter(t => t.type === 'video')
  if (videoTasks.length > 0) {
    const latest = videoTasks[0]
    if (latest.meta?.videoDir) {
      videoDir.value = latest.meta.videoDir
      if (latest.meta.outputPath) outputPath.value = latest.meta.outputPath
      await scanDir()
    }
    if (latest.status === 'running') {
      generating.value = true
      progressPct.value = latest.progress || 0
      progressMsg.value = latest.message || '正在重新连接...'
      pollLocalTask(latest)
    } else if (latest.status === 'completed') {
      generating.value = false
      generatedPath.value = latest.result?.output?.path || ''
      progressMsg.value = latest.message || '✅ 已完成'
      progressPct.value = 1
    } else if (latest.status === 'error') {
      generating.value = false
      progressMsg.value = latest.message || '❌ 任务失败'
    }
  }
})

onUnmounted(() => {
  pollAborted = true
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
  // 始终保存表单（不管是否在生成中）
  _saveFormNow()
})

// ========== 表单持久化（实时保存 + 挂载恢复）==========
const FORM_KEY = 'gg_video_form'

// 挂载时恢复
async function restoreFormState() {
  try {
    const raw = sessionStorage.getItem(FORM_KEY)
    if (!raw) return
    const f = JSON.parse(raw)
    if (f.videoDir) videoDir.value = f.videoDir
    if (f.outputPath) outputPath.value = f.outputPath
    if (f.bgImage != null) bgImage.value = f.bgImage
    if (f.bgColor) bgColor.value = f.bgColor
    dynamicBg.value = f.dynamicBg || false
    if (f.dynamicBgMode) dynamicBgMode.value = f.dynamicBgMode
    if (f.contentScale) contentScale.value = f.contentScale
    if (f.frameDuration) frameDuration.value = f.frameDuration
    if (f.transition) transition.value = f.transition
    if (f.resolution) resolution.value = f.resolution
    if (f.musicPath != null) musicPath.value = f.musicPath
    if (f.text1 != null) text1.value = f.text1
    if (f.text2 != null) text2.value = f.text2
    if (f.textFont) textFont.value = f.textFont
    useLogo.value = f.useLogo || false
    if (f.logoPosition) logoPosition.value = f.logoPosition
    if (f.logoEffect) logoEffect.value = f.logoEffect
    useAI.value = f.useAI || false
    if (f.aiService) aiService.value = f.aiService
    if (f.aiDuration) aiDuration.value = f.aiDuration
    if (f.aiApiKey) aiApiKey.value = f.aiApiKey
    if (f.aiPrompt) aiPrompt.value = f.aiPrompt
    if (f.randomOrder) randomOrder.value = f.randomOrder
    if (f.overwrite) overwrite.value = f.overwrite
    if (f.videoDir) {
      await scanDir()
      if (f.selectedImgs) selectedImgs.value = f.selectedImgs
    }
  } catch {}
}

// 统一保存函数（watchEffect + onUnmounted 共用）
function _saveFormNow() {
  const form = {
    videoDir: videoDir.value,
    outputPath: outputPath.value,
    bgImage: bgImage.value, bgColor: bgColor.value,
    dynamicBg: dynamicBg.value, dynamicBgMode: dynamicBgMode.value,
    contentScale: contentScale.value, frameDuration: frameDuration.value,
    transition: transition.value, resolution: resolution.value,
    musicPath: musicPath.value, text1: text1.value, text2: text2.value,
    textFont: textFont.value, useLogo: useLogo.value,
    logoPosition: logoPosition.value, logoEffect: logoEffect.value,
    useAI: useAI.value, aiService: aiService.value,
    aiDuration: aiDuration.value, aiApiKey: aiApiKey.value,
    aiPrompt: aiPrompt.value, randomOrder: randomOrder.value,
    overwrite: overwrite.value,
    selectedImgs: { ...selectedImgs.value },
  }
  try { sessionStorage.setItem(FORM_KEY, JSON.stringify(form)) } catch {}
}
// 实时保存（任何表单字段变化 → 写 sessionStorage）
watchEffect(() => { if (!generating.value) _saveFormNow() })

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

// 远程——加载包列表
async function loadRemotePackages() {
  try {
    const res = await videoApi.packages()
    remotePackages.value = res.packages || []
  } catch(e) { /* 静默 */ }
}

// 远程——加载音乐列表
async function loadMusicList() {
  try {
    const res = await videoApi.musicList()
    musicFiles.value = res.files || []
  } catch(e) { /* 静默 */ }
}

// 远程——选择包后自动扫描
async function onPkgSelect(path) {
  if (!path) return
  videoDir.value = path
  await scanDir()
}

// 远程——选音乐后自动播放
function onMusicSelect(path) {
  stopMusic()
  if (!path) return
  const audio = audioPlayer.value
  if (!audio) return
  audio.src = '/api/audio?path=' + encodeURIComponent(path)
  audio.play().then(() => { isPlaying.value = true }).catch(() => {})
  audio.onended = () => { isPlaying.value = false }
  audio.onerror = () => { isPlaying.value = false }
}

// 远程——停止音乐
function stopMusic() {
  const audio = audioPlayer.value
  if (audio) { audio.pause(); audio.currentTime = 0 }
  isPlaying.value = false
}

// 远程——文件选择
function onMusicFileChange(e) {
  selectedMusicFile.value = e.target.files?.[0] || null
}

// 远程——上传音乐
async function uploadMusic() {
  if (!selectedMusicFile.value) { ElMessage.warning('请先选择文件'); return }
  uploadingMusic.value = true
  try {
    const formData = new FormData()
    formData.append('file', selectedMusicFile.value)
    await videoApi.uploadMusic(formData)
    ElMessage.success('上传成功')
    selectedMusicFile.value = null
    if (musicFileInput.value) musicFileInput.value.value = ''
    await loadMusicList()
  } catch(e) { ElMessage.error('上传失败: ' + (e.message || '未知错误')) }
  uploadingMusic.value = false
}

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
      logo_path: (useLogo.value && logo.value) ? logo.value.path : undefined,
      logo_position: logoPosition.value,
      logo_effect: logoEffect.value,
      logo_size: logoSize.value,
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

function doGenerate(settings) {
  generating.value = true
  progressPct.value = 0
  progressMsg.value = '提交中...'

  return store.generate(settings).then(res => {
    const tid = res.task_id
    // 注册到全局任务 Store，附带页面上下文用于恢复
    const label = (settings.name || outputPath.value || '未命名')
    const innerId = taskStore.addTask('video', label, tid)
    // 保存页面上下文：目录 + 输出路径，切换页面回来后可重建
    taskStore.updateTask(innerId, {
      meta: { videoDir: videoDir.value, outputPath: outputPath.value },
    })

    return new Promise((resolve) => {
      let done = false
      const poll = () => {
        if (done) return
        store.checkProgress(tid).then(p => {
          if (pollAborted || done) return
          progressPct.value = p.progress || 0
          progressMsg.value = p.message || '处理中...'
          // 同步更新全局 Store
          taskStore.updateTask(innerId, {
            status: 'running',
            progress: p.progress || 0,
            message: p.message || '处理中...',
          })
          if (p.status === 'completed') {
            done = true
            generating.value = false
            generatedPath.value = p.output?.path || ''
            progressMsg.value = '✅ 完成: ' + (p.output?.path || '')
            taskStore.updateTask(innerId, {
              status: 'completed', progress: 1,
              message: '✅ 完成: ' + (p.output?.path || ''),
              result: p, finishedAt: Date.now(),
            })
            ElMessage.success('视频生成完成')
            autoSaveHistory()
            resolve()
          } else if (p.status === 'error') {
            done = true
            generating.value = false
            progressMsg.value = '❌ ' + (p.message || '未知错误')
            taskStore.updateTask(innerId, {
              status: 'error',
              message: p.message || '未知错误',
              error: p.message, finishedAt: Date.now(),
            })
            ElMessage.error(p.message || '未知错误')
            resolve()
          } else {
            pollTimer = setTimeout(poll, 2000)
          }
        }).catch(() => {
          if (!pollAborted && !done) pollTimer = setTimeout(poll, 2000)
        })
      }
      poll()
    })
  }).catch(e => {
    generating.value = false
    ElMessage.error(e.message || '提交任务失败')
  })
}

/**
 * 恢复本地轮询——用于页面挂载后重新连接全局 Store 中的活跃任务。
 * 全局轮询更新 store，本地 watch 同步 UI。
 */
function pollLocalTask(latest) {
  const tid = latest.taskId
  if (!tid) return

  let done = false
  const poll = () => {
    if (done) return
    store.checkProgress(tid).then(p => {
      if (pollAborted || done) return
      progressPct.value = p.progress || 0
      progressMsg.value = p.message || '处理中...'
      taskStore.updateTask(latest.id, {
        progress: p.progress || 0,
        message: p.message || '',
        status: 'running',
      })
      if (p.status === 'completed') {
        done = true
        generating.value = false
        generatedPath.value = p.output?.path || ''
        progressMsg.value = '✅ 完成: ' + (p.output?.path || '')
        taskStore.updateTask(latest.id, {
          status: 'completed', progress: 1,
          message: '✅ 完成', result: p, finishedAt: Date.now(),
        })
        ElMessage.success('视频生成完成')
        autoSaveHistory()
      } else if (p.status === 'error') {
        done = true
        generating.value = false
        progressMsg.value = '❌ ' + (p.message || '未知错误')
        taskStore.updateTask(latest.id, {
          status: 'error',
          message: p.message || '未知错误',
          error: p.message, finishedAt: Date.now(),
        })
        ElMessage.error(p.message || '未知错误')
      } else {
        pollTimer = setTimeout(poll, 2000)
      }
    }).catch(() => {
      if (!pollAborted && !done) pollTimer = setTimeout(poll, 2000)
    })
  }
  poll()
}

function downloadVideo() {
  if (generatedPath.value) {
    window.open('/api/video/download?path=' + encodeURIComponent(generatedPath.value), '_blank')
  }
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
    if (s.logo_size) logoSize.value = s.logo_size
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
