<template>
  <div style="display:flex;flex-direction:column;height:calc(100vh - 72px);">
    <h1 style="flex-shrink:0;">🧰 工具集</h1>
    <div class="sticky-tabs" style="flex-shrink:0;">
      <el-tabs :model-value="activeTab" @update:model-value="switchTab">
        <el-tab-pane label="📊 做表数据" name="zuobiao" />
        <el-tab-pane label="🎵 音频替换" name="audio" />
        <el-tab-pane label="🌐 翻译工具" name="translate" />
      </el-tabs>
    </div>

    <!-- ===== 做表数据 — 输入区固定 + 结果滚动 ===== -->
    <div v-show="activeTab === 'zuobiao'" style="flex:1;min-height:0;display:flex;flex-direction:column;">
      <div style="flex-shrink:0;">
        <div style="display:flex;gap:12px;align-items:center;margin-bottom:8px;">
          <el-select v-model="zbSelectedProduct" placeholder="搜索并选择产品..." filterable clearable style="width:220px;" :loading="zbProductsLoading">
            <el-option v-for="p in zbProducts" :key="p.id" :label="p.product_name + (p.region ? ' (' + p.region + ')' : '') + (p.sales_person ? ' - ' + p.sales_person : '')" :value="p.product_name" />
          </el-select>
          <el-date-picker v-model="zbSelectedDate" type="date" placeholder="选择日期" value-format="YYYY-MM-DD" style="width:150px;" />
          <el-select v-model="zbYanghuKeywords" multiple filterable allow-create placeholder="养户关键词（匹配到的行→养户/止戈）" style="flex:1;min-width:250px;" size="small" />
        </div>
        <p style="color:#888;margin-bottom:8px;font-size:13px;">粘贴包含"添加过滤条件"和"Total"的原始竖排数据：</p>
        <el-checkbox v-model="zbIncludeCampaignId" size="small" style="margin-bottom:8px;" :disabled="zbYanghu">包含广告系列ID（原数据11列，自动剔除第5列）</el-checkbox>
        <el-checkbox v-model="zbYanghu" size="small" style="margin-bottom:8px;margin-left:12px;">养户（7列：账号/客户ID/广告系列/状态/费用/展示/点击）</el-checkbox>
        <el-input v-model="zbInput" type="textarea" :rows="8" placeholder="在此粘贴原始数据..." />
        <div style="display:flex;gap:8px;margin-top:8px;">
          <el-button type="primary" @click="zbProcess">🚀 一键解析并生成所有报表</el-button>
          <el-button @click="zbExportExcel" :disabled="!zbRaw.length">📥 导出全部为 Excel</el-button>
          <el-button v-if="zbSelectedProduct && zbRaw.length" type="warning" @click="zbUpdateSheet" :loading="zbUpdatingSheet">📊 更新你的表格</el-button>
        </div>
        <div v-if="zbError" style="color:#dc2626;margin-top:8px;">{{ zbError }}</div>

        <!-- 表格同步状态提示条 -->
        <div v-if="zbSyncStatus && (zbSyncStatus.status === 'failed' || zbSyncStatus.status === 'retry_failed')"
          :style="{ marginTop: '10px', padding: '10px 14px', borderRadius: '8px', background: zbSyncStatus.status === 'retry_failed' ? '#fef2f2' : '#fffbeb', border: '1px solid ' + (zbSyncStatus.status === 'retry_failed' ? '#fecaca' : '#fde68a') }">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span style="font-weight:600;">
              {{ zbSyncStatus.status === 'retry_failed' ? '❌ 重试失败，请手动操作' : '⚠️ 填表失败' }}
            </span>
            <span v-if="zbSyncStatus.status === 'failed' && zbRetryCountdown > 0" style="color:#d97706;font-size:13px;">
              {{ zbRetryCountdown }}秒后自动重试...
            </span>
            <span v-if="zbSyncStatus.error_msg" style="font-size:12px;color:#999;">{{ zbSyncStatus.error_msg }}</span>
            <el-button link size="small" type="primary" @click="zbRetrySheetsSync">🔄 重新同步</el-button>
            <el-button link size="small" @click="zbShowSyncData = !zbShowSyncData">
              {{ zbShowSyncData ? '收起数据' : '📋 查看数据' }}
            </el-button>
          </div>
          <!-- 展开的数据表格 -->
          <div v-if="zbShowSyncData && zbSyncStatus.rows && zbSyncStatus.rows.length" style="margin-top:10px;max-height:300px;overflow:auto;">
            <div style="display:flex;justify-content:flex-end;margin-bottom:4px;">
              <el-button link size="small" @click="copySyncRows">📋 复制 TSV</el-button>
            </div>
            <table style="width:100%;font-size:11px;border-collapse:collapse;">
              <thead>
                <tr style="background:#f1f5f9;">
                  <th v-for="h in ['日期','运营','账号','客户ID','费用','','产品','商务','地区','广告系列','','代投比例','M','N']" :key="h"
                    style="padding:4px 6px;border:1px solid #e2e8f0;text-align:left;white-space:nowrap;">{{ h }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in zbSyncStatus.rows" :key="i">
                  <td v-for="(cell, j) in row" :key="j"
                    style="padding:3px 6px;border:1px solid #e2e8f0;white-space:nowrap;max-width:120px;overflow:hidden;text-overflow:ellipsis;">
                    {{ cell ?? '' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div style="flex:1;min-height:0;overflow-y:auto;">
        <!-- 原始清洗数据 -->
        <div v-if="zbRaw.length" style="margin-top:20px;">
          <h3>📋 原始清洗数据 <el-tag size="small">{{ zbRaw.length }}</el-tag>
            <el-button link size="small" @click="copyTable('zbRaw')">📋 一键复制</el-button>
          </h3>
          <el-table :data="zbRaw" size="small" border stripe max-height="300" :id="'zbTableRaw'">
            <el-table-column prop="account" label="账号" min-width="110" />
            <el-table-column prop="customerId" label="客户ID" min-width="120" />
            <el-table-column prop="campaign" label="广告系列" min-width="160" show-overflow-tooltip />
            <el-table-column prop="campaignStatus" label="状态" min-width="70">
              <template #default="{row}">{{ row.campaignStatus || '-' }}</template>
            </el-table-column>
            <el-table-column prop="cost" label="费用" min-width="80">
              <template #default="{row}">{{ row.cost.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="impressions" label="展示次数" min-width="80">
              <template #default="{row}">{{ row.impressions.toLocaleString() }}</template>
            </el-table-column>
            <el-table-column prop="clicks" label="点击次数" min-width="80">
              <template #default="{row}">{{ row.clicks.toLocaleString() }}</template>
            </el-table-column>
            <el-table-column prop="installs" label="安装次数" min-width="80">
              <template #default="{row}">{{ (row.installs || 0).toLocaleString() }}</template>
            </el-table-column>
            <el-table-column prop="inAppActions" label="应用内操作" min-width="100">
              <template #default="{row}">{{ row.inAppActions ?? '-' }}</template>
            </el-table-column>
            <el-table-column prop="costPerInApp" label="每次操作费用" min-width="110">
              <template #default="{row}">{{ row.costPerInApp ?? '-' }}</template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 做表数据 -->
        <div v-if="zbZuobiao.length" style="margin-top:20px;">
          <h3>📑 做表数据 <el-tag size="small">{{ zbZuobiao.length }}</el-tag>
            <el-button link size="small" @click="copyTable('zbZuobiao')">📋 一键复制</el-button>
          </h3>
          <el-table :data="zbZuobiao" size="small" border stripe max-height="300">
            <el-table-column prop="account" label="账号" /><el-table-column prop="customerId" label="客户ID" />
            <el-table-column prop="cost" label="费用"><template #default="{row}">{{ row.cost.toFixed(2) }}</template></el-table-column>
            <el-table-column width="20" /><el-table-column width="20" /><el-table-column width="20" /><el-table-column width="20" />
            <el-table-column prop="campaign" label="广告系列" />
          </el-table>
        </div>

        <!-- 客户表数据 -->
        <div v-if="zbKehu.length" style="margin-top:20px;">
          <h3>📈 客户表数据 <el-tag size="small">{{ zbKehu.length }}</el-tag>
            <el-button link size="small" @click="copyTable('zbKehu')">📋 一键复制</el-button>
          </h3>
          <el-table :data="zbKehu" size="small" border stripe max-height="300">
            <el-table-column prop="campaign" label="广告系列" />
            <el-table-column prop="cost" label="费用"><template #default="{row}">{{ row.cost.toFixed(2) }}</template></el-table-column>
            <el-table-column prop="impressions" label="展示次数"><template #default="{row}">{{ row.impressions.toLocaleString() }}</template></el-table-column>
            <el-table-column prop="clicks" label="点击次数"><template #default="{row}">{{ row.clicks.toLocaleString() }}</template></el-table-column>
          </el-table>
        </div>
      </div>
    </div>

    <!-- ===== 音频替换 ===== -->
    <div v-show="activeTab === 'audio'" style="flex:1;min-height:0;overflow-y:auto;max-width:700px;">
      <el-form-item label="🎬 原视频">
        <input type="file" accept="video/*" @change="onAudioVideoFileChange" style="width:100%;" />
        <span v-if="audioVideoFile" style="font-size:12px;color:#22c55e;">已选择: {{ audioVideoFile.name }}</span>
        <video v-if="audioVideoBlobUrl" :src="audioVideoBlobUrl" controls muted loop style="width:100%;max-height:200px;margin-top:6px;border-radius:6px;background:#000;" />
      </el-form-item>
      <el-form-item label="🎶 新音频源（音频或视频）">
        <input type="file" accept="audio/*,video/*" @change="onAudioSourceFileChange" style="width:100%;" />
        <span v-if="audioSourceFile" style="font-size:12px;color:#22c55e;">已选择: {{ audioSourceFile.name }}</span>
        <video v-if="audioSourceBlobUrl && audioSourceFile?.type?.startsWith('video/')" :src="audioSourceBlobUrl" controls muted loop style="width:100%;max-height:200px;margin-top:6px;border-radius:6px;background:#000;" />
        <audio v-else-if="audioSourceBlobUrl" :src="audioSourceBlobUrl" controls style="width:100%;margin-top:6px;" />
      </el-form-item>
      <el-button type="primary" @click="audioReplace" :loading="audioReplacing">🎵 替换音频</el-button>
      <div v-if="audioResult" style="margin-top:8px;font-size:12px;">
        {{ audioResult }}
        <el-button v-if="audioDownloadUrl" type="success" link size="small" @click="audioDoDownload" style="margin-left:8px;">⬇ 下载</el-button>
      </div>

      <!-- 历史记录 -->
      <div v-if="audioHistory.length" style="margin-top:24px;">
        <div style="display:flex;align-items:center;justify-content:space-between;">
          <h3 style="margin:0;">📋 历史记录 <el-tag size="small">{{ audioHistory.length }}</el-tag></h3>
          <el-popconfirm title="确定清空全部历史记录？" @confirm="audioHistoryClearAll">
            <template #reference><el-button type="danger" size="small" link>🗑 清空全部</el-button></template>
          </el-popconfirm>
        </div>
        <div v-for="item in audioHistory" :key="item.id"
          style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #eee;font-size:13px;">
          <div style="flex:1;min-width:0;">
            <div style="display:flex;gap:6px;align-items:center;">
              <span style="font-weight:600;">🎬 {{ item.video_name }}</span>
              <span style="color:#999;">+</span>
              <span>🎶 {{ item.audio_name }}</span>
            </div>
            <div style="color:#888;font-size:11px;margin-top:2px;">→ {{ item.output_name }} · {{ item.size_mb }} MB · {{ item.created_at }}</div>
          </div>
          <template v-if="item.file_exists">
            <el-button size="small" type="primary" link @click="audioHistoryDownload(item)">⬇ 下载</el-button>
          </template>
          <el-tag v-else size="small" type="info">已过期</el-tag>
          <el-popconfirm title="确定删除此记录？" @confirm="audioHistoryDelete(item)">
            <template #reference><el-button size="small" type="danger" link>🗑</el-button></template>
          </el-popconfirm>
        </div>
      </div>
    </div>

    <!-- ===== 翻译工具 ===== -->
    <div v-show="activeTab === 'translate'" style="flex:1;min-height:0;overflow-y:auto;max-width:700px;">
      <el-form-item label="📝 源文本">
        <el-input v-model="tlInput" type="textarea" :rows="6" placeholder="输入要翻译的文本..." />
      </el-form-item>
      <div style="display:flex;gap:8px;align-items:center;margin-top:12px;">
        <span style="font-size:13px;white-space:nowrap;">目标语言：</span>
        <el-select v-model="tlTarget" placeholder="选择语言" style="width:200px;" filterable>
          <el-option v-for="l in TL_LANGS" :key="l.value" :label="l.label" :value="l.value" />
        </el-select>
        <el-button type="primary" @click="tlTranslate" :loading="tlLoading">🌐 翻译</el-button>
      </div>
      <div v-if="tlError" style="color:#dc2626;margin-top:8px;">{{ tlError }}</div>
      <div v-if="tlResult" style="margin-top:16px;">
        <div style="display:flex;align-items:center;gap:8px;">
          <h3 style="margin:0;">📋 翻译结果</h3>
          <el-button link size="small" @click="tlCopy">📋 复制</el-button>
        </div>
        <div style="background:#f5f7fa;padding:12px;border-radius:8px;margin-top:8px;white-space:pre-wrap;font-size:14px;line-height:1.6;">{{ tlResult }}</div>
      </div>
    </div>

    <!-- 保存弹窗 -->
    <el-dialog v-model="zbSaveDialogVisible" title="💾 保存做表数据" width="95%" top="3vh" @open="onSaveDialogOpen">
      <div style="margin-bottom:12px;font-size:13px;color:#555;">
        <span>产品：<b>{{ zbSelectedProduct }}</b></span>
        <span style="margin-left:16px;">地区：<b>{{ zbSelectedRegion }}</b></span>
        <span style="margin-left:16px;">日期：<b>{{ zbSelectedDate }}</b></span>
      </div>
      <div style="margin-top:8px;">
        <div style="font-weight:600;margin-bottom:6px;">📋 待保存数据 ({{ saveRows.length }} 条)</div>
        <el-table :data="saveRows" size="small" border stripe max-height="380">
          <el-table-column prop="account" label="账号" min-width="100" />
          <el-table-column prop="customerId" label="客户ID" min-width="120" />
          <el-table-column prop="campaign" label="广告系列" min-width="160" show-overflow-tooltip />
          <el-table-column prop="cost" label="费用" min-width="80">
            <template #default="{row}">{{ row.cost.toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="impressions" label="展示" min-width="80">
            <template #default="{row}">{{ (row.impressions || 0).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="clicks" label="点击" min-width="70">
            <template #default="{row}">{{ (row.clicks || 0).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="installs" label="安装" min-width="70">
            <template #default="{row}">{{ (row.installs || 0).toLocaleString() }}</template>
          </el-table-column>
          <el-table-column prop="inAppActions" label="应用内操作" min-width="100">
            <template #default="{row}">{{ row.inAppActions ?? '-' }}</template>
          </el-table-column>
          <el-table-column prop="costPerInApp" label="每次操作费用" min-width="110">
            <template #default="{row}">{{ row.costPerInApp ?? '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" min-width="60" fixed="right">
            <template #default="{ $index }">
              <el-button link size="small" type="danger" @click="removeSaveRow($index)">🗑 删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="zbSaveDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="zbDoSave" :loading="zbSaving">💾 保存</el-button>
      </template>
    </el-dialog>

    <!-- 重复数据对比弹窗 -->
    <el-dialog v-model="zbDupDialogVisible" title="⚠️ 发现重复数据" width="960px" top="5vh" :close-on-click-modal="false">
      <p style="color:#dc2626;margin-bottom:12px;">
        以下 {{ duplicateItems.length }} 条数据已存在（同产品+同客户ID+同系列）。请逐条选择保留旧数据还是用新数据覆盖。再次点击可取消选择。
      </p>
      <div v-for="(item, idx) in duplicateItems" :key="idx"
        style="display:flex;gap:12px;margin-bottom:12px;padding:8px;border:1px solid #e5e7eb;border-radius:8px;"
        :style="{ opacity: item.resolved ? 0.45 : 1 }">
        <!-- 左侧：旧数据 -->
        <div style="flex:1;background:#fef2f2;padding:10px;border-radius:6px;" :style="item.decision === 'keep-old' ? { border: '2px solid #22c55e' } : {}">
          <div style="font-weight:600;margin-bottom:4px;">📋 旧数据 (ID: {{ item.existing.id }})</div>
          <div style="font-size:12px;line-height:1.7;">
            <div>客户ID: {{ item.existing.customer_id }}</div>
            <div>系列: {{ item.existing.campaign }}</div>
            <div>费用: {{ item.existing.cost }}</div>
            <div>展示: {{ item.existing.impressions?.toLocaleString() }}</div>
            <div>点击: {{ item.existing.clicks?.toLocaleString() }}</div>
            <div v-if="item.existing.installs">安装: {{ item.existing.installs?.toLocaleString() }}</div>
            <div>日期: {{ item.existing.report_date }}</div>
          </div>
          <el-button size="small" :type="item.decision === 'keep-old' ? 'primary' : 'default'"
            :disabled="item.resolved && item.decision !== 'keep-old'"
            @click="resolveDuplicate(idx, 'keep-old')" style="margin-top:6px;">
            {{ item.decision === 'keep-old' ? '✓ 已选保留旧数据（再次点击取消）' : '保留旧数据' }}
          </el-button>
        </div>
        <!-- 右侧：新数据 -->
        <div style="flex:1;background:#f0fdf4;padding:10px;border-radius:6px;" :style="item.decision === 'keep-new' ? { border: '2px solid #22c55e' } : {}">
          <div style="font-weight:600;margin-bottom:4px;">🆕 新数据</div>
          <div style="font-size:12px;line-height:1.7;">
            <div>账号: {{ item.incoming.account || '-' }}</div>
            <div>客户ID: {{ item.incoming.customerId }}</div>
            <div>系列: {{ item.incoming.campaign }}</div>
            <div>费用: {{ item.incoming.cost }}</div>
            <div>展示: {{ (item.incoming.impressions || 0).toLocaleString() }}</div>
            <div>点击: {{ (item.incoming.clicks || 0).toLocaleString() }}</div>
            <div v-if="item.incoming.installs">安装: {{ (item.incoming.installs || 0).toLocaleString() }}</div>
          </div>
          <el-button size="small" :type="item.decision === 'keep-new' ? 'success' : 'default'"
            :disabled="item.resolved && item.decision !== 'keep-new'"
            @click="resolveDuplicate(idx, 'keep-new')" style="margin-top:6px;">
            {{ item.decision === 'keep-new' ? '✓ 已选用新数据覆盖（再次点击取消）' : '用新数据覆盖' }}
          </el-button>
        </div>
      </div>
      <template #footer>
        <el-button @click="zbDupDialogVisible = false">取消保存</el-button>
        <el-button type="primary" @click="zbConfirmSave" :loading="zbSaving"
          :disabled="duplicateItems.some(d => !d.resolved)">
          确认保存 ({{ duplicateItems.filter(d => d.resolved).length }}/{{ duplicateItems.length }})
        </el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { copyToClipboard } from '@/utils/clipboard'
import { parseAdsData } from '@/utils/adsParser'
import { translateApi } from '@/api/youtube'
import { videoApi } from '@/api/video'
import { googleSheetsApi } from '@/api/google-sheets'
import api from '@/api/client'

const router = useRouter()
const route = useRoute()

const activeTab = computed(() => {
  if (route.path.includes('/audio')) return 'audio'
  if (route.path.includes('/translate')) return 'translate'
  return 'zuobiao'
})
function switchTab(name) { router.push(`/toolkit/${name}`) }

// ========== 做表数据 ==========
const zbInput = ref('')
const zbIncludeCampaignId = ref(false)
const zbYanghu = ref(false)
const zbRaw = ref([])
const zbZuobiao = ref([])
const zbKehu = ref([])
const zbError = ref('')

// ========== 外层产品/日期选择（共享给保存弹窗和更新表格） ==========
const zbSelectedProduct = ref('')
const zbSelectedDate = ref(_yesterday())
const zbProducts = ref([])
const zbProductsLoading = ref(false)
const zbUpdatingSheet = ref(false)
const zbSyncStatus = ref(null)        // { status, error_msg, rows, retry_count, updated_at }
const zbSyncChecking = ref(false)
const zbRetryCountdown = ref(0)       // 30s 倒计时
const zbShowSyncData = ref(false)
let _zbSyncTimer = null
let _zbCountdownTimer = null

// 选择产品时查询是否有未同步记录
watch(zbSelectedProduct, (name) => {
  clearZbSyncState()
  if (name) checkZbSyncStatus()
})

function clearZbSyncState() {
  zbSyncStatus.value = null
  zbRetryCountdown.value = 0
  if (_zbSyncTimer) { clearTimeout(_zbSyncTimer); _zbSyncTimer = null }
  if (_zbCountdownTimer) { clearInterval(_zbCountdownTimer); _zbCountdownTimer = null }
}

async function checkZbSyncStatus() {
  if (!zbSelectedProduct.value) return
  zbSyncChecking.value = true
  try {
    const res = await googleSheetsApi.syncStatus(zbSelectedProduct.value)
    if (res.retry_failed) {
      // 重试也失败了 → 一次性弹窗
      ElMessage.error('重试失败，请联系管理')
      zbSyncStatus.value = null
      return
    }
    zbSyncStatus.value = res.log
    if (res.log && res.log.status === 'failed') {
      // 显示 30s 重试中状态
      zbRetryCountdown.value = 30
      startZbCountdown()
    }
  } catch { zbSyncStatus.value = null }
  finally { zbSyncChecking.value = false }
}

function startZbCountdown() {
  if (_zbCountdownTimer) clearInterval(_zbCountdownTimer)
  zbRetryCountdown.value = 30
  _zbCountdownTimer = setInterval(() => {
    zbRetryCountdown.value--
    if (zbRetryCountdown.value <= 0) {
      clearInterval(_zbCountdownTimer)
      _zbCountdownTimer = null
      checkZbSyncStatus()  // 检查重试结果
    }
  }, 1000)
}

// 养户关键词（localStorage 持久化，默认值可随时增删）
const ZB_YANGHU_KEY = 'zb_yanghu_keywords'
const zbYanghuKeywords = ref(
  (() => { try { const v = localStorage.getItem(ZB_YANGHU_KEY); return v ? JSON.parse(v) : ['养户', 'Website traffic-Search', 'Campaign #1'] } catch { return ['养户', 'Website traffic-Search', 'Campaign #1'] } })()
)
watch(zbYanghuKeywords, (v) => { localStorage.setItem(ZB_YANGHU_KEY, JSON.stringify(v)) }, { deep: true })

const zbSelectedRegion = computed(() => {
  const p = zbProducts.value.find(x => x.product_name === zbSelectedProduct.value)
  return p ? p.region : ''
})

// ========== 保存到数据库相关状态 ==========
const zbSaveDialogVisible = ref(false)
const zbSaving = ref(false)
const saveRows = ref([])
const zbDupDialogVisible = ref(false)
const duplicateItems = ref([])

function _yesterday() {
  const d = new Date(Date.now() - 86400000)
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
}

async function onSaveDialogOpen() {
  saveRows.value = [...zbRaw.value]
}

function removeSaveRow(idx) {
  saveRows.value.splice(idx, 1)
}

async function zbDoSave() {
  if (!zbSelectedProduct.value) { ElMessage.warning('请选择产品'); return }
  if (!zbSelectedRegion.value) { ElMessage.warning('产品缺少地区信息'); return }
  if (!saveRows.value.length) { ElMessage.warning('没有可保存的数据'); return }
  zbSaving.value = true
  try {
    const checkRes = await api.post('/ad-reports/check-duplicates', {
      product_name: zbSelectedProduct.value,
      region: zbSelectedRegion.value,
      report_date: zbSelectedDate.value,
      rows: saveRows.value,
    })
    if (checkRes.duplicates && checkRes.duplicates.length) {
      duplicateItems.value = checkRes.duplicates.map(d => ({ ...d, resolved: false, decision: null }))
      zbSaveDialogVisible.value = false
      zbDupDialogVisible.value = true
    } else {
      const saveRes = await api.post('/ad-reports/save', {
        product_name: zbSelectedProduct.value,
        region: zbSelectedRegion.value,
        report_date: zbSelectedDate.value,
        rows: saveRows.value,
        override_ids: [],
      })
      ElMessage.success(`保存成功！已保存 ${saveRes.saved} 条`)
      zbSaveDialogVisible.value = false
    }
  } catch (e) { ElMessage.error('保存失败: ' + (e.message || '未知错误')) }
  zbSaving.value = false
}

async function loadZbProducts() {
  zbProductsLoading.value = true
  try {
    const res = await api.get('/ad-reports/products')
    zbProducts.value = res.products || []
  } catch { zbProducts.value = [] }
  zbProductsLoading.value = false
}

async function zbUpdateSheet() {
  if (!zbSelectedProduct.value) { ElMessage.warning('请选择产品'); return }
  if (!zbZuobiao.value.length) { ElMessage.warning('没有做表数据，请先解析'); return }
  zbUpdatingSheet.value = true
  try {
    const p = zbProducts.value.find(x => x.product_name === zbSelectedProduct.value)
    const keywords = zbYanghuKeywords.value.filter(Boolean)
    const taggedRows = zbZuobiao.value.map(row => ({
      ...row,
      is_yanghu: zbYanghu.value || keywords.some(kw => (row.campaign || '').toLowerCase().includes(kw.toLowerCase())),
    }))
    // raw 数据也打上养户标记，供后端过滤后保存到数据库
    const taggedRaw = zbRaw.value.map(row => ({
      account: row.account,
      customerId: row.customerId,
      campaign: row.campaign,
      cost: row.cost,
      impressions: row.impressions,
      clicks: row.clicks,
      installs: row.installs,
      inAppActions: row.inAppActions,
      costPerInApp: row.costPerInApp,
      is_yanghu: zbYanghu.value || keywords.some(kw => (row.campaign || '').toLowerCase().includes(kw.toLowerCase())),
    }))
    zbSyncStatus.value = null  // 清除旧状态
    const res = await googleSheetsApi.updateZuobiao({
      product_name: zbSelectedProduct.value,
      region: zbSelectedRegion.value,
      report_date: zbSelectedDate.value,
      rows: taggedRows,
      raw_rows: taggedRaw,
      sales_person: p?.sales_person || '',
      agency_ratio: p?.agency_ratio ?? null,
    })
    ElMessage.success(`数据库已保存 ${res.db_saved || (taggedRows.length)} 条，表格后台同步中...`)
    // 启动轮询检测同步结果
    startZbSyncPolling()
  } catch (e) {
    ElMessage.error('更新表格失败: ' + (e.response?.data?.error || e.message))
  }
  zbUpdatingSheet.value = false
}

function startZbSyncPolling() {
  let attempts = 0
  const maxAttempts = 40  // 最多轮询 2 分钟
  if (_zbSyncTimer) clearTimeout(_zbSyncTimer)
  const poll = async () => {
    if (attempts >= maxAttempts) return
    attempts++
    try {
      const res = await googleSheetsApi.syncStatus(zbSelectedProduct.value)
      // 重试失败 → 弹窗
      if (res.retry_failed) {
        ElMessage.error('重试失败，请联系管理')
        zbSyncStatus.value = null
        return
      }
      const log = res.log
      if (!log) {
        // 同步成功（无失败记录）
        zbSyncStatus.value = null
        return
      }
      zbSyncStatus.value = log
      if (log.status === 'failed') {
        ElMessage.warning({ message: '填表失败，30秒后自动重试...', duration: 0, showClose: true })
        zbRetryCountdown.value = 30
        startZbCountdown()
        return  // 等待倒计时结束后再检查
      }
      if (log.status === 'retry_failed') {
        ElMessage.error({ message: '重试失败，请手动操作', duration: 0, showClose: true })
        return
      }
      // 其他状态，继续轮询
      _zbSyncTimer = setTimeout(poll, 3000)
    } catch {
      _zbSyncTimer = setTimeout(poll, 3000)
    }
  }
  // 3 秒后开始第一次检查（给后台线程一点时间）
  _zbSyncTimer = setTimeout(poll, 3000)
}

async function zbRetrySheetsSync() {
  if (!zbSelectedProduct.value) return
  try {
    await googleSheetsApi.retrySync({ product_name: zbSelectedProduct.value })
    ElMessage.success('表格同步成功')
    zbSyncStatus.value = null
    zbRetryCountdown.value = 0
    zbShowSyncData.value = false
    if (_zbCountdownTimer) { clearInterval(_zbCountdownTimer); _zbCountdownTimer = null }
  } catch (e) {
    ElMessage.error('重试失败: ' + (e.response?.data?.error || e.message))
    checkZbSyncStatus()
  }
}

function copySyncRows() {
  if (!zbSyncStatus.value?.rows?.length) return
  const tsv = zbSyncStatus.value.rows.map(row =>
    row.map(cell => (cell ?? '')).join('\t')
  ).join('\n')
  navigator.clipboard.writeText(tsv).then(() => {
    ElMessage.success('已复制 ' + zbSyncStatus.value.rows.length + ' 行 TSV 数据')
  }).catch(() => {
    ElMessage.error('复制失败，请手动选择表格内容')
  })
}

function resolveDuplicate(idx, decision) {
  const item = duplicateItems.value[idx]
  if (item.decision === decision) {
    // 再次点击同一按钮 → 取消选择
    item.resolved = false
    item.decision = null
  } else {
    item.resolved = true
    item.decision = decision
  }
  // 触发响应式
  duplicateItems.value = [...duplicateItems.value]
}

async function zbConfirmSave() {
  const unresolved = duplicateItems.value.filter(d => !d.resolved)
  if (unresolved.length) { ElMessage.warning('请处理所有重复数据'); return }
  zbSaving.value = true
  try {
    const overrideIds = duplicateItems.value
      .filter(d => d.decision === 'keep-new')
      .map(d => d.existing.id)
    const saveRes = await api.post('/ad-reports/save', {
      product_name: zbSelectedProduct.value,
      region: zbSelectedRegion.value,
      report_date: zbSelectedDate.value,
      rows: saveRows.value,
      override_ids: overrideIds,
    })
    ElMessage.success(`保存成功！已保存 ${saveRes.saved} 条，跳过 ${saveRes.skipped || 0} 条`)
    zbDupDialogVisible.value = false
  } catch (e) { ElMessage.error('保存失败: ' + (e.message || '未知错误')) }
  zbSaving.value = false
}

function zbProcess() {
  zbError.value = ''
  zbRaw.value = []; zbZuobiao.value = []; zbKehu.value = []
  try {
    const { raw, zuobiao, kehu } = parseAdsData(zbInput.value, {
      isYanghu: zbYanghu.value,
      includeCampaignId: zbIncludeCampaignId.value,
    })
    zbRaw.value = raw
    zbZuobiao.value = zuobiao
    zbKehu.value = kehu
  } catch(e) { zbError.value = e.message }
}

function copyTable(type) {
  const data = type === 'zbZuobiao' ? zbZuobiao.value : type === 'zbKehu' ? zbKehu.value : zbRaw.value
  if (!data.length) return
  let lines
  if (type === 'zbZuobiao') {
    lines = data.map(d => [d.account, d.customerId, d.cost.toFixed(2), '', '', '', '', d.campaign].join('\t'))
  } else if (type === 'zbKehu') {
    lines = data.map(d => [d.campaign, d.cost.toFixed(2), d.impressions, d.clicks].join('\t'))
  } else {
    lines = data.map(d => [d.account, d.customerId, d.campaign, d.cost.toFixed(2), d.impressions, d.clicks].join('\t'))
  }
  copyToClipboard(lines.join('\n')).then(() => ElMessage.success('已复制 ✓'))
}

function zbExportExcel() {
  const XLSX = window.XLSX
  if (!XLSX) { ElMessage.warning('Excel 导出需要加载 XLSX 库，请稍后重试'); return }
  try {
    const wb = XLSX.utils.book_new()
    const rawSheet = XLSX.utils.json_to_sheet(zbRaw.value.map(d => ({
      账号: d.account, 客户ID: d.customerId, 广告系列: d.campaign, 费用: d.cost, 展示次数: d.impressions, 点击次数: d.clicks
    })))
    XLSX.utils.book_append_sheet(wb, rawSheet, '原始清洗数据')

    const zbSheet = XLSX.utils.aoa_to_sheet([
      ['账号','客户ID','费用','','','','','广告系列'],
      ...zbZuobiao.value.map(d => [d.account, d.customerId, d.cost, '', '', '', '', d.campaign])
    ])
    XLSX.utils.book_append_sheet(wb, zbSheet, '做表数据')

    const khSheet = XLSX.utils.json_to_sheet(zbKehu.value)
    XLSX.utils.book_append_sheet(wb, khSheet, '客户表数据')

    XLSX.writeFile(wb, 'Ads多维分析_' + Date.now() + '.xlsx')
    ElMessage.success('导出成功')
  } catch(e) { ElMessage.error('导出失败: ' + e.message) }
}

// ========== 音频替换 ==========
const audioVideoFile = ref(null)
const audioSourceFile = ref(null)
const audioVideoBlobUrl = ref('')
const audioSourceBlobUrl = ref('')
const audioReplacing = ref(false)
const audioResult = ref('')
const audioDownloadUrl = ref('')
const audioHistory = ref([])

// ------ 文件选择 & 预览 ------
function _revokeAudioBlobs() {
  if (audioVideoBlobUrl.value) { URL.revokeObjectURL(audioVideoBlobUrl.value); audioVideoBlobUrl.value = '' }
  if (audioSourceBlobUrl.value) { URL.revokeObjectURL(audioSourceBlobUrl.value); audioSourceBlobUrl.value = '' }
}
onUnmounted(() => { _revokeAudioBlobs(); clearZbSyncState() })

function onAudioVideoFileChange(e) {
  audioVideoFile.value = e.target.files?.[0] || null
  if (audioVideoBlobUrl.value) { URL.revokeObjectURL(audioVideoBlobUrl.value); audioVideoBlobUrl.value = '' }
  if (audioVideoFile.value) audioVideoBlobUrl.value = URL.createObjectURL(audioVideoFile.value)
}

function onAudioSourceFileChange(e) {
  audioSourceFile.value = e.target.files?.[0] || null
  if (audioSourceBlobUrl.value) { URL.revokeObjectURL(audioSourceBlobUrl.value); audioSourceBlobUrl.value = '' }
  if (audioSourceFile.value) audioSourceBlobUrl.value = URL.createObjectURL(audioSourceFile.value)
}

// ------ 替换 & 下载 ------
async function audioReplace() {
  if (!audioVideoFile.value || !audioSourceFile.value) { ElMessage.warning('请选择原视频和音频源'); return }
  audioReplacing.value = true; audioResult.value = ''; audioDownloadUrl.value = ''
  try {
    const fd = new FormData()
    fd.append('video', audioVideoFile.value)
    fd.append('audio', audioSourceFile.value)
    const res = await api.post('/audio-replace', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    audioResult.value = `✅ 完成: ${res.output} (${res.size_mb} MB)`
    audioDownloadUrl.value = res.download_url
    audioLoadHistory()
  } catch(e) { audioResult.value = '❌ ' + (e.response?.data?.error || e.message) }
  audioReplacing.value = false
}

function audioDoDownload() {
  if (audioDownloadUrl.value) window.open(audioDownloadUrl.value, '_blank')
}

// ------ 历史记录 ------
async function audioLoadHistory() {
  try {
    const res = await videoApi.audioHistoryList()
    audioHistory.value = res.items || []
  } catch { /* 静默失败 */ }
}

async function audioHistoryDelete(item) {
  try {
    await videoApi.audioHistoryDelete(item.id)
    ElMessage.success('已删除')
    audioLoadHistory()
  } catch(e) { ElMessage.error('删除失败: ' + (e.response?.data?.error || e.message)) }
}

async function audioHistoryClearAll() {
  try {
    await videoApi.audioHistoryClear()
    ElMessage.success('已清空全部历史')
    audioLoadHistory()
  } catch(e) { ElMessage.error('清空失败: ' + (e.response?.data?.error || e.message)) }
}

function audioHistoryDownload(item) {
  window.open(`/api/audio-replace/download?path=${encodeURIComponent(item.output_path)}`, '_blank')
}

onMounted(() => { audioLoadHistory(); loadZbProducts() })

// ========== 翻译工具 ==========
const TL_LANGS = [
  { label: '中文', value: 'zh-CN' },
  { label: '英语', value: 'en' },
  { label: '葡萄牙语', value: 'pt' },
  { label: '印尼语', value: 'id' },
  { label: '菲律宾语', value: 'tl' },
  { label: '西班牙语', value: 'es' },
  { label: '日语', value: 'ja' },
  { label: '韩语', value: 'ko' },
  { label: '泰语', value: 'th' },
  { label: '越南语', value: 'vi' },
]

const tlInput = ref('')
const tlTarget = ref('zh-CN')
const tlLoading = ref(false)
const tlResult = ref('')
const tlError = ref('')

async function tlTranslate() {
  const text = tlInput.value.trim()
  if (!text) { tlError.value = '请输入要翻译的文本'; return }
  tlError.value = ''
  tlLoading.value = true
  try {
    const res = await translateApi.translate({ text, target: tlTarget.value })
    tlResult.value = res.translated
  } catch (e) {
    tlError.value = '翻译失败：' + (e.message || '未知错误')
  } finally {
    tlLoading.value = false
  }
}

function tlCopy() {
  if (tlResult.value) {
    copyToClipboard(tlResult.value).then(() => ElMessage.success('已复制译文 ✓'))
  }
}
</script>
