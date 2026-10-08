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
          <span style="display:inline-flex;gap:24px;align-items:center;flex-wrap:wrap;">
            <span style="display:inline-flex;gap:8px;align-items:center;">
              <el-button @click="pushDlg.visible = true" :loading="hdPushing"
                         :disabled="!hdConfigured || hdBusy">🔄 刷新到看板</el-button>
              <el-button @click="askUndo('push')" :loading="hdUndoing === 'push'"
                         :disabled="!hdUndo.push || hdBusy">↩️ 撤回上次</el-button>
              <span v-if="hdUndo.push" style="font-size:12px;color:#6b7280;">
                上一次：{{ hdUndoText('push') }}
              </span>
            </span>
            <span style="display:inline-flex;gap:8px;align-items:center;">
              <el-button @click="syncHd" :loading="hdSyncing"
                         :disabled="!hdConfigured || hdBusy">⬇️ 从表同步到系统</el-button>
              <el-button @click="askUndo('sync')" :loading="hdUndoing === 'sync'"
                         :disabled="!hdUndo.sync || hdBusy">↩️ 撤回上次</el-button>
              <span v-if="hdUndo.sync" style="font-size:12px;color:#6b7280;">
                上一次：{{ hdUndoText('sync') }}
              </span>
            </span>
          </span>
        </el-tooltip>
      </div>

      <!-- 写表失败汇总（三期）。只有户管能看见这张卡，而户管正是这些写表点的表主人
           —— 失败原先只落服务端日志，户管在这里才能看到并重试。
           有失败才渲染：无失败时连占位都没有（计划 §Task 6 的硬要求）。

           视觉：3px 琥珀左脊柱，与卡片自身「仅户管」的紫色左脊柱同一语法 —— 在卡片
           自己的视觉语法里声明「需要你处理」。用 warning 而非 danger：本期 4 个 target
           全部零回滚，retry_failed 的含义是「系统改动已生效、只是没写进表」，
           报红会把「表旧了」夸大成「数据坏了」。 -->
      <div v-if="hdSwFailures.length"
           style="background:var(--el-color-warning-light-9);border-left:3px solid var(--el-color-warning);border-radius:8px;padding:10px 12px;margin-top:12px;">
        <!-- 量词用「项」不用「账户」：hdSwFailures 的粒度是 (target, business_key) 一行，
             一次换绑会同时产生 huguan_dashboard + huguan_owner_channel 两条
             （FB 编辑则为 huguan_dashboard + huguan_fb_acceptor）—— 按「账户」数会把
             一个账户显示成「2 个账户」。与卡片既有词汇一致（applySync 写的是「有 N 项没有落库」）。 -->
        <div style="font-weight:600;font-size:13px;color:#92400e;margin-bottom:6px;">
          ⚠️ {{ hdSwFailures.length }} 项没写进表
        </div>
        <div v-for="(f, i) in hdSwFailures" :key="f.target + '|' + f.business_key"
             :style="{ display:'flex', alignItems:'baseline', gap:'8px', padding:'5px 0',
                       borderTop: i ? '1px solid var(--el-color-warning-light-7)' : 'none' }">
          <!-- 全句文案挂在 ID 上：那里是用户识别这条记录时视线落点，
               且复用 sheetWriteUi 的唯一文案源（不要在这里另写一份失败说明）。 -->
          <el-tooltip placement="top" :content="sheetWriteHint(f)">
            <span style="font-family:monospace;font-size:12px;color:#374151;flex:none;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ f.business_key }}</span>
          </el-tooltip>
          <span style="font-size:12px;color:#6b7280;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ f.error_msg || '未知原因' }}</span>
          <el-button link size="small" :type="sheetWriteTone(f.status)"
                     @click="retryHdSw(f)">重试</el-button>
        </div>
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

  <!-- ↩️ 撤回上次 · 结果报告（与差异报告同一口径：冲突 / 保留 / 表里找不到的行都逐条列出，
       不能只弹一个「成功 N 项」—— spec §八 明文要求） -->
  <el-dialog v-if="authStore.isHuguan" v-model="undoDlg.visible" :title="undoTitle"
             width="760px" top="8vh" :close-on-click-modal="false">
    <div style="max-height:70vh;overflow-y:auto;">
      <el-alert v-if="undoDlg.error" type="error" show-icon :closable="false">
        <template #title>撤回失败：{{ undoDlg.error }}</template>
        <div style="font-size:12px;">本次没有撤回任何内容，请重试。</div>
      </el-alert>

      <template v-else>
        <el-alert type="success" show-icon :closable="false">
          <template #title>{{ undoDoneText }}</template>
        </el-alert>

        <!-- 冲突：同步之后被别人改过，一律跳过、不覆盖 -->
        <div v-if="undoConflicts.length" style="margin-top:14px;">
          <el-alert type="warning" show-icon :closable="false">
            <template #title>有 {{ undoConflicts.length }} 项没有撤回（同步后被改过）</template>
            <div style="font-size:12px;">下面这些项在你同步之后被改动过，系统没有覆盖它们，改动保留。</div>
          </el-alert>
          <el-table :data="undoConflictsShown" size="small" border style="margin-top:8px;">
            <el-table-column label="账户ID" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">{{ hdUndoItemLabel(row) }}</template>
            </el-table-column>
            <el-table-column prop="reason" label="原因" min-width="160" />
          </el-table>
          <div v-if="undoConflicts.length > 20" style="margin-top:6px;font-size:12px;color:#6b7280;">
            …另有 {{ undoConflicts.length - 20 }} 项
          </div>
        </div>

        <!-- 保留：新建的账户被同步之后改过，保留不删 -->
        <div v-if="undoKept.length" style="margin-top:14px;">
          <el-alert type="warning" show-icon :closable="false">
            <template #title>有 {{ undoKept.length }} 个新建账户没有删除（同步后被改过）</template>
            <div style="font-size:12px;">这些账户是你那次同步新建的，之后被人改过，系统保留它们、没有删除。</div>
          </el-alert>
          <el-table :data="undoKeptShown" size="small" border style="margin-top:8px;">
            <el-table-column label="账户ID" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">{{ hdUndoItemLabel(row) }}</template>
            </el-table-column>
            <el-table-column prop="reason" label="原因" min-width="160" />
          </el-table>
          <div v-if="undoKept.length > 20" style="margin-top:6px;font-size:12px;color:#6b7280;">
            …另有 {{ undoKept.length - 20 }} 个
          </div>
        </div>

        <!-- 表里找不到的行 -->
        <div v-if="undoNotFound.length" style="margin-top:14px;">
          <el-alert type="warning" show-icon :closable="false">
            <template #title>有 {{ undoNotFound.length }} 个账户不在你的表里</template>
            <div style="font-size:12px;">这些账户在表里的行已经不在了，本次没能还原它们。</div>
          </el-alert>
          <el-table :data="undoNotFoundShown" size="small" border style="margin-top:8px;">
            <el-table-column label="账户ID" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">{{ hdUndoItemLabel(row) }}</template>
            </el-table-column>
          </el-table>
          <div v-if="undoNotFound.length > 20" style="margin-top:6px;font-size:12px;color:#6b7280;">
            …另有 {{ undoNotFound.length - 20 }} 个
          </div>
        </div>
      </template>
    </div>

    <template #footer>
      <div style="margin-left:auto;">
        <el-button type="primary" @click="undoDlg.visible = false">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed, nextTick, onMounted, onActivated, onDeactivated, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { huguanApi } from '@/api/huguan'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api/client'
import { sheetWriteApi } from '@/api/sheetWrite'
import { sheetWriteTone, sheetWriteHint } from '@/utils/sheetWriteUi'

const authStore = useAuthStore()

// ===========================================================================
// 户管看板配置（子项目 B）
//
// 视觉设计：docs/superpowers/specs/2026-09-24-huguan-frontend-visual-design.md
//   卡片 §2 / 「刷新到看板」二次确认 §3 / 差异报告对话框 §4 / 标签映射 §4.9
// 平台差异只有三处：platform、读 res.config[platform]、中文列名按该平台的
// COLUMN_SPEC 走（GG：运营 / 重新分配；TT：接户运营 / 换绑情况 / BC / 消耗…；
// FB：在用运营 / 接户运营 / 资产UID / 入库 / 出库…）。
// ===========================================================================
const props = defineProps({
  platform: { type: String, required: true, validator: v => ['gg', 'tt', 'fb'].includes(v) },
})

// 平台标识：本组件由 GG / TT / FB 三个设置页共用。传入的 platform 是静态字面量
// （每个页面各挂一次，不会中途变化），因此按普通常量使用即可。
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

// 撤回（子项目 ③，spec §八）：hdUndo 是「两个方向各有没有可撤的快照」，
// 平铺取自 GET /huguan/dashboard/undo 的 res.push / res.sync（各为 {count, created_at} 或 null）。
// 撤回成功后这两个值会作废，必须重新拉一次，否则按钮状态停在旧值。
const hdUndo = ref({ push: null, sync: null })
const hdUndoing = ref(null)            // 'push' | 'sync' | null，用于按钮 loading
const undoDlg = reactive({ visible: false, direction: 'push', result: null, error: '' })
const clearingExpanded = ref(false)

const syncDiff = ref(null)
const syncResult = ref(null)
const selOwner = ref([])
const selCreate = ref([])
const selUpdate = ref([])

const hdBusy = computed(() =>
  hdReading.value || hdSaving.value || hdPushing.value || hdSyncing.value
  || !!hdUndoing.value || syncDlg.applying)
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
  // FB 没有通道列，变更来源恒为「在用运营」列
  fb: { owner_name: '在用运营' },
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
  fb: {
    acquired_date: '日期', name: '账户名称',
    channel_id: '所属渠道', asset_type_id: '资产类型',
    unit_price: '单价', inbound_qty: '入库',
    outbound_date: '出库时间', outbound_qty: '出库',
    timezone: '时区', consumption: '消耗', remark: '产品信息',
    status_id: '状态', _primary_bm_name: '位置',
    _is_dead: '死亡',
  },
}
// 后端 warnings[].message 会夹带英文字段名，展示前替换（纯展示层）。
// 按平台分区：FB 用的是 channel_name / asset_type_name，不是 agent_name / bc_name，
// 共用一份映射会漏替换 FB 的词。GG / TT 的四个词逐字不变。
const WARN_TOKENS = {
  gg: { agent_name: '所属渠道', bc_name: 'BC', mcc_name: '所属 MCC', status_name: '状态' },
  tt: { agent_name: '所属渠道', bc_name: 'BC', mcc_name: '所属 MCC', status_name: '状态' },
  fb: { channel_name: '所属渠道', asset_type_name: '资产类型', status_name: '状态' },
}
const CATEGORY_LABELS = { create: '新增', update: '字段更新', owner: '归属变更' }
const OWNER_WRITEBACK_TEXT = {
  gg: '表里「运营」列已改写成新归属名，「重新分配」列已清空。下次同步不会重复应用这些变更。',
  tt: '表里「接户运营」列已改写成新归属名，「换绑情况」列已清空。下次同步不会重复应用这些变更。',
  fb: '表里「在用运营」列已改写成新归属名，「接户运营」列已记下本次换绑。下次同步不会重复应用这些变更。',
}

function hdViaLabel(via) { return (VIA_LABELS[HD_PLATFORM] || {})[via] ?? '—' }
function hdFieldLabel(key) { return (FIELD_LABELS[HD_PLATFORM] || {})[key] ?? key }
function hdCategoryLabel(cat) { return CATEGORY_LABELS[cat] ?? cat }
function hdWarnText(message) {
  let out = String(message ?? '')
  const tokens = WARN_TOKENS[HD_PLATFORM] || {}
  Object.keys(tokens).forEach(k => { out = out.split(k).join(tokens[k]) })
  return out
}
const hdWriteBackText = OWNER_WRITEBACK_TEXT[HD_PLATFORM]

// ---------- 撤回按钮的小字与报告项标签（spec §八） ----------
// 小字格式「上一次：10-06 14:32 · 影响 128 行」。created_at 由后端按
// datetime('now','localtime') 落成 "YYYY-MM-DD HH:MM:SS"，此处只取「月-日 时:分」。
function hdUndoText(direction) {
  const meta = hdUndo.value[direction]
  if (!meta) return ''
  const raw = String(meta.created_at || '')
  // 形状对不上就原样显示 —— 绝不静默吞掉一个时间（宁可难看也不丢信息）
  const when = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(raw) ? raw.slice(5, 16) : (raw || '未知时间')
  const unit = direction === 'push' ? '行' : '项'
  return `${when} · 影响 ${meta.count || 0} ${unit}`
}
// 报告项可能是对象（conflicts / kept：{account_id} 或状态类 {name}），
// 也可能是纯字符串（not_found：账户ID 列表）—— 两种形状都要能显示。
function hdUndoItemLabel(row) {
  if (row === null || row === undefined) return '—'
  if (typeof row !== 'object') return String(row)
  return row.account_id || row.name || '—'
}

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
  fb: [
    { col: 'C 列',  head: '账户名称', to: '系统里的「账户名称」' },
    { col: 'E 列',  head: '所属渠道', to: '系统里的「所属渠道」' },
    { col: 'F 列',  head: '资产类型', to: '系统里的「资产类型」' },
    { col: 'G 列',  head: '单价',     to: '系统里的「单价」' },
    { col: 'H 列',  head: '入库',     to: '系统里的「入库」' },
    { col: 'J 列',  head: '在用运营', to: '系统里的「归属人」' },
    { col: 'K 列',  head: '出库时间', to: '系统里的「出库时间」' },
    { col: 'L 列',  head: '出库',     to: '系统里的「出库」' },
    { col: 'M 列',  head: '时区',     to: '系统里的「时区」' },
    { col: 'N 列',  head: '消耗',     to: '系统里的「消耗」' },
    { col: 'O 列',  head: '状态',     to: '系统里的「状态」' },
    { col: 'P 列',  head: '位置',     to: '该账户的主 BM' },
    { col: 'Q 列',  head: '产品信息', to: '系统里的「备注」' },
  ],
}
const PUSH_SAFE = {
  gg: ['E 列 · 国家', 'H 列 · 重新分配', 'L 列 · 位置', 'M 列 · 消耗', 'N 列 · 产品信息'],
  tt: ['K 列 · 位置', 'L 列 · 换绑情况'],
  fb: ['B 列 · 操作人', 'D 列 · 资产UID', 'I 列 · 接户运营'],
}
const PUSH_SAFE_NOTE = {
  gg: '其中「重新分配」列是你在表里填归属变更的通道，系统永远不碰它。',
  tt: '其中「换绑情况」列是你在表里填归属变更的通道，系统永远不碰它。',
  fb: '其中「接户运营」列是系统记的换绑流水，系统只在归属变更时写它，其余时候不碰。',
}
const PUSH_EXTRA_NOTE = {
  gg: '另外系统还会按自己的数据重写：A 列 · 日期、B 列 · 是否封户、C 列 · 账户ID。表里有、系统里没有的账户不会被写入，只会在结果里报一个数。',
  tt: '另外系统还会按自己的数据重写：A 列 · 入库时间、B 列 · 是否回收、C 列 · 账户ID。表里有、系统里没有的账户不会被写入，只会在结果里报一个数。',
  fb: '另外系统还会按自己的数据重写：A 列 · 日期。表里有、系统里没有的账户不会被写入，只会在结果里报一个数。',
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

// ---------- 撤回结果的派生数据（与差异报告同一渲染口径） ----------
// 结果体按方向形状不同：push {updated, not_found}；sync {reverted, conflicts, kept, not_found}。
// 报告必须能列出冲突项与未命中项 —— 不能只弹一个「成功 N 项」（spec §八）。
const undoResult = computed(() => undoDlg.result || {})
const undoConflicts = computed(() => undoResult.value.conflicts || [])
const undoKept = computed(() => undoResult.value.kept || [])
const undoNotFound = computed(() => undoResult.value.not_found || [])
const undoConflictsShown = computed(() => undoConflicts.value.slice(0, 20))
const undoKeptShown = computed(() => undoKept.value.slice(0, 20))
const undoNotFoundShown = computed(() => undoNotFound.value.slice(0, 20))
const undoDoneText = computed(() => {
  const r = undoResult.value
  return undoDlg.direction === 'push'
    ? `已撤回上一次刷新：还原 ${r.updated || 0} 行。`
    : `已撤回上一次同步：还原 ${r.reverted || 0} 项。`
})
const undoTitle = computed(() => (undoDlg.direction === 'push'
  ? '撤回上次 · 刷新到看板'
  : '撤回上次 · 从表同步到系统'))

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

async function loadHdUndo() {
  if (!authStore.isHuguan) return
  try {
    const res = await huguanApi.getUndo(HD_PLATFORM)
    // 平铺：res.push / res.sync（不是 res.undo.push）
    hdUndo.value = { push: res.push || null, sync: res.sync || null }
  } catch {
    // 快照状态只是「撤回按钮亮不亮」的信息，拉不到就当没有（按钮禁用），
    // 不打断用户 —— 刷新/同步主流程照常可用。
    hdUndo.value = { push: null, sync: null }
  }
}

async function askUndo(direction) {
  const label = direction === 'push' ? '刷新到看板' : '从表同步到系统'
  try {
    await ElMessageBox.confirm(
      `确定撤回上一次「${label}」吗？这与那次同步相反：系统会把当时写下的值还原成之前的样子。`,
      '确认撤回',
      { type: 'warning', confirmButtonText: '确认撤回', cancelButtonText: '取消',
        distinguishCancelAndClose: true },
    )
  } catch {
    // 用户取消或关闭二次确认（ElMessageBox reject 的是 'cancel'/'close'，
    // 不是操作失败）—— 什么都不做。
    return
  }

  hdUndoing.value = direction
  try {
    const res = await huguanApi.doUndo(HD_PLATFORM, direction)
    undoDlg.direction = direction
    undoDlg.result = res
    undoDlg.error = ''
    undoDlg.visible = true
    // 快照已被本次撤回作废 ⇒ 必须重新拉一次，否则按钮状态停在旧值。
    await loadHdUndo()
  } catch (e) {
    undoDlg.direction = direction
    undoDlg.result = null
    undoDlg.error = e?.response?.data?.error || '撤回失败'
    undoDlg.visible = true
  } finally {
    hdUndoing.value = null
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
    // push 走的就是点位 #1 的 writeback_rows 链路（写表是异步的）：
    // 成功分支刷一次 + 起有界轮询，失败路径不跟（见 onUnmounted 注释同理）。
    loadHdSwFailures()
    startHdSwPoll()
  } catch (e) {
    // 单次 values().batchUpdate 是原子的：要么全成、要么全不成，不存在「写了一半」。
    // 因此失败即整批未写入，直接重试是安全的，无需打开表格核对。
    setHdHint('刷新到看板失败。本次没有写入任何数据，直接重试是安全的。', 'error')
  } finally {
    hdPushing.value = false
    // 这次刷新留下了新快照（写失败/空写时后端作废，拉回来就是 null）⇒
    // 重新拉一次，「撤回上次」按钮才会随本次操作亮起。
    loadHdUndo()
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
    // 打勾落库会触发 #2/#3/#4（含归属变更通道列）：同样刷一次 + 起有界轮询。
    loadHdSwFailures()
    startHdSwPoll()
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
    // 这次同步留下了新快照 ⇒ 重新拉一次，「撤回上次」按钮随之亮起。
    loadHdUndo()
  }
}

// ===========================================================================
// 写表失败治理（三期：户管看板域）
//
// 规格 §5：户管是本期 4 个 target 里 3 个的**表主人**（sheet_write_log.user_id 记的
// 就是表主人）。原先写表失败只落服务端日志 —— 户管在自己的卡片里看不到、也无法重试。
// 这里是本期唯一的新增 UI。
// ===========================================================================
const HD_SW_POLL_MS = 3000
const HD_SW_POLL_MAX = 15               // ~45s，覆盖 30s 重试窗口

// 本看板下、**属于户管自己**的 target。不含 operator_dashboard_remark ——
// 那是投手看板（表主人是投手），已在 TT 账户表行上标记，不在这里汇总。
//
// fb 没有「归属变更通道列」（OWNER_CHANNEL_COL['fb'] is None），但建号/编辑/换绑
// 会写 huguan_fb_acceptor；而 FB 账户表面板只过滤 huguan_dashboard（T5 核实），
// 那类失败在行上**没有任何标记** —— 汇总在这里，它的表主人（户管）才有地方看到、重试。
const HD_SW_TARGETS = HD_PLATFORM === 'fb'
  ? ['huguan_dashboard', 'huguan_fb_acceptor']
  : ['huguan_dashboard', 'huguan_owner_channel']

const hdSwFailures = ref([])            // [{target, business_key, status, error_msg, updated_at}]
let hdSwTimer = null

/** 拉失败汇总。按 target **分别**拉（三期新加的 /status target 参数）—— 不带 target
 *  会把别的 target 的行也混进来（同一 account_id 跨 target 是正常现象）。静默失败。 */
async function loadHdSwFailures() {
  if (!authStore.isHuguan) return
  try {
    const res = await Promise.all(HD_SW_TARGETS.map(t =>
      sheetWriteApi.status({ platform: HD_PLATFORM, target: t })))
    const items = res.flatMap(r => r.items || [])
    // 两次请求各按 updated_at DESC 回来，合并后要重排，否则列表顺序会随
    // Promise 完成顺序漂移 —— 用户点重试时行会跳。
    items.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
    hdSwFailures.value = items
  } catch { /* 汇总拉不到不该打扰用户，保持上一次的结果 */ }
}

/** 停掉轮询。离开页面 / 组件卸载 / 起新链之前都要先清旧的。 */
function stopHdSwPoll() {
  if (hdSwTimer) { clearTimeout(hdSwTimer); hdSwTimer = null }
}

/** 写表是异步的：push / 打勾落库 / 重试 之后都要在 30s 重试窗口内跟一段时间。
 *  有界（HD_SW_POLL_MAX 次）自终止，与二期 TT / FB 面板同形。 */
function startHdSwPoll() {
  stopHdSwPoll()
  let attempts = 0
  const tick = async () => {
    if (attempts >= HD_SW_POLL_MAX) { hdSwTimer = null; return }
    attempts++
    await loadHdSwFailures()
    hdSwTimer = setTimeout(tick, HD_SW_POLL_MS)
  }
  hdSwTimer = setTimeout(tick, HD_SW_POLL_MS)
}

/** 重试一条。retry 只回「已受理」，结果要轮询才知道 —— 所以刷一次 + 起轮询。 */
async function retryHdSw(f) {
  try {
    await sheetWriteApi.retry({ platform: HD_PLATFORM, target: f.target,
                                businessKey: f.business_key })
    ElMessage.success('已重新提交，请稍后查看结果')
    await loadHdSwFailures()
    startHdSwPoll()
  } catch (e) {
    ElMessage.error(e.response?.data?.error || '重试失败')
  }
}

onMounted(() => {
  // 并行拉一次：配置与「有没有可撤的快照」互不依赖。
  loadHdConfig()
  loadHdUndo()
})

// keep-alive（App.vue:8-12，GG/TT 设置页自身还各套了一层 —— AccountsView.vue:14-18 /
// TtView.vue:13-17，FB 的 /fb/settings 是顶层路由、被 App 那层缓存）只 deactivate、
// 不 unmount ⇒ onMounted 只在首次进入时跑一次。触发本卡片写表的动作（改状态 / 换绑 /
// 编辑账户）全发生在**别的面板**，所以「回到设置页」必须自己重拉一次，否则汇总区永远
// 停在首次进入时的空快照上 —— 计划 Step 4 人工清单第 1 条就会失败。
//
// 首次挂载后 onActivated 也会触发，故不要与 onMounted 并存（会重复请求两次）。
onActivated(() => {
  loadHdSwFailures()
  // 也在途的写表（刚在账户面板触发的）会在 30s 重试窗口内收敛，跟一段才有结果。
  startHdSwPoll()
})
// 离开页面就停轮询，别在别的页面继续打请求。
onDeactivated(stopHdSwPoll)
// 兜底：组件被真正销毁时（onDeactivated 不覆盖这条路径）也要停。
onUnmounted(stopHdSwPoll)
</script>
