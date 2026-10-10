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
            <el-option v-for="p in zbProductOptions" :key="p.id" :label="p.product_name + (p.region ? ' (' + p.region + ')' : '') + (p.sales_person ? ' - ' + p.sales_person : '') + (isPausedProduct(p) ? '（已暂停）' : '')" :value="p.product_name" />
          </el-select>
          <el-checkbox v-model="zbShowPaused" size="small">显示已暂停产品</el-checkbox>
          <el-date-picker v-model="zbSelectedDate" type="date" placeholder="选择日期" value-format="YYYY-MM-DD" style="width:150px;" />
          <el-select v-model="zbYanghuKeywords" multiple filterable allow-create placeholder="养户关键词（匹配到的行→养户/止戈）" style="flex:1;min-width:250px;" size="small" />
        </div>
        <p style="color:#888;margin-bottom:8px;font-size:13px;">粘贴包含"添加过滤条件"和"Total"的原始竖排数据：</p>
        <el-checkbox v-model="zbIncludeCampaignId" size="small" style="margin-bottom:8px;">包含广告系列ID（自动剔除第5列）</el-checkbox>
        <el-checkbox v-model="zbSevenCols" size="small" style="margin-bottom:8px;margin-left:12px;">7列数据（无安装/应用指标）</el-checkbox>
        <el-input v-model="zbInput" type="textarea" :rows="8" placeholder="在此粘贴原始数据..." />
        <div style="display:flex;gap:8px;margin-top:8px;">
          <el-button type="primary" @click="zbProcess">🚀 一键解析并生成所有报表</el-button>
          <el-button @click="zbExportExcel" :disabled="!zbRaw.length">📥 导出全部为 Excel</el-button>
          <el-button v-if="zbSelectedProduct && zbRaw.length" type="warning" @click="zbUpdateSheet" :loading="zbUpdatingSheet">📊 更新你的表格</el-button>
        </div>
        <div v-if="zbError" style="color:#dc2626;margin-top:8px;">{{ zbError }}</div>

        <!-- 写表失败汇总（五期）。复用 FB 数据管理页 / 户管看板卡片已 /frontend-design
             定稿的视觉语法：3px 琥珀左脊柱 + warning 色调（gg_zuobiao 零回滚 ⇒ 只可能是
             retry_failed，「表中未写入」不等于数据坏了）。有失败才渲染，无失败时连占位都没有。
             margin 取 10px（本页提示条原有位置）而非 FB 的 margin-bottom：本块接在按钮行之下。 -->
        <div v-if="zbSwFailures.length"
             style="background:var(--el-color-warning-light-9);border-left:3px solid var(--el-color-warning);border-radius:8px;padding:10px 12px;margin-top:10px;">
          <div style="font-weight:600;font-size:13px;color:#92400e;margin-bottom:6px;">
            ⚠️ {{ zbSwFailures.length }} 项没写进表
          </div>
          <div v-for="(f, i) in zbSwFailures" :key="f.business_key"
               :style="{ display:'flex', alignItems:'baseline', gap:'8px', padding:'5px 0',
                         borderTop: i ? '1px solid var(--el-color-warning-light-7)' : 'none' }">
            <el-tooltip placement="top" :content="sheetWriteHint(f)">
              <span style="font-family:monospace;font-size:12px;color:#374151;flex:none;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ f.business_key }}</span>
            </el-tooltip>
            <span style="font-size:12px;color:#6b7280;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ f.error_msg || '未知原因' }}</span>
            <el-button link size="small" :type="sheetWriteTone(f.status)"
                       @click="retryZbSw(f)">重试</el-button>
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
import { isPausedProduct, visibleProducts } from '@/utils/productOptions'
import { parseAdsData } from '@/utils/adsParser'
import { translateApi } from '@/api/youtube'
import { videoApi } from '@/api/video'
import { googleSheetsApi } from '@/api/google-sheets'
import { sheetWriteApi } from '@/api/sheetWrite'
import { sheetWriteTone, sheetWriteHint, SHEET_WRITE_TOAST } from '@/utils/sheetWriteUi'
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
const zbSevenCols = ref(false)
const zbRaw = ref([])
const zbZuobiao = ref([])
const zbKehu = ref([])
const zbError = ref('')

// ========== 外层产品/日期选择（共享给保存弹窗和更新表格） ==========
const zbSelectedProduct = ref('')
const zbSelectedDate = ref(_yesterday())
const zbProducts = ref([])
const zbProductsLoading = ref(false)
// 下拉默认只列「未暂停」产品。zbProducts 必须保持全量 —— zbUpdateSheet/保存 里
// 靠它 find() 取地区、代投比例（用的是可选链，取不到会静默写空值）。
// 已暂停产品之所以还给一个开关，是因为库里有几十个暂停产品带着历史做表数据，
// 补录和「更新表格」仍然需要能选到它们。
const zbShowPaused = ref(false)
const zbProductOptions = computed(() => visibleProducts(zbProducts.value, zbShowPaused.value))
const zbUpdatingSheet = ref(false)
let _zbSyncTimer = null               // 「保存后轮询」的在途定时器
let _zbSyncGen = 0                    // 每轮保存 +1：作废上一轮在途的 tick，防两条链并行
let _zbMidnightTimer = null

// ---------- 写表失败汇总（五期） ----------
const ZB_SW_TARGET = 'gg_zuobiao'
const zbSwFailures = ref([])

// 轮询本次写表结果：pending / failed 静默续查（**不得提示中间态**）；
// 上限必须 > 后端 30s 重试窗口，否则终态 retry_failed 在 40s 前落不了库（四期栽过）。
// 重试提交后也按同一节奏刷新汇总区 —— 重试后该行转 `pending`，而不带 businessKey 的
// status **只回需要提示的终态** ⇒ 汇总区立刻少一项（看着像成功）；若再次失败，那一项
// 要到手动刷新才回来（假成功）。两条链共用同一预算。
const ZB_SW_POLL_MS = 3000
const ZB_SW_POLL_MAX = 15          // ~45s，覆盖 30s 重试窗口

let zbSwPollTimer = null
let zbSwPollLeft = 0
let zbSwPollGen = 0        // 每轮重试 +1：作废上一轮在途的 tick，防两条链并行

/** 停掉「保存后轮询」：作废在途 tick（它会在 await 回来后自行退出）+ 清在途定时器。 */
function stopZbSyncPoll() {
  _zbSyncGen++
  if (_zbSyncTimer) { clearTimeout(_zbSyncTimer); _zbSyncTimer = null }
}

/** 停掉「重试后汇总轮询」：同上（照 FbDataManage 的世代号 + 清定时器做法）。 */
function stopZbSwPoll() {
  zbSwPollGen++
  zbSwPollLeft = 0
  if (zbSwPollTimer) { clearTimeout(zbSwPollTimer); zbSwPollTimer = null }
}

/** 汇总区数据源：只取本 target 的终态；拉不到不该打扰用户，保持上一次结果。 */
async function loadZbSwFailures() {
  try {
    const res = await sheetWriteApi.status({ platform: 'gg', target: ZB_SW_TARGET })
    // 显式跳过中间态 **且** 不展示 synced：端点本就只回需要提示的终态，这里再兜一层，
    // 防「中间态 / 成功态误入汇总区」被当成已落定的失败（本功能反复踩过的坑）。
    zbSwFailures.value = (res.items || []).filter(
      f => f.status !== 'pending' && f.status !== 'failed' && f.status !== 'synced')
  } catch { /* 汇总拉不到不该打扰用户，保持上一次结果 */ }
}

/** 重试提交后按固定节奏刷新汇总区，有界（15 次后自动停）。
 *  全程不弹任何提示 —— 中间态与终态都由汇总区自身呈现，避免打断 / 重复提示。 */
function scheduleZbSwRefresh() {
  const gen = ++zbSwPollGen                       // 开新一轮：作废上一轮（连点重试不叠链）
  if (zbSwPollTimer) { clearTimeout(zbSwPollTimer); zbSwPollTimer = null }
  zbSwPollLeft = ZB_SW_POLL_MAX
  const tick = async () => {
    zbSwPollTimer = null
    if (gen !== zbSwPollGen || zbSwPollLeft <= 0) return   // 已被新一轮取代 / 到顶 / 已卸载即停
    zbSwPollLeft--
    await loadZbSwFailures()
    if (gen !== zbSwPollGen || zbSwPollLeft <= 0) return
    zbSwPollTimer = setTimeout(tick, ZB_SW_POLL_MS)
  }
  zbSwPollTimer = setTimeout(tick, ZB_SW_POLL_MS)
}

/** 逐条重试：提交 → 立即刷新 → 起有界轮询跟结果。 */
async function retryZbSw(f) {
  try {
    await sheetWriteApi.retry({ platform: 'gg', target: ZB_SW_TARGET,
                                businessKey: f.business_key })
    ElMessage.success('已重新提交，请稍后查看结果')
    await loadZbSwFailures()
    scheduleZbSwRefresh()
  } catch (e) { ElMessage.error(e.response?.data?.error || '重试失败') }
}

// 选择产品时刷新失败汇总区（沿用本页「切产品即查一次」的既有节奏），
// 并停掉上一条保存后的轮询（它跟的是上一个产品的结果）。
watch(zbSelectedProduct, () => {
  stopZbSyncPoll()
  loadZbSwFailures()
})

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

// 转点后自动把做表日期更新为新的「昨天」，避免隔天仍用旧日期覆盖数据
function scheduleZbMidnightRefresh() {
  if (_zbMidnightTimer) clearTimeout(_zbMidnightTimer)
  const now = new Date()
  const nextMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 0)
  _zbMidnightTimer = setTimeout(() => {
    zbSelectedDate.value = _yesterday()
    scheduleZbMidnightRefresh()
  }, nextMidnight.getTime() - now.getTime() + 1000)
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
      is_yanghu: keywords.some(kw => (row.campaign || '').toLowerCase().includes(kw.toLowerCase())),
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
      is_yanghu: keywords.some(kw => (row.campaign || '').toLowerCase().includes(kw.toLowerCase())),
    }))
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
    if (res.warning) {
      ElMessage.warning({ message: res.warning, duration: 8000, showClose: true })
    }
    // 启动轮询检测同步结果
    startZbSyncPolling()
  } catch (e) {
    ElMessage.error('更新表格失败: ' + (e.response?.data?.error || e.message))
  }
  zbUpdatingSheet.value = false
}

// 保存后按 business_key（= 产品名）轮询本次写表结果 —— 与四期 FB 提取页同形。
// 中间态（pending / failed）静默续查、**只在终态提示**：后端首次失败先落中间态 failed
// → 睡 30s → 重试 → 终态最早 ~30s 才落库，窗口短于 30s 会把「走过后端重试」的终态全
// 排除在提示之外（四期栽过）。失败文案复用 sheetWriteUi 的唯一文案源；成功确认是本页
// 自己的一句（成功不属于「失败治理三态语汇」，见 sheetWriteUi.js 自述）。
function startZbSyncPolling() {
  const businessKey = zbSelectedProduct.value
  if (!businessKey) return
  stopZbSyncPoll()                 // 作废上一轮在途 tick（连点保存不叠链）
  const gen = _zbSyncGen           // 本轮世代号
  let attempts = 0
  const poll = async () => {
    if (gen !== _zbSyncGen) return // 已被新一轮 / 卸载取代
    if (attempts >= ZB_SW_POLL_MAX) {
      // 非「中间态报警」，而是「无法确认结果」的告知：把用户指到能查看 / 重试的地方
      ElMessage.warning('写表结果未返回，请稍后在本页汇总区查看或重试')
      loadZbSwFailures()
      return
    }
    attempts++
    try {
      const res = await sheetWriteApi.status({
        platform: 'gg', target: ZB_SW_TARGET, businessKey,
      })
      if (gen !== _zbSyncGen) return
      const it = res.item
      if (!it) return                             // 无记录 = 这条路径没触发写表
      if (it.target !== ZB_SW_TARGET) return      // 被同期其它 target 遮蔽时误判
      if (it.status === 'synced') { loadZbSwFailures(); ElMessage.success('✅ 写表成功'); return }
      if (it.status === 'pending' || it.status === 'failed') {
        _zbSyncTimer = setTimeout(poll, ZB_SW_POLL_MS)
        return
      }
      // 需提示的终态（retry_failed 等）：文案与汇总区 / 工具提示同源
      SHEET_WRITE_TOAST[sheetWriteTone(it.status)](sheetWriteHint(it))
      loadZbSwFailures()
    } catch {
      if (gen !== _zbSyncGen) return                  // 已被新一轮 / 卸载取代即停
      _zbSyncTimer = setTimeout(poll, ZB_SW_POLL_MS)  // 查询失败不打扰用户，续查
    }
  }
  // 3 秒后开始第一次检查（给后台线程一点时间）
  _zbSyncTimer = setTimeout(poll, ZB_SW_POLL_MS)
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
      isSevenCols: zbSevenCols.value,
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
onUnmounted(() => {
  _revokeAudioBlobs()
  stopZbSyncPoll()               // 保存后轮询：作废在途 tick + 清掉在途定时器
  stopZbSwPoll()                 // 重试后汇总轮询：同上
  if (_zbMidnightTimer) clearTimeout(_zbMidnightTimer)
})

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
  // 优先用后端下发的签名 URL；`||` 只是防前端崩的退路 —— 服务端已收口，
  // 自拼 URL 必然 401，不是可用路径。
  window.open(item.download_url || `/api/audio-replace/download?path=${encodeURIComponent(item.output_path)}`, '_blank')
}

onMounted(() => { audioLoadHistory(); loadZbProducts(); loadZbSwFailures(); scheduleZbMidnightRefresh() })

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
