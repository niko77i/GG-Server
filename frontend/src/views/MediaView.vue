<template>
  <div class="media-root">
    <h1>🎬 媒体工具</h1>

    <!-- ===== ① 爬取图片 ===== -->
    <div class="section">
      <h3>📥 爬取图片</h3>
      <el-form label-position="top">
        <el-form-item label="Google Play 链接">
          <el-input v-model="urls" type="textarea" :rows="4" placeholder="每行一个链接，或用逗号分隔" />
        </el-form-item>
        <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;">
          <el-form-item label="保存路径" style="flex:1;min-width:200px;">
            <div style="display:flex;gap:6px;">
              <el-input v-model="saveDir" :placeholder="isLocalhost() ? '例如：F:\\images\\google_ads\\' : '留空则使用服务器默认目录'" size="small" />
              <el-button v-if="isLocalhost()" @click="browseFolder" style="width:36px;">📂</el-button>
            </div>
          </el-form-item>
          <el-form-item style="min-width:80px;">
            <el-checkbox v-model="includeAds" size="small">按 Google Ads 规格放大图片</el-checkbox>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="startScrape" :loading="scraping" :disabled="!urls">开始爬取</el-button>
          </el-form-item>
        </div>
      </el-form>

      <div v-if="scrapeResults.length" style="margin-top:12px;">
        <div v-if="scrapeSummary" style="padding:8px 12px;background:#ecfdf5;border-radius:6px;margin-bottom:8px;font-size:12px;">{{ scrapeSummary }}</div>
        <div v-for="r in scrapeResults" :key="r.url"
          class="scrape-result-row"
          :style="{ borderColor: r.error ? '#dc2626' : r.image_count ? '#059669' : '#0891b2' }">
          <span>{{ r.loading ? '⏳' : r.error ? '❌' : '✅' }}</span>
          <span style="flex:1;">{{ r.package_name || r.url }}<template v-if="r.image_count"> — {{ r.image_count }} 张</template></span>
          <el-button v-if="!r.error && r.saved_path" link size="small" @click="downloadImages(r)">📥</el-button>
          <el-button v-if="!r.error && r.saved_path" link size="small" type="primary" @click="loadPackage(r.saved_path)">🎬 生成视频</el-button>
        </div>
      </div>
    </div>

    <!-- ===== ②+③ 双栏布局 ===== -->
    <div style="display:flex;gap:16px;align-items:flex-start;">
    <div style="flex:1;min-width:0;">

    <!-- ===== ② 图片预览 ===== -->
    <div class="section">
      <h3>🖼️ 图片预览</h3>
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap;">
        <!-- 用户切换（管理员） -->
        <el-select v-if="authStore.isAdmin" v-model="selectedUserDn" placeholder="选择用户" @change="onUserChange" size="small" style="width:140px;" clearable>
          <el-option v-for="u in scrapeUsers" :key="u.display_name" :label="`${u.display_name} (${u.package_count})`" :value="u.display_name" />
        </el-select>
        <!-- 包下拉框 -->
        <el-select v-model="videoDir" placeholder="选择已爬取包" @change="scanDir" size="small" style="flex:1;min-width:180px;" filterable>
          <el-option v-for="p in remotePackages" :key="p.path" :label="`${p.name} (${p.image_count}张)`" :value="p.path" />
        </el-select>
        <span v-if="!remotePackages.length" style="font-size:11px;color:#999;">暂无数据，请先爬取或上传</span>
      </div>
      <!-- 本机用户：手动输入路径 -->
      <div v-if="isLocalhost()" style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
        <el-input v-model="manualDir" placeholder="或手动输入图片目录路径" size="small" style="flex:1;min-width:200px;" />
        <el-button @click="browseManualFolder" size="small" style="width:36px;">📂</el-button>
        <el-button type="primary" @click="doManualScan" :loading="scanning" size="small">🔍 扫描</el-button>
      </div>

      <!-- 上传区域 -->
      <div style="margin:12px 0;">
        <div
          style="border:2px dashed #ddd;border-radius:8px;padding:20px;text-align:center;cursor:pointer;transition:all .2s;"
          :style="{ borderColor: dragOver ? '#0891b2' : '#ddd', background: dragOver ? '#f0f9ff' : '#fafafa' }"
          @click="$refs.imageFileInput.click()"
          @dragover.prevent="dragOver = true"
          @dragleave="dragOver = false"
          @drop.prevent="onImageDrop"
        >
          <div style="font-size:28px;margin-bottom:4px;">📁</div>
          <div style="font-size:12px;color:#666;">拖拽图片到此处 或 点击上传</div>
          <div style="font-size:10px;color:#aaa;">支持 PNG / JPG / WebP / BMP</div>
        </div>
        <input type="file" accept="image/*" multiple @change="onImageFileChange" ref="imageFileInput" style="display:none;" />
        <div v-if="pendingImages.length" style="margin-top:8px;display:flex;gap:6px;align-items:center;">
          <span style="font-size:12px;color:#666;">已选择 {{ pendingImages.length }} 张</span>
          <el-button size="small" type="primary" @click="doUploadImages" :loading="uploadingImages">上传并加载</el-button>
        </div>
      </div>

      <!-- 排序面板：拖拽调整图片顺序 -->
      <div v-if="orderedImages.length" style="margin-top:4px;margin-bottom:8px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
          <span style="font-size:12px;font-weight:600;">📸 视频图片顺序（{{ orderedImages.length }} 张，拖拽调整）</span>
          <el-button link size="small" @click="shuffleOrdered">🎲 随机排序</el-button>
          <el-button link size="small" type="danger" @click="clearOrdered">🗑 清空</el-button>
        </div>
        <div style="display:flex;gap:6px;overflow-x:auto;padding:8px;background:#f8fafc;border:1px dashed #cbd5e1;border-radius:6px;min-height:70px;align-items:center;">
          <div v-for="(img, i) in orderedImages" :key="img.filename"
            class="sort-card"
            draggable="true"
            @dragstart="onDragStart($event, i)"
            @dragover.prevent="onDragOver($event, i)"
            @dragend="onDragEnd"
            @drop="onDrop($event, i)"
            :class="{ 'drag-over': dragOverIndex === i, 'dragging': dragIndex === i }"
            style="width:80px;flex-shrink:0;cursor:grab;border:2px solid #e2e8f0;border-radius:6px;overflow:hidden;background:#fff;transition:transform .15s;position:relative;">
            <el-image :src="'/api/image?path=' + encodeURIComponent(img.path)" fit="cover" style="width:80px;height:50px;pointer-events:none;" />
            <div style="padding:2px 4px;font-size:9px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:center;">{{ i + 1 }}. {{ img.filename }}</div>
            <span @click.stop="removeFromOrdered(img.filename)"
              style="position:absolute;top:1px;right:2px;cursor:pointer;font-size:12px;color:#ef4444;line-height:1;background:rgba(255,255,255,0.9);border-radius:50%;width:16px;height:16px;text-align:center;">✕</span>
          </div>
          <span v-if="!orderedImages.length" style="font-size:11px;color:#999;width:100%;text-align:center;">点击下方图片添加到排序面板</span>
        </div>
      </div>

      <div v-if="images.length" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;">
        <div v-for="img in images" :key="img.filename" class="img-card" :class="{ selected: selectedImgs[img.filename] }" @click="toggleImg(img.filename)">
          <el-image :src="'/api/image?path=' + encodeURIComponent(img.path)" fit="cover" style="aspect-ratio:16/10;border-radius:4px 4px 0 0;" />
          <div style="padding:3px 6px;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ img.filename }}</div>
        </div>
      </div>
      <div v-if="images.length" style="margin-top:6px;display:flex;gap:8px;align-items:center;">
        <el-checkbox v-model="randomOrder" size="small" @change="onRandomOrderChange">随机排序</el-checkbox>
        <el-button link size="small" @click="toggleSelectAll">{{ allSelected ? '☑ 取消全选' : '☑ 全选' }}</el-button>
        <span style="font-size:11px;color:#888;">已选 {{ Object.values(selectedImgs).filter(Boolean).length }} / {{ images.length }}</span>
      </div>
    </div>

    <!-- ===== ③ 视频生成 ===== -->
    <div class="section">
      <h3>🎬 视频生成</h3>
      <div v-if="!images.length" style="text-align:center;padding:40px 20px;color:#999;font-size:14px;">
        <div style="font-size:32px;margin-bottom:8px;">🖼️</div>
        请先爬取图片或选择已有的包扫描图片
      </div>
      <div v-if="images.length">
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;">

        <!-- Logo -->
        <div v-if="logo" class="sub-section">
          <el-tooltip :content="logo.filename" placement="top" :show-after="300">
            <el-checkbox v-model="useLogo"><span style="display:inline-block;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:bottom;">🏷️ Logo 叠加（{{ logo.filename }}）</span></el-checkbox>
          </el-tooltip>
          <div v-if="useLogo" style="display:flex;gap:8px;margin-top:8px;">
            <el-select v-model="logoPosition" size="small" style="flex:1;">
              <el-option label="右上" value="top-right" /><el-option label="左上" value="top-left" />
              <el-option label="左下" value="bottom-left" /><el-option label="右下" value="bottom-right" />
              <el-option label="浮动" value="floating" />
            </el-select>
            <el-select v-model="logoEffect" size="small" style="flex:1;">
              <el-option label="静态" value="static" /><el-option label="淡入淡出" value="fade" />
              <el-option label="浮动弹跳" value="bounce" /><el-option label="放大进入" value="zoom-in" />
              <el-option label="从右滑入" value="slide-right" /><el-option label="脉冲缩放" value="pulse" />
            </el-select>
          </div>
        </div>

        <!-- AI -->
        <div class="sub-section">
          <el-checkbox v-model="useAI">🤖 AI 动态化（可选）</el-checkbox>
          <div v-if="useAI" style="margin-top:8px;">
            <div style="display:flex;gap:8px;">
              <el-select v-model="aiService" size="small" style="flex:1;">
                <el-option label="豆包 Seedance 1.5 Pro" value="doubao" />
                <el-option label="豆包 Seedance 1.0 Pro Fast" value="doubao-fast" />
                <el-option label="Seedance 2.0" value="seedance" />
                <el-option label="Veo 3.1 Lite" value="veo" />
                <el-option label="Atlas Cloud" value="atlas" />
              </el-select>
              <el-select v-model="aiDuration" size="small" style="width:100px;">
                <el-option label="3s" :value="3" /><el-option label="4s" :value="4" /><el-option label="5s" :value="5" /><el-option label="8s" :value="8" />
              </el-select>
            </div>
            <el-input v-model="aiApiKey" type="password" size="small" placeholder="API Key" style="margin-top:6px;" />
            <el-input v-model="aiPrompt" size="small" placeholder="视频效果描述（可选）" style="margin-top:6px;" />
          </div>
        </div>

        <!-- 背景设置 -->
        <div class="sub-section" style="margin-top:8px;">
          <el-form-item label="🖼️ 背景图片（可选）" style="margin-bottom:6px;">
            <div style="display:flex;gap:6px;">
              <el-input v-model="bgImage" placeholder="留空则使用纯色背景" size="small" style="flex:1;min-width:0;" />
              <el-button v-if="isLocalhost()" @click="browseBgImage" size="small" style="width:36px;flex-shrink:0;">📂</el-button>
            </div>
          </el-form-item>
          <div v-if="!bgImage" style="display:flex;gap:12px;align-items:center;">
            <el-form-item label="背景颜色" style="margin-bottom:0;flex:1;">
              <div style="display:flex;align-items:center;gap:8px;">
                <el-color-picker v-model="bgColor" size="small" />
                <el-checkbox v-model="dynamicBg" size="small">动态背景</el-checkbox>
                <el-select v-if="dynamicBg" v-model="dynamicBgMode" size="small" style="width:100px;">
                  <el-option label="呼吸" value="breathe" /><el-option label="波浪" value="wave" />
                  <el-option label="律动" value="beat" /><el-option label="流光" value="flow" />
                </el-select>
              </div>
            </el-form-item>
          </div>
        </div>

        <!-- 视频设置 -->
        <div class="sub-section">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <el-form-item label="单帧时长" style="margin-bottom:0;"><el-select v-model="frameDuration" size="small" style="width:100%;"><el-option v-for="d in [3,4,5]" :key="d" :label="d+'秒'" :value="d" /></el-select></el-form-item>
            <el-form-item label="输出分辨率" style="margin-bottom:0;"><el-select v-model="resolution" size="small" style="width:100%;"><el-option label="9:16 竖屏" value="1080:1920" /><el-option label="1:1 方形" value="1080:1080" /></el-select></el-form-item>
            <el-form-item label="转场效果" style="margin-bottom:0;"><el-select v-model="transition" size="small" style="width:100%;">
              <el-option label="淡入淡出" value="fade" /><el-option label="黑场过渡" value="fadeblack" /><el-option label="白场过渡" value="fadewhite" />
              <el-option label="向右滑动" value="slideright" /><el-option label="向左滑动" value="slideleft" />
              <el-option label="向上滑动" value="slideup" /><el-option label="向下滑动" value="slidedown" />
              <el-option label="缩放" value="zoomin" /><el-option label="溶解" value="dissolve" />
              <el-option label="像素化" value="pixelize" /><el-option label="圆形展开" value="circleopen" /><el-option label="圆形收缩" value="circleclose" />
              <el-option label="擦除" value="wiperight" /><el-option label="无" value="none" />
            </el-select></el-form-item>
            <el-form-item label="内容缩放" style="margin-bottom:0;"><el-select v-model="contentScale" size="small" style="width:100%;"><el-option label="70%" value="0.70" /><el-option label="82%" value="0.82" /><el-option label="92%" value="0.92" /><el-option label="100%" value="1.00" /></el-select></el-form-item>
          </div>
        </div>
      </div>

      <!-- 音乐 -->
      <div class="sub-section" style="margin-top:12px;">
        <el-form-item label="背景音乐（可选）" style="margin-bottom:8px;">
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
            <template v-if="isLocalhost()">
              <el-input v-model="musicPath" size="small" placeholder="F:\music\bg.mp3" style="flex:1;min-width:140px;" />
              <el-button @click="browseMusic" size="small" style="width:36px;flex-shrink:0;">📂</el-button>
            </template>
            <template v-else>
              <el-select v-model="musicPath" placeholder="选音乐或留空" clearable size="small" style="flex:1;min-width:140px;" @change="onMusicSelect">
                <el-option v-for="m in musicFiles" :key="m.path" :label="m.name" :value="m.path" />
              </el-select>
              <el-button v-if="isPlaying" @click="stopMusic" size="small">⏹</el-button>
              <input type="file" accept=".mp3,.wav,.aac,.m4a,.ogg,.flac,.mp4" multiple @change="onMusicFileChange" ref="musicFileInput" style="display:none;" />
              <el-button size="small" @click="$refs.musicFileInput.click()">{{ selectedMusicFiles.length ? `已选 ${selectedMusicFiles.length} 个` : '选择文件' }}</el-button>
              <el-button size="small" type="primary" @click="uploadMusic" :loading="uploadingMusic" :disabled="!selectedMusicFiles.length">上传</el-button>
            </template>
          </div>
          <audio ref="audioPlayer" style="display:none;" />
        </el-form-item>
      </div>

      <!-- 文案 -->
      <div class="sub-section" style="margin-top:12px;">
        <el-form-item label="📝 文案浮层（最多两条）" style="margin-bottom:8px;">
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <el-input v-model="text1" placeholder="文案 1" size="small" style="flex:1;min-width:100px;" />
            <el-input v-model="text2" placeholder="文案 2" size="small" style="flex:1;min-width:100px;" />
            <el-select v-model="textFont" size="small" style="width:120px;" @change="onFontChange">
              <el-option v-for="f in fonts" :key="f.id" :label="f.name" :value="f.id" />
            </el-select>
            <input type="file" accept=".ttf,.otf,.ttc,.woff,.woff2" multiple @change="onFontFileChange" ref="fontFileInput" style="display:none;" />
            <el-button size="small" @click="$refs.fontFileInput.click()">{{ pendingFonts.length ? `已选 ${pendingFonts.length} 个` : '选择字体' }}</el-button>
            <el-button size="small" type="primary" @click="uploadFonts" :loading="uploadingFonts" :disabled="!pendingFonts.length">上传</el-button>
          </div>
          <div v-if="(text1 || text2) && fontLoaded" style="margin-top:10px;padding:10px 14px;background:#fff;border:1px solid #e5e7eb;border-radius:4px;border-left:3px solid #0891b2;">
            <div style="font-size:10px;color:#999;margin-bottom:4px;">预览效果</div>
            <div style="font-size:18px;line-height:1.6;color:#1f2937;" :style="{ fontFamily: previewFontFamily }">
              <span v-if="text1">{{ text1 }}</span>
              <span v-if="text1 && text2" style="margin:0 6px;">|</span>
              <span v-if="text2">{{ text2 }}</span>
            </div>
          </div>
          <span class="hint" style="font-size:11px;color:#888;">每条随机浮现 2-3 秒，淡入淡出 + 阴影描边</span>
        </el-form-item>
      </div>

      <!-- 输出 + 操作 -->
      <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-top:12px;">
        <el-form-item v-if="isLocalhost()" label="输出路径" style="flex:1;min-width:200px;margin-bottom:0;">
          <div style="display:flex;gap:6px;">
            <el-input v-model="outputPath" placeholder="例如：F:\output\video.mp4" @blur="outputPath = ensureMp4(outputPath)" size="small" />
            <el-button @click="browseSave" size="small" style="width:36px;">📂</el-button>
          </div>
        </el-form-item>
        <div style="display:flex;gap:8px;">
          <el-checkbox v-model="overwrite" size="small">覆盖已有</el-checkbox>
          <el-button @click="addToQueue" size="small">📋 添加到队列</el-button>
          <el-button type="primary" @click="startGenerate" size="small">🎬 生成视频</el-button>
        </div>
      </div>

      <!-- 任务队列 + 进度 -->
      <div v-if="taskQueue.length" style="margin-top:12px;">
        <el-tag v-for="(t,i) in taskQueue" :key="i" size="small" style="margin:2px;" closable @close="removeFromQueue(i)">{{ t.name || '任务 '+(i+1) }}</el-tag>
        <el-button type="success" @click="generateAll" size="small" style="margin-top:6px;" :disabled="generatingBatch || !taskQueue.length">⚡ 一键生成全部</el-button>
      </div>
      <div v-if="progressMsg" style="margin-top:12px;">
        <el-progress :percentage="Math.round(progressPct * 100)" />
        <div style="font-size:12px;color:#888;">{{ progressMsg }}</div>
        <div v-if="generatedPaths.length" style="display:flex;flex-wrap:wrap;gap:4px;max-height:120px;overflow-y:auto;margin-top:4px;padding:4px;background:#f9fafb;border-radius:4px;">
          <el-button v-for="(p, i) in generatedPaths" :key="i" link size="small" type="primary" @click="downloadVideo(p)" style="font-size:11px;">📥 {{ pathBasename(p) }}</el-button>
          <el-button v-if="generatedPaths.length > 1" link size="small" type="info" @click="generatedPaths = []" style="font-size:10px;">清空列表</el-button>
        </div>
      </div>

    </div>
  </div>
</div>

      <!-- 右侧历史栏 -->
      <div style="width:220px;flex-shrink:0;position:sticky;top:20px;">
        <div style="border:1px solid #eee;border-radius:10px;padding:12px;background:#fff;">
          <h4 style="font-size:12px;margin:0 0 8px 0;">📋 历史设置（{{ historyCount }}）</h4>
          <div v-if="!historyCount" style="font-size:10px;color:#999;">暂无历史</div>
          <div v-for="(pkgs, username) in history" :key="username" style="margin-bottom:8px;">
            <div @click="toggleUserCollapse(username)"
              style="font-size:11px;font-weight:600;color:#0891b2;padding:3px 4px;background:#f0f9ff;border-radius:3px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;">
              <span>👤 {{ username === '_shared' ? '📦 旧数据（无用户）' : username }}</span>
              <span style="font-size:9px;color:#999;">{{ collapsedUsers[username] ? '▶' : '▼' }}</span>
            </div>
            <div v-show="!collapsedUsers[username]">
              <div v-for="(entries, pkg) in pkgs" :key="pkg" style="margin-bottom:6px;margin-left:4px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                  <strong style="font-size:10px;color:#666;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:130px;">{{ pkg }}</strong>
                  <el-button link size="small" type="danger" @click="deleteHistoryPkg(username, pkg)" style="font-size:9px;">✕</el-button>
                </div>
                <div v-for="(e,i) in (Array.isArray(entries) ? entries : [])" :key="i"
                  style="font-size:10px;padding:3px 6px;cursor:pointer;border-radius:3px;display:flex;justify-content:space-between;align-items:center;margin-top:2px;"
                  :style="{ background: e._id === activeHistoryId ? '#e6f7ff' : 'transparent' }">
                  <span @click="applyHistory(e)" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ e.name || e._saved_at || '-' }}</span>
                  <el-button link size="small" type="danger" @click.stop="deleteHistoryEntry(username, pkg, i)" style="font-size:9px;">✕</el-button>
                </div>
              </div>
            </div>
          </div>
          <el-button size="small" @click="saveHistory" style="width:100%;margin-top:6px;">💾 保存当前设置</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useVideoStore } from '@/stores/video'
import { useTaskStore } from '@/stores/taskRunner'
import { useAuthStore } from '@/stores/auth'
import { videoApi } from '@/api/video'
import { scrapeApi } from '@/api/scrape'
import { browseApi } from '@/api/browse'
import { isLocalhost } from '@/utils/env'
import { ElMessage } from 'element-plus'

const videoStore = useVideoStore()
const authStore = useAuthStore()
const taskStore = useTaskStore()

// ========== ① 爬取 ==========
const urls = ref('')
const saveDir = ref('')
const includeAds = ref(true)
const scraping = ref(false)
const scrapeResults = ref([])
const scrapeSummary = ref('')

async function browseFolder() {
  try {
    const res = await browseApi.folder({ initial_dir: saveDir.value || null })
    if (res.path) saveDir.value = res.path
  } catch(e) { ElMessage.error('选择文件夹失败: ' + e.message) }
}

function parseUrls(input) {
  const matches = input.match(/https?:\/\/play\.google\.com\/[^\s,;，；\n]+/gi)
  if (matches?.length) return matches
  return input.split(/[\n,]+/).map(s => s.trim()).filter(s => s.startsWith('http'))
}

async function startScrape() {
  const links = parseUrls(urls.value)
  if (!links.length) return
  scraping.value = true; scrapeSummary.value = ''
  scrapeResults.value = links.map(url => ({ url, loading: true, package_name: '', image_count: 0, error: '', saved_path: '' }))
  let successCount = 0, failCount = 0, totalImages = 0
  for (let i = 0; i < links.length; i++) {
    try {
      const res = await scrapeApi.scrape({ url: links[i], save_dir: saveDir.value, include_ads_images: includeAds.value })
      scrapeResults.value[i] = { url: links[i], package_name: res.package_name, image_count: res.image_count, error: '', saved_path: res.saved_path, from_cache: res.from_cache }
      successCount++; totalImages += (res.image_count || 0) + (res.logo ? 1 : 0)
    } catch (e) {
      scrapeResults.value[i] = { url: links[i], package_name: '', image_count: 0, error: e.message, saved_path: '' }
      failCount++
    }
  }
  scrapeSummary.value = `完成！成功 ${successCount}，失败 ${failCount}，共 ${totalImages} 张`
  scraping.value = false
  if (successCount === 1) {
    const pkg = scrapeResults.value.find(r => !r.error && r.saved_path)
    if (pkg) loadPackage(pkg.saved_path)
  }
}

function downloadImages(r) {
  window.open('/api/scrape/download?path=' + encodeURIComponent(r.saved_path), '_blank')
}

// ========== ② 图片预览 ==========
const videoDir = ref('')
const manualDir = ref('')
const scanning = ref(false)
const images = ref([])
const logo = ref(null)
const selectedImgs = ref({})
const orderedImages = ref([])  // 排序面板中的图片（有序）
const allSelected = ref(true)
const randomOrder = ref(false)
// 拖拽状态
const dragIndex = ref(-1)
const dragOverIndex = ref(-1)
const remotePackages = ref([])
const scrapeUsers = ref([])
const selectedUserDn = ref('')
const dragOver = ref(false)
const pendingImages = ref([])
const uploadingImages = ref(false)
const imageFileInput = ref(null)

function loadPackage(dirPath) {
  videoDir.value = dirPath
  scanDir()
}

async function browseManualFolder() {
  try {
    const res = await browseApi.folder({ initial_dir: manualDir.value || null })
    if (res.path) manualDir.value = res.path
  } catch(e) { ElMessage.error('选择文件夹失败: ' + e.message) }
}

function doManualScan() {
  if (!manualDir.value) { ElMessage.warning('请输入或选择图片目录'); return }
  videoDir.value = manualDir.value
  scanDir()
}

async function scanDir() {
  if (!videoDir.value) { ElMessage.warning('请先选择或输入图片目录'); return }
  scanning.value = true
  try {
    const res = await videoStore.scanDir(videoDir.value)
    images.value = res.images || []
    logo.value = res.logo
    toggleSelectAll(true)
    // 每次扫描新目录都自动填充输出路径（否则切换包名时旧路径残留导致名字对不上）
    const clean = videoDir.value.replace(/[\\/]+$/, '').replace(/\\/g, '/')
    const parts = clean.split('/')
    const pkg = parts[parts.length - 1]
    const parent = parts.slice(0, -1).join('/')
    let outPath = parent + '/ai/' + pkg + '.mp4'
    try { const check = await videoApi.nextFilename({ output_path: outPath }); if (check.path) outPath = check.path } catch(e) {}
    outputPath.value = outPath
  } catch(e) { ElMessage.error('扫描失败：' + (e.response?.data?.error || e.message || '未知错误')) }
  scanning.value = false
}

function toggleImg(filename) {
  const wasSelected = selectedImgs.value[filename]
  selectedImgs.value = { ...selectedImgs.value, [filename]: !wasSelected }
  allSelected.value = Object.keys(selectedImgs.value).length === images.value.length
  // 同步排序面板
  if (!wasSelected) {
    // 新选中：追加到排序面板末尾
    const img = images.value.find(i => i.filename === filename)
    if (img && !orderedImages.value.find(o => o.filename === filename)) {
      orderedImages.value.push({ filename: img.filename, path: img.path })
    }
  } else {
    // 取消选中：从排序面板移除
    orderedImages.value = orderedImages.value.filter(o => o.filename !== filename)
  }
}
function toggleSelectAll(force) {
  const s = {}
  const val = force !== undefined ? force : !allSelected.value
  if (val) {
    images.value.forEach(img => s[img.filename] = true)
    // 全选：排序面板同步为全部图片（保持当前网格顺序）
    orderedImages.value = images.value.map(img => ({ filename: img.filename, path: img.path }))
  } else {
    orderedImages.value = []
  }
  selectedImgs.value = s
  allSelected.value = val
}

// ---- 排序面板操作 ----
function removeFromOrdered(filename) {
  orderedImages.value = orderedImages.value.filter(o => o.filename !== filename)
  selectedImgs.value = { ...selectedImgs.value, [filename]: false }
  allSelected.value = false
}
function clearOrdered() {
  orderedImages.value = []
  selectedImgs.value = {}
  allSelected.value = false
}
function shuffleOrdered() {
  if (orderedImages.value.length > 0) {
    // 排序面板有图片 → 随机打乱
    const arr = [...orderedImages.value]
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]]
    }
    orderedImages.value = arr
  } else if (images.value.length > 0) {
    // 排序面板为空 → 把所有图片随机打乱塞入
    const arr = images.value.map(img => ({ filename: img.filename, path: img.path }))
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]]
    }
    orderedImages.value = arr
    // 同时全选
    const s = {}
    arr.forEach(img => s[img.filename] = true)
    selectedImgs.value = s
    allSelected.value = true
  }
}
function onRandomOrderChange(val) {
  // 勾选随机排序时自动填充排序面板
  if (val) shuffleOrdered()
}

// ---- 拖拽排序 ----
function onDragStart(e, i) {
  dragIndex.value = i
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', i.toString())
}
function onDragOver(e, i) {
  dragOverIndex.value = i
}
function onDrop(e, i) {
  const from = dragIndex.value
  if (from < 0 || from === i) return
  const arr = [...orderedImages.value]
  const [item] = arr.splice(from, 1)
  arr.splice(i, 0, item)
  orderedImages.value = arr
  dragIndex.value = -1
  dragOverIndex.value = -1
}
function onDragEnd() {
  dragIndex.value = -1
  dragOverIndex.value = -1
}

async function loadRemotePackages(userDn) {
  try {
    const res = await videoApi.packages(userDn || '')
    remotePackages.value = res.packages || []
  } catch(e) { console.error('加载包列表失败:', e) }
}
async function loadScrapeUsers() {
  if (!authStore.isAdmin) return
  try {
    const res = await videoApi.scrapeUsers()
    scrapeUsers.value = res.users || []
  } catch(e) { console.error('加载用户列表失败:', e) }
}
function onUserChange(dn) {
  videoDir.value = ''
  images.value = []
  logo.value = null
  loadRemotePackages(dn || '')
}

// 上传图片
function onImageDrop(e) {
  dragOver.value = false
  const files = e.dataTransfer?.files
  if (files?.length) pendingImages.value = Array.from(files)
}
function onImageFileChange(e) {
  const files = e.target?.files
  if (files?.length) pendingImages.value = Array.from(files)
}
async function doUploadImages() {
  if (!pendingImages.value.length) return
  uploadingImages.value = true
  try {
    const formData = new FormData()
    pendingImages.value.forEach(f => formData.append('files', f))
    const res = await videoApi.uploadImages(formData)
    ElMessage.success(`上传成功，${res.image_count} 张`)
    pendingImages.value = []
    if (imageFileInput.value) imageFileInput.value.value = ''
    // 自动加载
    loadPackage(res.saved_path)
    // 远程用户刷新包列表
    if (!isLocalhost()) loadRemotePackages(selectedUserDn.value || '')
  } catch (e) {
    ElMessage.error('上传失败: ' + (e.message || '未知错误'))
  }
  uploadingImages.value = false
}

// ========== ③ 视频生成 ==========
const useLogo = ref(false)
const logoPosition = ref('top-right')
const logoEffect = ref('static')
const useAI = ref(false)
const aiService = ref('doubao')
const aiDuration = ref(4)
const aiApiKey = ref('')
const aiPrompt = ref('')
const bgColor = ref('#f0ebe0')
const bgImage = ref('')
const dynamicBg = ref(false)
const dynamicBgMode = ref('breathe')
const contentScale = ref('0.82')
const frameDuration = ref(3)
const transition = ref('fade')
const resolution = ref('1080:1920')
const musicPath = ref('')
const outputPath = ref('')
const overwrite = ref(false)
const text1 = ref('')
const text2 = ref('')
const textFont = ref('simhei')
const fonts = ref([])

// 音乐（远程）
const musicFiles = ref([])
const uploadingMusic = ref(false)
const isPlaying = ref(false)
const audioPlayer = ref(null)
const musicFileInput = ref(null)

// 进度
const progressMsg = ref('')
const progressPct = ref(0)
const generatedPaths = ref([])  // 队列生成时累积所有输出路径
const generating = ref(false)
const generatingBatch = ref(false)  // 批量生成中（防止重复点击）
let pollTimer = null
let pollAborted = false

// 队列
const taskQueue = ref([])

onMounted(async () => {
  await videoStore.loadFonts()
  fonts.value = videoStore.fonts || []
  loadRemotePackages()
  loadMusicList()
  loadHistory()
  if (authStore.isAdmin) loadScrapeUsers()
  // 恢复活跃或刚完成的视频任务（切换页面后回来）
  const videoTasks = taskStore.visibleTasks.filter(t => t.type === 'video')
  if (videoTasks.length > 0) {
    const latest = videoTasks[0]
    if (latest.meta?.videoDir && !videoDir.value) {
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
      if (latest.result?.output?.path) generatedPaths.value.push(latest.result.output.path)
      progressMsg.value = latest.message || '✅ 已完成'
      progressPct.value = 1
    } else if (latest.status === 'error') {
      generating.value = false
      progressMsg.value = latest.message || '❌ 任务失败'
    }
  }
})

onUnmounted(() => {
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
})

async function loadMusicList() {
  try { const res = await videoApi.musicList(); musicFiles.value = res.files || [] } catch(e) {}
}

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
function stopMusic() {
  const audio = audioPlayer.value
  if (audio) { audio.pause(); audio.currentTime = 0 }
  isPlaying.value = false
}
const selectedMusicFiles = ref([])
function onMusicFileChange(e) { selectedMusicFiles.value = Array.from(e.target.files || []) }
async function uploadMusic() {
  if (!selectedMusicFiles.value.length) { ElMessage.warning('请先选择文件'); return }
  uploadingMusic.value = true
  let ok = 0, fail = 0
  for (const file of selectedMusicFiles.value) {
    try {
      const formData = new FormData(); formData.append('file', file)
      await videoApi.uploadMusic(formData)
      ok++
    } catch(e) { fail++ }
  }
  if (ok) ElMessage.success(`上传完成：${ok} 个成功` + (fail ? `，${fail} 个失败` : ''))
  else ElMessage.error('上传失败')
  selectedMusicFiles.value = []
  if (musicFileInput.value) musicFileInput.value.value = ''
  await loadMusicList()
  uploadingMusic.value = false
}

// 浏览
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
    let p = outputPath.value; let initial_dir = null
    if (p) { const idx = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\')); if (idx > -1) initial_dir = p.substring(0, idx) }
    const res = await browseApi.save({ initial_dir })
    if (res.path) { p = res.path; if (!p.toLowerCase().endsWith('.mp4')) p += '.mp4'; outputPath.value = p }
  } catch(e) { ElMessage.error('选择保存路径失败: ' + e.message) }
}

// 生成
function getSettings() {
  // 优先使用排序面板的顺序，如果为空则用勾选的图片（保持网格顺序）
  const ordered = orderedImages.value.length > 0
    ? orderedImages.value.map(img => img.path)
    : images.value.filter(img => selectedImgs.value[img.filename]).map(img => img.path)
  return {
    images: ordered, random_order: false,  // 排序面板已确定顺序，不需后端再随机
    settings: {
      output_path: outputPath.value, use_logo: useLogo.value, logo_position: logoPosition.value, logo_effect: logoEffect.value,
      frame_duration: frameDuration.value, transition: transition.value, resolution: resolution.value,
      bg_image: bgImage.value || undefined, bg_color: bgColor.value,
      dynamic_bg: dynamicBg.value, dynamic_bg_mode: dynamicBgMode.value,
      content_scale: contentScale.value,
      music_path: musicPath.value || undefined,
      text1: text1.value || undefined, text2: text2.value || undefined, text_font: textFont.value,
      overwrite: overwrite.value,
    },
    ai: useAI.value ? { enabled: true, service: aiService.value, duration: aiDuration.value, api_key: aiApiKey.value, prompt: aiPrompt.value || undefined } : { enabled: false },
  }
}

function doGenerate(settings) {
  generating.value = true; progressPct.value = 0; progressMsg.value = '提交中...'

  return videoStore.generate(settings).then(res => {
    const tid = res.task_id
    const label = (settings.name || '未命名')
    const innerId = taskStore.addTask('video', label, tid)
    taskStore.updateTask(innerId, {
      meta: { videoDir: videoDir.value, outputPath: outputPath.value },
    })

    return new Promise((resolve) => {
      let done = false
      const poll = () => {
        if (done) return
        videoStore.checkProgress(tid).then(p => {
          if (pollAborted || done) return
          progressPct.value = p.progress || 0
          progressMsg.value = p.message || '处理中...'
          taskStore.updateTask(innerId, {
            status: 'running',
            progress: p.progress || 0,
            message: p.message || '处理中...',
          })
          if (p.status === 'completed') {
            done = true
            generating.value = false
            if (p.output?.path) generatedPaths.value.push(p.output.path)
            progressMsg.value = '✅ 完成: ' + (p.output?.path || '')
            taskStore.updateTask(innerId, {
              status: 'completed', progress: 1,
              message: '✅ 完成', result: p, finishedAt: Date.now(),
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
          if (!done) pollTimer = setTimeout(poll, 2000)
        })
      }
      poll()
    })
  }).catch(e => {
    generating.value = false
    ElMessage.error(e.message || '提交任务失败')
  })
}

/** 恢复本地轮询——页面挂载后重新连接全局 Store 中的活跃任务 */
function pollLocalTask(latest) {
  const tid = latest.taskId
  if (!tid) return
  let done = false
  const poll = () => {
    if (done) return
    videoStore.checkProgress(tid).then(p => {
      if (done) return
      progressPct.value = p.progress || 0
      progressMsg.value = p.message || '处理中...'
      taskStore.updateTask(latest.id, {
        progress: p.progress || 0, message: p.message || '', status: 'running',
      })
      if (p.status === 'completed') {
        done = true; generating.value = false
        if (p.output?.path) generatedPaths.value.push(p.output.path)
        progressMsg.value = '✅ 完成: ' + (p.output?.path || '')
        taskStore.updateTask(latest.id, {
          status: 'completed', progress: 1, message: '✅ 完成', result: p, finishedAt: Date.now(),
        })
        ElMessage.success('视频生成完成'); autoSaveHistory()
      } else if (p.status === 'error') {
        done = true; generating.value = false
        progressMsg.value = '❌ ' + (p.message || '未知错误')
        taskStore.updateTask(latest.id, {
          status: 'error', message: p.message || '未知错误', error: p.message, finishedAt: Date.now(),
        })
        ElMessage.error(p.message || '未知错误')
      } else {
        pollTimer = setTimeout(poll, 2000)
      }
    }).catch(() => { if (!done) pollTimer = setTimeout(poll, 2000) })
  }
  poll()
}

function pathBasename(p) {
  if (!p) return ''
  const clean = p.replace(/\\/g, '/')
  return clean.split('/').pop() || p
}
function downloadVideo(path) {
  if (path) window.open('/api/video/download?path=' + encodeURIComponent(path), '_blank')
}

function ensureMp4(p) { if (!p) return p; return p.toLowerCase().endsWith('.mp4') ? p : p + '.mp4' }

async function startGenerate() {
  generatedPaths.value = []
  outputPath.value = ensureMp4(outputPath.value)
  const s = getSettings(); s.settings.output_path = outputPath.value
  if (!s.images.length) { ElMessage.warning('请选择图片'); return }
  if (!outputPath.value) { ElMessage.warning('请设置输出路径'); return }
  if (!overwrite.value) {
    try { const n = await videoApi.nextFilename({ output_path: outputPath.value }); if (n.path) outputPath.value = n.path } catch(e) {}
  }
  await doGenerate(s)
}

function addToQueue() {
  outputPath.value = ensureMp4(outputPath.value)
  const s = getSettings(); s.settings.output_path = outputPath.value
  if (!s.images.length) { ElMessage.warning('请选择图片'); return }
  taskQueue.value.push({ ...s, name: (logo.value ? logo.value.filename : (images.value[0]?.filename || '')) })
  ElMessage.success('已加入队列')
}
function removeFromQueue(i) { taskQueue.value.splice(i, 1) }
async function generateAll() {
  if (generatingBatch.value || !taskQueue.value.length) return
  generatingBatch.value = true
  // 快照当前队列，立即从 taskQueue 中移除这批（新增的留给下次）
  const batch = [...taskQueue.value]
  taskQueue.value = taskQueue.value.slice(batch.length)
  for (const t of batch) {
    await doGenerate(t)
    await new Promise(r => setTimeout(r, 1000))
  }
  generatingBatch.value = false
}

// 历史记录
const history = ref({})
const activeHistoryId = ref(null)
const historyCount = computed(() => {
  let n = 0
  Object.values(history.value).forEach(userPkgs => {
    if (userPkgs && typeof userPkgs === 'object') {
      Object.values(userPkgs).forEach(entries => {
        if (Array.isArray(entries)) n += entries.length
      })
    }
  })
  return n
})

const collapsedUsers = reactive({})
function toggleUserCollapse(username) {
  collapsedUsers[username] = !collapsedUsers[username]
}

async function loadHistory() {
  try {
    await videoStore.loadHistory()
    history.value = videoStore.history || {}
    // 新加载的数据默认全部折叠
    Object.keys(history.value).forEach(u => {
      if (!(u in collapsedUsers)) collapsedUsers[u] = true
    })
  } catch(e) {}
}

function autoSaveHistory() {
  if (!videoDir.value || !images.value.length) return
  const s = getSettings()
  s.videoDir = videoDir.value
  s.username = authStore.user?.display_name || authStore.user?.username || ''
  s.name = videoDir.value.replace(/\\/g, '/').split('/').pop() || (images.value[0]?.filename || '')
  delete s.images
  videoStore.saveHistory(s).then(() => loadHistory()).catch(() => {})
}

async function saveHistory() {
  if (!videoDir.value) { ElMessage.warning('请先选择图片目录'); return }
  if (!images.value.length) { ElMessage.warning('请先扫描图片'); return }
  const s = getSettings()
  s.videoDir = videoDir.value
  s.username = authStore.user?.display_name || authStore.user?.username || ''
  s.name = videoDir.value.replace(/\\/g, '/').split('/').pop() || (images.value[0]?.filename || '')
  delete s.images
  await videoStore.saveHistory(s)
  await loadHistory()
  ElMessage.success('已保存')
}

function _historyKey(username, pkg) {
  // _shared 是旧数据的分组名，实际文件在根目录下不带用户名前缀
  if (!username || username === '_shared') return pkg
  return `${username}/${pkg}`
}

async function deleteHistoryEntry(username, pkg, index) {
  await videoStore.deleteHistory(_historyKey(username, pkg), [index])
  await loadHistory()
}

async function deleteHistoryPkg(username, pkg) {
  await videoStore.deleteHistory(_historyKey(username, pkg), null)
  await loadHistory()
}

async function applyHistory(e) {
  activeHistoryId.value = e._id
  // 1. 先扫描目录加载图片（会填充默认 outputPath 等）
  if (e.videoDir) {
    videoDir.value = e.videoDir
    await scanDir()
  }
  // 2. 再用历史配置覆盖（scanDir 的自动填充被历史值覆盖）
  if (e.settings) {
    const s = e.settings
    if (s.output_path) outputPath.value = s.output_path
    if (s.frame_duration) frameDuration.value = s.frame_duration
    if (s.transition) transition.value = s.transition
    if (s.resolution) resolution.value = s.resolution
    if (s.bg_color != null) bgColor.value = s.bg_color
    if (s.bg_image != null) bgImage.value = s.bg_image
    if (s.dynamic_bg != null) dynamicBg.value = s.dynamic_bg
    if (s.dynamic_bg_mode) dynamicBgMode.value = s.dynamic_bg_mode
    if (s.content_scale) contentScale.value = s.content_scale
    if (s.music_path != null) musicPath.value = s.music_path
    if (s.text_font) textFont.value = s.text_font
    if (s.text1 != null) text1.value = s.text1
    if (s.text2 != null) text2.value = s.text2
    if (s.use_logo != null) useLogo.value = s.use_logo
    if (s.logo_position) logoPosition.value = s.logo_position
    if (s.logo_effect) logoEffect.value = s.logo_effect
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
  ElMessage.success('已应用' + (e.videoDir && !images.value.length ? '（目录可能已不存在）' : ''))
}

// 字体
const pendingFonts = ref([])
const uploadingFonts = ref(false)
const fontFileInput = ref(null)

function onFontFileChange(e) {
  pendingFonts.value = Array.from(e.target.files || [])
}
async function uploadFonts() {
  if (!pendingFonts.value.length) return
  uploadingFonts.value = true
  try {
    const formData = new FormData()
    pendingFonts.value.forEach(f => formData.append('files', f))
    const res = await videoApi.fontsUpload(formData)
    ElMessage.success(`导入 ${res.imported} 个字体`)
    pendingFonts.value = []
    if (fontFileInput.value) fontFileInput.value.value = ''
    await videoStore.loadFonts()
    fonts.value = videoStore.fonts || []
  } catch(e) { ElMessage.error('上传失败: ' + (e.message || '未知错误')) }
  uploadingFonts.value = false
}

// 文案预览
const previewFontFamily = ref('')
const fontLoaded = ref(false)
function onFontChange(fontId) {
  fontLoaded.value = false
  if (!fontId) return
  const font = fonts.value.find(f => f.id === fontId)
  if (!font) return
  const family = 'font_preview_' + fontId
  const existing = document.getElementById('font-preview-style')
  if (existing) existing.remove()
  const style = document.createElement('style')
  style.id = 'font-preview-style'
  style.textContent = `@font-face { font-family: '${family}'; src: url('/api/font-file?path=${encodeURIComponent(font.path)}'); }`
  document.head.appendChild(style)
  // 等字体加载
  document.fonts.load(`16px ${family}`).then(() => {
    previewFontFamily.value = family
    fontLoaded.value = true
  }).catch(() => {
    previewFontFamily.value = ''
    fontLoaded.value = false
  })
}
</script>

<style scoped>
.media-root { max-width: 1000px; }
.section { background: #fff; border: 1px solid #eee; border-radius: 10px; padding: 20px; margin-bottom: 16px; overflow: hidden; }
.section h3 { margin: 0 0 12px 0; font-size: 15px; }
.sub-section { background: #fafafa; border-radius: 6px; padding: 10px 12px; overflow: hidden; overflow-wrap: break-word; }
.sub-section :deep(.el-checkbox__label) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; display: inline-block; vertical-align: middle; }
.scrape-result-row {
  padding: 6px 10px; border-radius: 4px; margin-bottom: 3px; font-size: 12px;
  display: flex; align-items: center; gap: 8px;
  background: rgba(0,0,0,0.02); border-left: 3px solid;
  transition: background .15s;
}
.scrape-result-row:hover { background: rgba(8,145,178,.08); }
.img-card { border: 2px solid transparent; border-radius: 8px; cursor: pointer; transition: all .15s; }
.img-card:hover { border-color: #0891b2; }
.img-card.selected { border-color: #0891b2; background: rgba(8,145,178,.08); }
.sort-card { transition: transform .15s, opacity .15s, border-color .15s; }
.sort-card.dragging { opacity: 0.4; transform: scale(0.95); }
.sort-card.drag-over { border-color: #0891b2 !important; transform: scale(1.05); }
</style>
