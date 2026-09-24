<template>
  <!-- 户管看板配置（子项目 B）。只有户管可见 —— 面板里另一张 sheet 卡片对户管是互斥的
       （GG 设置页：管理员专属 template；TT 设置页：v-if="!authStore.isHuguan"），
       所以本卡不存在主次并列。守卫留在组件内部，两个设置页都无条件挂载本组件。
       平台差异（GG / TT）全部由 platform 属性驱动。 -->
  <el-card v-if="authStore.isHuguan" shadow="never"
           style="margin-top:20px;border-left:3px solid #7c3aed;">
    <template #header>
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <span style="font-weight:600;">📊 户管看板配置</span>
        <span style="margin-left:8px;font-size:12px;font-weight:500;color:#7c3aed;">仅户管</span>
      </div>
    </template>

    <div v-loading="hdLoadingConfig">
      <!-- 分组 1 · 表格来源 -->
      <div style="margin-bottom:16px;">
        <div style="font-weight:500;font-size:13px;color:#374151;margin-bottom:6px;">Google 表格（URL 或 ID）</div>
        <div style="display:flex;gap:8px;">
          <el-input v-model="hdForm.spreadsheet_id"
                    placeholder="粘贴 Google 表格链接或直接输入 spreadsheet ID"
                    style="flex:1;" :disabled="hdBusy" />
          <el-button @click="readHdSheets" :loading="hdReading" :disabled="hdBusy">📋 读取工作表</el-button>
        </div>
        <div v-if="!hdSheetsLoaded" style="font-size:12px;color:#6b7280;margin-top:6px;">
          点击「📋 读取工作表」后可从下拉里选工作表，也可以直接手动输入
        </div>
        <div v-else style="font-size:12px;color:#047857;margin-top:6px;">
          ✅ 已加载 {{ hdSheets.length }} 个工作表可供选择
        </div>
      </div>

      <div style="margin-bottom:16px;">
        <div style="font-weight:500;font-size:13px;color:#374151;margin-bottom:6px;">工作表名</div>
        <el-select v-model="hdForm.sheet_name" filterable allow-create default-first-option
                   placeholder="选择或输入工作表名" style="width:100%;" :disabled="hdBusy">
          <el-option v-for="name in hdSheets" :key="name" :label="name" :value="name" />
          <template #empty>
            <div style="padding:8px 12px;font-size:12px;color:#6b7280;line-height:1.6;">
              这个表格里没有可读的工作表
            </div>
          </template>
        </el-select>
      </div>

      <div>
        <el-button type="primary" @click="saveHdConfig" :loading="hdSaving" :disabled="hdBusy">💾 保存配置</el-button>
        <span v-if="hdSaved" style="margin-left:8px;font-size:12px;color:#047857;">✅ 已保存</span>
      </div>

      <!-- 分组 2 · 看板同步 -->
      <div style="background:#f9fafb;border-radius:8px;padding:12px;margin-top:16px;">
        <div style="font-weight:600;font-size:13px;color:#374151;margin-bottom:6px;">看板同步</div>
        <div style="font-size:12px;color:#6b7280;margin-bottom:10px;">
          看板不会自动跟着系统变。左边按钮把系统数据写进表，右边按钮把表里的改动读回系统。
        </div>
        <el-tooltip content="请先填写表格地址、选择工作表并保存配置" placement="top"
                    :disabled="hdConfigured">
          <span style="display:inline-flex;gap:8px;">
            <el-button @click="pushDlg.visible = true" :loading="hdPushing"
                       :disabled="!hdConfigured || hdBusy">🔄 刷新到看板</el-button>
            <el-button @click="syncHd" :loading="hdSyncing"
                       :disabled="!hdConfigured || hdBusy">⬇️ 从表同步到系统</el-button>
          </span>
        </el-tooltip>
      </div>

      <el-alert v-if="hdHint.text" :title="hdHint.text" :type="hdHint.type" show-icon closable
                style="margin-top:12px;" @close="hdHintClosed = true" />
    </div>
  </el-card>

  <!-- 🔄 刷新到看板 · 二次确认（覆盖列清单按列分组呈现，纯文本装不下） -->
  <el-dialog v-if="authStore.isHuguan" v-model="pushDlg.visible" title="确认刷新到看板？"
             width="600px" top="8vh" :close-on-click-modal="false" @opened="focusPushCancel">
    <el-alert type="warning" show-icon :closable="false">
      <template #title>这会把系统里当前的数据整表写进你的看板表。</template>
    </el-alert>

    <div style="font-weight:600;font-size:14px;color:#374151;margin:16px 0 4px;">会覆盖的列</div>
    <div style="font-size:12px;color:#6b7280;margin-bottom:8px;">
      表中下列列的内容会被系统数据替换。你在表里改动过这些列、还没有同步回系统的，改动会丢失：
    </div>
    <el-table :data="hdPushCover" size="small" border>
      <el-table-column prop="col" label="列" width="80" />
      <el-table-column prop="head" label="表头" width="120" />
      <el-table-column prop="to" label="会被写成" />
    </el-table>

    <div style="font-weight:600;font-size:14px;color:#374151;margin:16px 0 4px;">不会改动的列</div>
    <div>
      <el-tag v-for="t in hdPushSafe" :key="t" size="small" type="info" effect="plain"
              style="margin:0 6px 6px 0;">{{ t }}</el-tag>
    </div>
    <div style="font-size:12px;color:#6b7280;margin-top:4px;">{{ hdPushSafeNote }}</div>
    <div style="font-size:12px;color:#6b7280;margin-top:8px;">{{ hdPushExtraNote }}</div>

    <el-alert type="info" show-icon :closable="false" style="margin-top:16px;">
      <template #title>建议：如果表里刚改过上面那几列，先点「⬇️ 从表同步到系统」把改动读回系统，再刷新到看板。</template>
    </el-alert>

    <template #footer>
      <el-button ref="pushCancelBtn" @click="pushDlg.visible = false">取消</el-button>
      <el-button type="warning" :loading="hdPushing" :disabled="hdPushing" @click="doPushHd">确认刷新</el-button>
    </template>
  </el-dialog>

  <!-- ⬇️ 从表同步到系统 · 差异报告（唯一的人工护栏：逐条勾选后才落库） -->
  <el-dialog v-if="authStore.isHuguan" v-model="syncDlg.visible" :title="syncTitle"
             width="880px" top="5vh" :close-on-click-modal="false" @opened="focusSyncCancel">
    <div style="max-height:70vh;overflow-y:auto;">
      <!-- Mode A · 预演 / 待确认 -->
      <div v-if="syncDlg.mode === 'A'">
        <el-alert v-if="syncDlg.applyError" type="error" show-icon :closable="false"
                  style="margin-bottom:12px;">
          <template #title>同步失败：{{ syncDlg.applyError }}</template>
          <div style="font-size:12px;">系统没有写入任何数据（或只写入了一部分），请重试。</div>
        </el-alert>

        <el-alert type="info" show-icon :closable="false">
          <template #title>预演结果。现在还没有写入系统，确认后才会生效。</template>
        </el-alert>

        <p style="font-size:13px;color:#374151;margin:12px 0 8px;">
          表里共 {{ hdSummary.total_in_sheet }} 行数据。下面是表和系统的差异，请核对后再确认。
        </p>

        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="表里数据行">{{ hdSummary.total_in_sheet }}</el-descriptions-item>
          <el-descriptions-item label="新增账户">{{ hdSummary.new_accounts }} 个</el-descriptions-item>
          <el-descriptions-item label="字段更新">{{ hdSummary.updates }} 处</el-descriptions-item>
          <el-descriptions-item label="归属变更">{{ hdSummary.owner_changes }} 个</el-descriptions-item>
          <el-descriptions-item label="跳过">{{ hdSummary.skipped }} 个</el-descriptions-item>
          <el-descriptions-item label="警告">{{ hdSummary.warnings }} 条</el-descriptions-item>
        </el-descriptions>

        <!-- ① 归属变更：置顶 + 户管紫左边框 + 默认不勾（改错人不可撤销） -->
        <div v-if="hdOwnerChanges.length"
             style="border-left:3px solid #7c3aed;padding-left:10px;margin:16px 0;">
          <div style="font-weight:600;font-size:14px;color:#374151;margin-bottom:6px;">① 归属变更</div>
          <div style="font-size:12px;color:#6b7280;margin-bottom:8px;">
            这些账户会换归属人。改错人不可撤销，请逐条核对后再勾选。
          </div>
          <el-alert type="warning" show-icon :closable="false" style="margin-bottom:8px;">
            <template #title>归属变更默认不勾选。勾选哪一行，哪一行的归属人就会变成「新归属」。</template>
          </el-alert>
          <el-table ref="ownerTblRef" :data="hdOwnerChanges" size="small" row-key="account_id"
                    border @selection-change="v => selOwner = v">
            <el-table-column type="selection" width="42" />
            <el-table-column label="表行" width="86">
              <template #default="{ row }">
                <el-tag size="small" type="info" effect="plain">第 {{ row.row }} 行</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="account_id" label="账户ID" min-width="150" show-overflow-tooltip />
            <el-table-column label="原归属" min-width="110">
              <template #default="{ row }">
                <span v-if="row.from">{{ row.from }}</span>
                <span v-else style="color:#6b7280;">（未分配）</span>
              </template>
            </el-table-column>
            <el-table-column label="→" width="40" align="center">
              <template #default><span aria-hidden="true">→</span></template>
            </el-table-column>
            <el-table-column label="新归属" min-width="110">
              <template #default="{ row }">
                <span style="font-weight:600;color:#7c3aed;">{{ row.to }}</span>
              </template>
            </el-table-column>
            <el-table-column label="来源" width="110">
              <template #default="{ row }">{{ hdViaLabel(row.via) }}</template>
            </el-table-column>
          </el-table>
        </div>

        <!-- ② 将清空：不可逆，常显、不折叠 -->
        <div v-if="hdClearing.length" style="margin:16px 0;">
          <el-alert type="error" show-icon :closable="false">
            <template #title>有 {{ hdSummary.clears }} 个字段将被清空（不可撤销）</template>
            <div style="font-size:12px;">表里这些列是空的，同步后系统里对应的值会被清掉。</div>
          </el-alert>
          <el-table :data="hdClearingShown" size="small" border style="margin-top:8px;">
            <el-table-column label="表行" width="86">
              <template #default="{ row }">
                <el-tag size="small" type="info" effect="plain">第 {{ row.row }} 行</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="account_id" label="账户ID" min-width="150" show-overflow-tooltip />
            <el-table-column label="将被清空的字段" min-width="200">
              <template #default="{ row }">
                <el-tag v-for="k in row.clears" :key="k" size="small" type="danger" effect="plain"
                        style="margin:0 6px 4px 0;">{{ hdFieldLabel(k) }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="hdClearing.length > 20" style="margin-top:6px;font-size:12px;color:#6b7280;">
            …另有 {{ hdClearing.length - 20 }} 行
            <el-button v-if="!clearingExpanded" link type="primary" @click="clearingExpanded = true">展开全部</el-button>
          </div>
        </div>

        <!-- ③ 新增账户（默认勾选） -->
        <div v-if="hdCreate.length" style="margin:16px 0;">
          <div style="font-weight:600;font-size:14px;color:#374151;margin-bottom:6px;">② 新增账户</div>
          <div style="font-size:12px;color:#6b7280;margin-bottom:8px;">这些账户在系统里还没有，确认后会新建。</div>
          <el-table ref="createTblRef" :data="hdCreate" size="small" row-key="account_id"
                    border @selection-change="v => selCreate = v">
            <el-table-column type="selection" width="42" />
            <el-table-column label="表行" width="86">
              <template #default="{ row }">
                <el-tag size="small" type="info" effect="plain">第 {{ row.row }} 行</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="account_id" label="账户ID" min-width="150" show-overflow-tooltip />
            <el-table-column label="归属人" min-width="110">
              <template #default="{ row }">
                <el-tooltip v-if="!row.owner_name" placement="top"
                            content="新建后这个账户没有归属人，普通用户看不到它，只有户管和管理员可见。改归属请用账户面板的「户归属」列。">
                  <el-tag size="small" type="warning" effect="plain">未分配</el-tag>
                </el-tooltip>
                <span v-else>{{ row.owner_name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="待新建状态" min-width="110">
              <template #default="{ row }">
                <el-tag v-if="row.pending_status" size="small" type="warning" effect="plain">{{ row.pending_status }}</el-tag>
                <span v-else>—</span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- ④ 字段更新（默认勾选，展开给「字段 → 新值」明细） -->
        <div v-if="hdUpdate.length" style="margin:16px 0;">
          <div style="font-weight:600;font-size:14px;color:#374151;margin-bottom:6px;">③ 字段更新</div>
          <div style="font-size:12px;color:#6b7280;margin-bottom:8px;">这些账户在系统里已有，部分字段会按表里的值覆盖。</div>
          <el-table ref="updateTblRef" :data="hdUpdate" size="small" row-key="account_id"
                    border @selection-change="v => selUpdate = v">
            <el-table-column type="selection" width="42" />
            <el-table-column type="expand" width="42">
              <template #default="{ row }">
                <el-table :data="hdFieldsList(row)" size="small" style="margin-left:84px;width:auto;">
                  <el-table-column prop="label" label="字段" width="140" />
                  <el-table-column label="新值">
                    <template #default="{ row: f }">
                      <span :style="f.cleared ? 'color:#f56c6c;font-weight:500;' : ''">{{ f.value }}</span>
                    </template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column label="表行" width="86">
              <template #default="{ row }">
                <el-tag size="small" type="info" effect="plain">第 {{ row.row }} 行</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="account_id" label="账户ID" min-width="150" show-overflow-tooltip />
            <el-table-column label="改动" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ hdChangedText(row.fields) }}</template>
            </el-table-column>
            <el-table-column label="含清空" width="100">
              <template #default="{ row }">
                <el-tag v-if="(row.clears || []).length" size="small" type="danger" effect="plain">
                  ⚠ {{ row.clears.length }} 项
                </el-tag>
                <span v-else>—</span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- ⑤ 跳过（折叠） -->
        <el-collapse v-if="hdSkip.length" style="margin-top:8px;">
          <el-collapse-item name="skip">
            <template #title>
              <span style="font-weight:600;">④ 跳过 · {{ hdSkip.length }} 个</span>
              <span style="margin-left:12px;font-size:12px;color:#6b7280;">系统里已删除的账户，本次不动。</span>
            </template>
            <el-table :data="hdSkip" size="small" border>
              <el-table-column label="表行" width="86">
                <template #default="{ row }">
                  <el-tag size="small" type="info" effect="plain">第 {{ row.row }} 行</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="account_id" label="账户ID" min-width="150" show-overflow-tooltip />
              <el-table-column prop="reason" label="原因" min-width="160" />
            </el-table>
          </el-collapse-item>
        </el-collapse>

        <!-- ⑥ 警告（折叠） -->
        <el-collapse v-if="hdWarnings.length" style="margin-top:8px;">
          <el-collapse-item name="warn">
            <template #title>
              <span style="font-weight:600;">⑤ 警告 · {{ hdWarnings.length }} 条</span>
              <span style="margin-left:12px;font-size:12px;color:#6b7280;">这些行没能同步，需要你去表里改。</span>
            </template>
            <el-table :data="hdWarnings" size="small" border>
              <el-table-column label="表行" width="86">
                <template #default="{ row }">
                  <el-tag size="small" type="info" effect="plain">第 {{ row.row }} 行</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="说明" min-width="220">
                <template #default="{ row }">
                  <el-tag size="small" type="warning" effect="plain" style="margin-right:6px;">⚠</el-tag>{{ hdWarnText(row.message) }}
                </template>
              </el-table-column>
            </el-table>
          </el-collapse-item>
        </el-collapse>
      </div>

      <!-- Mode B · 结果报告（停在这里不自动关，not_applied 不能被 toast 吞掉） -->
      <div v-else>
        <el-alert type="success" show-icon :closable="false">
          <template #title>同步完成</template>
          <div style="font-size:12px;">
            新增 {{ hdResult.created }} 个账户，更新 {{ hdResult.updated }} 处，归属变更 {{ hdResult.owner_changed }} 个。
          </div>
        </el-alert>

        <el-alert v-if="hdResult.owner_changed" type="info" show-icon :closable="false"
                  style="margin-top:12px;">
          <template #title>{{ hdWriteBackText }}</template>
        </el-alert>

        <el-alert v-if="(hdResult.errors || []).length" type="error" show-icon :closable="false"
                  style="margin-top:12px;">
          <template #title>有 {{ hdResult.errors.length }} 行出错，没有写入</template>
          <div style="font-size:12px;">下面这些行在落库时报错，系统没有写入它们，请检查后重试。</div>
        </el-alert>
        <el-table v-if="(hdResult.errors || []).length" :data="hdResult.errors" size="small"
                  border style="margin-top:8px;">
          <el-table-column label="表行" width="86">
            <template #default="{ row }">
              <el-tag size="small" type="info" effect="plain">第 {{ row.row }} 行</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="error" label="错误" min-width="220" show-overflow-tooltip />
        </el-table>

        <template v-if="(hdResult.not_applied || []).length">
          <el-alert type="warning" show-icon :closable="false" style="margin-top:12px;">
            <template #title>有 {{ hdResult.not_applied.length }} 项没有落库（确认之后表又变了）</template>
            <div style="font-size:12px;">
              下面这些你在预演里勾选的项，在确认前表被改动了，系统找不到对应账户，已跳过。请重新点「⬇️ 从表同步到系统」再看一次。
            </div>
          </el-alert>
          <el-table :data="hdNotAppliedShown" size="small" border style="margin-top:8px;">
            <el-table-column prop="account_id" label="账户ID" min-width="150" show-overflow-tooltip />
            <el-table-column label="类别" width="120">
              <template #default="{ row }">{{ hdCategoryLabel(row.category) }}</template>
            </el-table-column>
          </el-table>
          <div v-if="hdResult.not_applied.length > 20" style="margin-top:6px;font-size:12px;color:#6b7280;">
            …另有 {{ hdResult.not_applied.length - 20 }} 条
          </div>
        </template>
      </div>
    </div>

    <template #footer>
      <div style="display:flex;align-items:center;">
        <template v-if="syncDlg.mode === 'A'">
          <span style="font-size:12px;color:#6b7280;margin-right:auto;">
            <template v-if="selectedCount === 0">还没有勾选任何项</template>
            <template v-else-if="selOwner.length === 0 && hdOwnerChanges.length">已选 {{ selectedCount }} 项（归属变更未勾选，这些账户的归属人不会变）</template>
            <template v-else>已选 {{ selectedCount }} 项（其中归属变更 {{ selOwner.length }} 项）</template>
          </span>
          <template v-if="syncDlg.applyError">
            <el-button @click="syncDlg.visible = false">关闭</el-button>
            <el-button type="primary" :loading="syncDlg.applying" :disabled="syncDlg.applying"
                       @click="applySync">重试</el-button>
          </template>
          <template v-else>
            <el-button ref="syncCancelBtn" @click="syncDlg.visible = false">取消</el-button>
            <el-button :type="confirmType" :loading="syncDlg.applying"
                       :disabled="selectedCount === 0 || syncDlg.applying" @click="applySync">
              <template v-if="selectedCount === 0">确认同步（请先勾选）</template>
              <template v-else>确认同步（已选 {{ selectedCount }} 项）</template>
            </el-button>
          </template>
        </template>
        <template v-else>
          <div style="margin-left:auto;">
            <el-button type="primary" @click="syncDlg.visible = false">关闭</el-button>
          </div>
        </template>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed, nextTick, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { huguanApi } from '@/api/huguan'
import { ElMessage } from 'element-plus'
import api from '@/api/client'

const authStore = useAuthStore()

// ===========================================================================
// 户管看板配置（子项目 B）
//
// 视觉设计：docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md
//   卡片 §2 / 「刷新到看板」二次确认 §3 / 差异报告对话框 §4 / 标签映射 §4.9
// 平台差异只有三处：platform、读 res.config[platform]、中文列名按该平台的
// COLUMN_SPEC 走（GG：运营 / 重新分配；TT：接户运营 / 换绑情况 / BC / 消耗…）。
// ===========================================================================
const props = defineProps({
  platform: { type: String, required: true, validator: v => ['gg', 'tt'].includes(v) },
})

// 平台标识：本组件由 GG / TT 两个设置页共用。传入的 platform 是静态字面量
// （两个页面各挂一次，不会中途变化），因此按普通常量使用即可。
const HD_PLATFORM = props.platform


const hdForm = ref({ spreadsheet_id: '', sheet_name: '' })
const hdSheets = ref([])
const hdSheetsLoaded = ref(false)
const hdLoadingConfig = ref(false)
const hdReading = ref(false)
const hdSaving = ref(false)
const hdPushing = ref(false)
const hdSyncing = ref(false)
const hdSaved = ref(false)
const hdHintMsg = ref('')
const hdHintType = ref('info')
const hdHintClosed = ref(false)
let hdSavedTimer = null

const pushCancelBtn = ref(null)
const syncCancelBtn = ref(null)
const ownerTblRef = ref(null)
const createTblRef = ref(null)
const updateTblRef = ref(null)

const pushDlg = reactive({ visible: false })
const syncDlg = reactive({ visible: false, mode: 'A', applyError: '', applying: false })
const clearingExpanded = ref(false)

const syncDiff = ref(null)
const syncResult = ref(null)
const selOwner = ref([])
const selCreate = ref([])
const selUpdate = ref([])

const hdBusy = computed(() =>
  hdReading.value || hdSaving.value || hdPushing.value || hdSyncing.value || syncDlg.applying)
const hdConfigured = computed(() => !!(hdForm.value.spreadsheet_id && hdForm.value.sheet_name))

// 提示条三态：显式消息 > 未配置空态 > 无。type 只跟着显式消息走。
const hdHint = computed(() => {
  if (hdHintClosed.value) return { text: '', type: 'info' }
  if (hdHintMsg.value) return { text: hdHintMsg.value, type: hdHintType.value }
  if (authStore.isHuguan && !hdConfigured.value) {
    return { text: '还没配置看板表格。填写表格地址和工作表名，点「💾 保存配置」后才能同步。', type: 'info' }
  }
  return { text: '', type: 'info' }
})
function setHdHint(text, type = 'info') {
  hdHintMsg.value = text
  hdHintType.value = type
  hdHintClosed.value = false
}

// ---------- 标签映射（全部来自设计 §4.9 / §4.10，逐字） ----------

// via 是后端稳定 token，不是给人看的文字：**不得**渲染裸 token。
// 四个中文名与 py/huguan_dashboard.py 的 COLUMN_SPEC 表头（:24-56）逐字一致 ——
// 户管要拿这个词去自己的表里找到那一列，多一个「列」字他就找不到。
const VIA_LABELS = {
  gg: { owner_channel: '重新分配', owner_name: '运营' },
  tt: { owner_channel: '换绑情况', owner_name: '接户运营' },
}
// 未知键一律原样显示，绝不隐藏（宁可露出英文，也不静默丢一条差异）
const FIELD_LABELS = {
  gg: {
    acquired_date: '到手时间',
    timezone: '时区',
    mcc_id: '所属 MCC',
    agent_id: '所属渠道',
    status_id: '状态',
    // 合成键，_collect_updates 会无条件写进 fields：不映射就会露出 _is_dead
    _is_dead: '是否封户',
  },
  tt: {
    acquired_date: '入库时间',
    country: '国家',
    timezone: '时区',
    consumption: '消耗',
    remark: '产品信息',
    bc_id: 'BC',
    agent_id: '所属渠道',
    status_id: '状态',
    _is_dead: '是否回收',
  },
}
// 后端 warnings[].message 会夹带英文字段名，展示前替换（纯展示层）
const WARN_TOKENS = { agent_name: '所属渠道', bc_name: 'BC', mcc_name: '所属 MCC', status_name: '状态' }
const CATEGORY_LABELS = { create: '新增', update: '字段更新', owner: '归属变更' }
const OWNER_WRITEBACK_TEXT = {
  gg: '表里「运营」列已改写成新归属名，「重新分配」列已清空。下次同步不会重复应用这些变更。',
  tt: '表里「接户运营」列已改写成新归属名，「换绑情况」列已清空。下次同步不会重复应用这些变更。',
}

function hdViaLabel(via) { return (VIA_LABELS[HD_PLATFORM] || {})[via] ?? '—' }
function hdFieldLabel(key) { return (FIELD_LABELS[HD_PLATFORM] || {})[key] ?? key }
function hdCategoryLabel(cat) { return CATEGORY_LABELS[cat] ?? cat }
function hdWarnText(message) {
  let out = String(message ?? '')
  Object.keys(WARN_TOKENS).forEach(k => { out = out.split(k).join(WARN_TOKENS[k]) })
  return out
}
const hdWriteBackText = OWNER_WRITEBACK_TEXT[HD_PLATFORM]

function hdFieldNewValue(value, cleared) {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (cleared || value === '' || value === null || value === undefined) return '（清空）'
  return String(value)
}
function hdFieldsList(row) {
  const fields = row.fields || {}
  const clears = row.clears || []
  return Object.keys(fields).map(k => ({
    label: hdFieldLabel(k),
    value: hdFieldNewValue(fields[k], clears.includes(k)),
    cleared: clears.includes(k),
  }))
}
// 「改动」列：中文名用「、」连接，超 3 个压成「甲、乙、丙 等 4 项」
function hdChangedText(fields) {
  const names = Object.keys(fields || {}).map(hdFieldLabel)
  if (!names.length) return '—'
  if (names.length > 3) return `${names.slice(0, 3).join('、')} 等 ${names.length} 项`
  return names.join('、')
}

// ---------- 覆盖列清单（「刷新到看板」二次确认用，设计 §3.4） ----------
// 只列**户管可能手改的列**（改了会丢）；A/B/C 三列系统本来就当权威，收进下面那行
// 「另外系统还会…」。清单与 py/huguan_dashboard.py 的 cells_for_row 实际写入列一致。
const PUSH_COVER = {
  gg: [
    { col: 'D 列', head: 'MCC', to: '系统里的「所属 MCC」' },
    { col: 'F 列', head: '所属渠道', to: '系统里的「代理」' },
    { col: 'G 列', head: '运营', to: '系统里的「归属人」' },
    { col: 'I 列', head: '时区', to: '系统里的「时区」' },
    { col: 'J 列', head: '大MCC', to: '由 MCC 自动推出' },
    { col: 'K 列', head: '状态', to: '系统里的「状态」' },
  ],
  tt: [
    { col: 'D 列', head: 'BC', to: '系统里的「BC」' },
    { col: 'E 列', head: '国家', to: '系统里的「国家」' },
    { col: 'F 列', head: '所属渠道', to: '系统里的「代理」' },
    { col: 'G 列', head: '接户运营', to: '系统里的「归属人」' },
    { col: 'H 列', head: '时区', to: '系统里的「时区」' },
    { col: 'I 列', head: '状态', to: '系统里的「状态」' },
    { col: 'J 列', head: '消耗', to: '系统里的「消耗」' },
    { col: 'M 列', head: '产品信息', to: '系统里的「备注」' },
  ],
}
const PUSH_SAFE = {
  gg: ['E 列 · 国家', 'H 列 · 重新分配', 'L 列 · 位置', 'M 列 · 消耗', 'N 列 · 产品信息'],
  tt: ['K 列 · 位置', 'L 列 · 换绑情况'],
}
const PUSH_SAFE_NOTE = {
  gg: '其中「重新分配」列是你在表里填归属变更的通道，系统永远不碰它。',
  tt: '其中「换绑情况」列是你在表里填归属变更的通道，系统永远不碰它。',
}
const PUSH_EXTRA_NOTE = {
  gg: '另外系统还会按自己的数据重写：A 列 · 日期、B 列 · 是否封户、C 列 · 账户ID。表里有、系统里没有的账户不会被写入，只会在结果里报一个数。',
  tt: '另外系统还会按自己的数据重写：A 列 · 入库时间、B 列 · 是否回收、C 列 · 账户ID。表里有、系统里没有的账户不会被写入，只会在结果里报一个数。',
}
const hdPushCover = computed(() => PUSH_COVER[HD_PLATFORM] || [])
const hdPushSafe = computed(() => PUSH_SAFE[HD_PLATFORM] || [])
const hdPushSafeNote = PUSH_SAFE_NOTE[HD_PLATFORM]
const hdPushExtraNote = PUSH_EXTRA_NOTE[HD_PLATFORM]

// ---------- 差异对话框的派生数据 ----------
const hdSummary = computed(() => (syncDiff.value && syncDiff.value.summary) || {})
const hdOwnerChanges = computed(() => (syncDiff.value && syncDiff.value.owner_changes) || [])
const hdCreate = computed(() => (syncDiff.value && syncDiff.value.to_create) || [])
const hdUpdate = computed(() => (syncDiff.value && syncDiff.value.to_update) || [])
const hdSkip = computed(() => (syncDiff.value && syncDiff.value.to_skip) || [])
const hdWarnings = computed(() => (syncDiff.value && syncDiff.value.warnings) || [])
const hdClearing = computed(() => hdUpdate.value.filter(x => (x.clears || []).length))
const hdClearingShown = computed(() => clearingExpanded.value ? hdClearing.value : hdClearing.value.slice(0, 20))
const hdResult = computed(() => syncResult.value || {})
const hdNotAppliedShown = computed(() => (hdResult.value.not_applied || []).slice(0, 20))

const selectedCount = computed(() => selCreate.value.length + selUpdate.value.length + selOwner.value.length)
// 只有「这次点下去会不可逆地清空字段」才染红（永远染红等于没染）
const willClear = computed(() => selUpdate.value.some(x => (x.clears || []).length))
const confirmType = computed(() => willClear.value ? 'danger' : 'primary')

const syncTitle = computed(() => {
  if (syncDlg.mode === 'B') return '从表同步到系统 · 同步结果'
  const name = hdForm.value.sheet_name || ''
  // 工作表名太长会撑爆标题：省略，完整名交给 el-dialog 的原生 title tooltip
  return name.length > 20 ? '从表同步到系统' : `从表同步到系统 · 工作表「${name}」`
})

function focusPushCancel() { pushCancelBtn.value?.$el?.focus?.() }
function focusSyncCancel() {
  // 焦点落在「取消」而不是确认键：避免连按回车误提交（设计 §6.1）
  if (syncDlg.mode === 'A' && !syncDlg.applyError) syncCancelBtn.value?.$el?.focus?.()
}

// ---------- 卡片动作 ----------
async function loadHdConfig() {
  if (!authStore.isHuguan) return
  hdLoadingConfig.value = true
  try {
    const res = await huguanApi.getConfig()
    const conf = (res.config && res.config[HD_PLATFORM]) || {}
    hdForm.value = {
      spreadsheet_id: conf.spreadsheet_id || '',
      sheet_name: conf.sheet_name || '',
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '读取看板配置失败')
  } finally {
    hdLoadingConfig.value = false
  }
}

async function readHdSheets() {
  if (!hdForm.value.spreadsheet_id) { ElMessage.warning('请先填表格 ID 或链接'); return }
  hdReading.value = true
  try {
    const res = await api.get('/google-sheets/sheets', {
      params: { spreadsheet_id: hdForm.value.spreadsheet_id },
    })
    // 该端点返回的是对象数组 [{name, gid, rowCount}]，必须取 name（同本文件 readSheets）
    hdSheets.value = (res.sheets || [])
      .map(s => (typeof s === 'string' ? s : s && s.name))
      .filter(Boolean)
    hdSheetsLoaded.value = true
    if (hdSheets.value.length) ElMessage.success(`已读取 ${hdSheets.value.length} 个工作表`)
    else ElMessage.warning('这个表格里没有可读的工作表，请检查表格地址或表格权限。')
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '读取工作表失败')
  } finally {
    hdReading.value = false
  }
}

async function saveHdConfig() {
  hdSaving.value = true
  try {
    await huguanApi.saveConfig({
      platform: HD_PLATFORM,
      spreadsheet_id: hdForm.value.spreadsheet_id,
      sheet_name: hdForm.value.sheet_name,
    })
    ElMessage.success('配置已保存')
    hdSaved.value = true
    clearTimeout(hdSavedTimer)
    hdSavedTimer = setTimeout(() => { hdSaved.value = false }, 2000)
    if (hdConfigured.value) hdHintMsg.value = ''
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '保存配置失败')
  } finally {
    hdSaving.value = false
  }
}

async function doPushHd() {
  pushDlg.visible = false
  hdPushing.value = true
  try {
    const res = await huguanApi.push(HD_PLATFORM)
    const r = res.result || {}
    const notFound = (r.not_found || []).length
    if (notFound) {
      // 表里没有的账户是**正常结果**不是失败，所以用 warning
      ElMessage.warning(`有 ${notFound} 个账户不在你的表里，未写入。`)
      setHdHint(`已刷新到看板：写入 ${r.updated} 行。有 ${notFound} 个账户不在你的表里，没有写入。`, 'warning')
    } else {
      ElMessage.success(`已刷新到看板：写入 ${r.updated} 行。`)
      setHdHint(`已刷新到看板：写入 ${r.updated} 行。`, 'success')
    }
  } catch (e) {
    // 逐行写、失败即中断：Google 可能已经写入一部分，不能只说「失败」
    setHdHint('刷新到看板失败。Google 可能已经写入了一部分，请打开表格核对后再重试。', 'error')
  } finally {
    hdPushing.value = false
  }
}

async function syncHd() {
  hdSyncing.value = true
  try {
    const res = await huguanApi.sync({ platform: HD_PLATFORM, dry_run: true })
    const d = res.diff || {}
    const s = d.summary || {}
    // warnings 必须一起判：表里运营名写错（系统里没有这个名字）这类差异**只**
    // 产生警告，不产生 new_accounts / updates / owner_changes 任何一条。漏掉它
    // 就会把「表里有行没同步上」当成「已经一致」整份丢掉 —— 既不弹警告面板，
    // 用户也永远不知道表里有行没同步上。
    if (!s.new_accounts && !s.updates && !s.owner_changes && !s.warnings) {
      setHdHint('看板与系统已经一致，没有需要同步的改动。', 'info')
      return
    }
    await openSyncDialog(d)
  } catch (e) {
    ElMessage.error(e?.response?.data?.error || '从表同步到系统失败')
  } finally {
    hdSyncing.value = false
  }
}

async function openSyncDialog(diff) {
  syncDiff.value = diff
  syncResult.value = null
  syncDlg.applyError = ''
  syncDlg.mode = 'A'
  clearingExpanded.value = false
  selOwner.value = []
  selCreate.value = []
  selUpdate.value = []
  syncDlg.visible = true

  // 默认勾选：新增/更新是这次操作的预期目的，全勾；归属变更是**改别人的户**，
  // 默认不勾 —— 户管必须逐条主动点，才算「逐个确认才落库」（设计 §4.4）。
  await nextTick()
  setTimeout(() => {
    const createRows = diff.to_create || []
    const updateRows = diff.to_update || []
    // 上一轮的勾选状态会留在表格内部：先清干净，否则「上一条 diff 里有、
    // 这一条 diff 里没有」的行会带着勾选被提交，落库时进 not_applied。
    ownerTblRef.value?.clearSelection()
    createTblRef.value?.clearSelection()
    updateTblRef.value?.clearSelection()
    createRows.forEach(r => createTblRef.value?.toggleRowSelection(r, true))
    updateRows.forEach(r => updateTblRef.value?.toggleRowSelection(r, true))
  }, 100)
}

async function applySync() {
  syncDlg.applying = true
  syncDlg.applyError = ''
  try {
    const applied = await huguanApi.sync({
      platform: HD_PLATFORM,
      dry_run: false,
      confirmed: {
        create: selCreate.value.map(x => x.account_id),
        update: selUpdate.value.map(x => x.account_id),
        owner: selOwner.value.map(x => x.account_id),
      },
    })
    syncResult.value = applied.result || {}
    syncDlg.mode = 'B'
    const r = syncResult.value
    const line = `已同步：新增 ${r.created} 个账户，更新 ${r.updated} 处，归属变更 ${r.owner_changed} 个。`
    ElMessage.success(line)
    if ((r.not_applied || []).length) {
      setHdHint(`${line}有 ${r.not_applied.length} 项没有落库。`, 'warning')
    } else {
      setHdHint(line, 'success')
    }
  } catch (e) {
    // 落库失败不关弹窗：已勾选状态还在，户管可以直接重试
    syncDlg.applyError = e?.response?.data?.error || '从表同步到系统失败'
  } finally {
    syncDlg.applying = false
  }
}

onMounted(loadHdConfig)
</script>
