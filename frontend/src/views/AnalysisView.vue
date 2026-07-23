<template>
  <div style="display:flex;flex-direction:column;height:calc(100vh - 72px);">
    <h1 style="flex-shrink:0;">📊 数据分析</h1>

    <!-- 筛选栏 -->
    <div style="flex-shrink:0;display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;align-items:center;">
      <el-select v-model="filterProduct" placeholder="全部产品" clearable style="width:200px;" filterable multiple collapse-tags @change="onGlobalProductChange">
        <el-option v-for="p in filterProducts" :key="p.name" :label="p.label" :value="p.name" />
      </el-select>
      <el-select v-model="filterRegion" placeholder="全部地区" clearable style="width:140px;" @change="refreshAll">
        <el-option v-for="r in filterRegions" :key="r" :label="r" :value="r" />
      </el-select>
      <el-date-picker v-model="filterDateRange" type="daterange" range-separator="~" start-placeholder="开始" end-placeholder="结束"
        value-format="YYYY-MM-DD" style="width:260px;" @change="refreshAll" popper-class="analysis-date-picker" :cell-class-name="dateCellClass" />
      <el-button @click="refreshAll">🔄 刷新</el-button>
    </div>

    <!-- Tab 页 -->
    <div style="flex:1;min-height:0;overflow-y:auto;">
      <el-tabs v-model="activeTab" type="border-card">
        <!-- 仪表盘 -->
        <el-tab-pane label="📊 仪表盘" name="dashboard">
          <div v-if="dashboardData" style="padding:8px;">
            <div style="display:flex;gap:16px;align-items:flex-start;">
              <div style="flex:1;">
                <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">
                  <div class="stat-card"><div class="stat-val">${{ (dashboardData.summary.total_cost || 0).toLocaleString() }}</div><div class="stat-label">总花费</div></div>
                  <div class="stat-card"><div class="stat-val">{{ (dashboardData.summary.total_impressions || 0).toLocaleString() }}</div><div class="stat-label">总展示</div></div>
                  <div class="stat-card"><div class="stat-val">{{ (dashboardData.summary.total_installs || 0).toLocaleString() }}</div><div class="stat-label">总安装</div></div>
                  <div class="stat-card"><div class="stat-val">{{ (dashboardData.summary.total_in_app || 0).toLocaleString() }}</div><div class="stat-label">应用内操作</div></div>
                  <div class="stat-card">
                    <div class="stat-val">${{ dashboardData.summary.avg_cpi || 0 }}</div>
                    <div class="stat-label">
                      每次操作费用
                      <span v-if="dashboardData.summary.product_kpi != null" :style="{color: dashboardData.summary.kpi_met ? '#16a34a' : '#dc2626'}">
                        / KPI ${{ dashboardData.summary.product_kpi }}
                        {{ dashboardData.summary.kpi_met ? '✓' : '✗' }}
                      </span>
                    </div>
                  </div>
                  <div class="stat-card"><div class="stat-val">{{ ((dashboardData.summary.avg_ctr || 0) * 100).toFixed(2) }}%</div><div class="stat-label">CTR</div></div>
                  <div class="stat-card"><div class="stat-val">{{ ((dashboardData.summary.avg_cvr || 0) * 100).toFixed(2) }}%</div><div class="stat-label">CVR</div></div>
                </div>
              </div>
              <div style="width:200px;flex-shrink:0;background:#f5f7fa;border-radius:8px;padding:12px;font-size:12px;line-height:1.8;">
                <div style="font-weight:600;margin-bottom:4px;color:#303133;">📖 指标说明</div>
                <div><b>CPI</b> — Cost Per In-app Action，每次应用内操作费用（花费 ÷ 应用内操作数）</div>
                <div><b>CTR</b> — Click Through Rate，点击率（点击 ÷ 展示 × 100%）</div>
                <div><b>CVR</b> — Conversion Rate，安装转化率（安装 ÷ 点击 × 100%）</div>
                <div><b>KPI</b> — 产品目标 CPI，实际 ≤ KPI 为消耗合格 ✓</div>
              </div>
            </div>

            <div v-if="dashboardData.period_compare && Object.keys(dashboardData.period_compare).length" style="margin-bottom:12px;font-size:13px;color:#666;">
              环比变化：
              <span v-if="dashboardData.period_compare.cost_change_pct !== undefined" :style="{color: dashboardData.period_compare.cost_change_pct > 0 ? '#dc2626' : '#16a34a'}">
                花费 {{ dashboardData.period_compare.cost_change_pct > 0 ? '↑' : '↓' }}{{ Math.abs(dashboardData.period_compare.cost_change_pct) }}%
              </span>
              <span v-if="dashboardData.period_compare.installs_change_pct !== undefined" :style="{color: dashboardData.period_compare.installs_change_pct > 0 ? '#16a34a' : '#dc2626'}" style="margin-left:12px;">
                安装 {{ dashboardData.period_compare.installs_change_pct > 0 ? '↑' : '↓' }}{{ Math.abs(dashboardData.period_compare.installs_change_pct) }}%
              </span>
            </div>

            <div v-if="dashboardData.anomalies?.length" style="margin-bottom:12px;">
              <div style="font-weight:600;color:#dc2626;margin-bottom:6px;">⚠️ 异常提醒</div>
              <div v-for="(a, i) in dashboardData.anomalies" :key="i" style="font-size:13px;color:#666;margin-bottom:2px;">
                · {{ a.date }} {{ a.campaign }}：{{ a.detail }}
              </div>
            </div>

            <!-- 按 campaign 分组明细 -->
            <div v-if="dashboardData.campaigns?.length" style="margin-top:16px;">
              <div style="font-weight:600;margin-bottom:8px;">📦 按包/系列分组</div>
              <el-table :data="dashboardData.campaigns" size="small" border stripe max-height="300">
                <el-table-column prop="campaign" label="包名" min-width="150" />
                <el-table-column prop="total_cost" label="花费" min-width="90" sortable>
                  <template #default="{row}">${{ (row.total_cost || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="total_installs" label="安装" min-width="75" sortable>
                  <template #default="{row}">{{ (row.total_installs || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="avg_cpi" label="CPI" min-width="80" sortable>
                  <template #default="{row}">${{ (row.avg_cpi || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="total_in_app" label="应用内操作" min-width="90" sortable>
                  <template #default="{row}">{{ (row.total_in_app || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="total_impressions" label="展示" min-width="85" sortable>
                  <template #default="{row}">{{ (row.total_impressions || 0).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column prop="total_clicks" label="点击" min-width="75" sortable>
                  <template #default="{row}">{{ (row.total_clicks || 0).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column prop="ctr" label="CTR" min-width="75" sortable>
                  <template #default="{row}">{{ ((row.ctr || 0) * 100).toFixed(2) }}%</template>
                </el-table-column>
                <el-table-column prop="cvr" label="CVR" min-width="75" sortable>
                  <template #default="{row}">{{ ((row.cvr || 0) * 100).toFixed(2) }}%</template>
                </el-table-column>
              </el-table>
            </div>

            <div v-if="dashboardData.asset_count !== undefined" style="font-size:13px;color:#666;margin-top:8px;">
              🎬 成效素材关联：{{ dashboardData.asset_count }} 个
            </div>
          </div>
          <el-empty v-else description="暂无数据，请先保存做表数据" />
        </el-tab-pane>

        <!-- 趋势 -->
        <el-tab-pane label="📈 趋势" name="trends">
          <div style="margin-bottom:8px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
            <el-select v-model="trendProducts" placeholder="选择产品（可多选）" style="width:300px;" multiple clearable filterable collapse-tags @change="loadTrends">
              <el-option v-for="p in trendProductOptions" :key="p" :label="p" :value="p" />
            </el-select>
            <span>指标：<el-radio-group v-model="trendMetric" size="small" @change="loadTrends">
              <el-radio-button value="cpi">CPI</el-radio-button>
              <el-radio-button value="cost">花费</el-radio-button>
              <el-radio-button value="installs">安装</el-radio-button>
              <el-radio-button value="ctr">CTR</el-radio-button>
            </el-radio-group></span>
            <span>分组：<el-radio-group v-model="trendGroupBy" size="small" @change="loadTrends">
              <el-radio-button value="campaign">按包</el-radio-button>
              <el-radio-button value="product_name">按产品</el-radio-button>
            </el-radio-group></span>
            <span v-if="trendLoading" style="font-size:12px;color:#909399;">加载中...</span>
          </div>
          <div v-if="trendSeries.length" ref="trendChart" style="width:100%;height:340px;"></div>
          <div v-if="trendSeries.length" style="display:flex;gap:6px 16px;flex-wrap:wrap;padding:8px 0 0 60px;">
            <span v-for="s in trendSeries" :key="s.name" style="display:flex;align-items:center;gap:4px;font-size:11px;color:#666;cursor:pointer;"
              @click="toggleTrendSeries(s.name)"
              :style="{ opacity: trendHidden[s.name] ? 0.4 : 1 }">
              <span style="width:8px;height:8px;border-radius:50%;display:inline-block;" :style="{ background: trendColor(s.name) }"></span>
              {{ s.name }}
            </span>
          </div>
          <el-empty v-else description="暂无趋势数据" />
        </el-tab-pane>

        <!-- 对比 -->
        <el-tab-pane label="📋 对比" name="compare">
          <div v-if="compareItems.length" style="padding:8px;">
            <div style="display:flex;gap:16px;align-items:flex-start;">
              <div style="flex:1;">
                <div style="margin-bottom:10px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
                  <span style="font-weight:600;">分组：</span>
                  <el-radio-group v-model="compareGroupBy" size="small" @change="loadCompare">
                    <el-radio-button value="product_name">按产品</el-radio-button>
                    <el-radio-button value="campaign">按系列</el-radio-button>
                  </el-radio-group>
                  <span style="font-size:13px;color:#909399;">共 {{ compareItems.length }} 个分组</span>
                </div>

                <!-- 每个对比组的统计卡片 -->
                <div v-for="item in compareItems" :key="item.name" style="margin-bottom:16px;border:1px solid #e5e7eb;border-radius:8px;padding:12px;">
                  <div style="font-weight:600;margin-bottom:8px;color:#303133;">📦 {{ item.name }}</div>
                  <div style="display:flex;gap:8px;flex-wrap:wrap;">
                    <div class="stat-card" style="min-width:100px;padding:10px 14px;">
                      <div class="stat-val" style="font-size:18px;">${{ (item.total_cost || 0).toLocaleString() }}</div>
                      <div class="stat-label">花费</div>
                    </div>
                    <div class="stat-card" style="min-width:100px;padding:10px 14px;">
                      <div class="stat-val" style="font-size:18px;">{{ (item.total_impressions || 0).toLocaleString() }}</div>
                      <div class="stat-label">展示</div>
                    </div>
                    <div class="stat-card" style="min-width:100px;padding:10px 14px;">
                      <div class="stat-val" style="font-size:18px;">{{ (item.total_installs || 0).toLocaleString() }}</div>
                      <div class="stat-label">安装</div>
                    </div>
                    <div class="stat-card" style="min-width:100px;padding:10px 14px;">
                      <div class="stat-val" style="font-size:18px;">{{ (item.total_in_app || 0).toLocaleString() }}</div>
                      <div class="stat-label">应用内操作</div>
                    </div>
                    <div class="stat-card" style="min-width:100px;padding:10px 14px;">
                      <div class="stat-val" style="font-size:18px;">${{ (item.avg_cpi || 0).toFixed(2) }}</div>
                      <div class="stat-label">CPI</div>
                    </div>
                    <div class="stat-card" style="min-width:100px;padding:10px 14px;">
                      <div class="stat-val" style="font-size:18px;">{{ ((item.ctr || 0) * 100).toFixed(2) }}%</div>
                      <div class="stat-label">CTR</div>
                    </div>
                    <div class="stat-card" style="min-width:100px;padding:10px 14px;">
                      <div class="stat-val" style="font-size:18px;">{{ ((item.cvr || 0) * 100).toFixed(2) }}%</div>
                      <div class="stat-label">CVR</div>
                    </div>
                  </div>
                </div>
              </div>
              <div style="width:200px;flex-shrink:0;background:#f5f7fa;border-radius:8px;padding:12px;font-size:12px;line-height:1.8;">
                <div style="font-weight:600;margin-bottom:4px;color:#303133;">📖 指标说明</div>
                <div><b>CPI</b> — 每次应用内操作费用</div>
                <div><b>CTR</b> — 点击率（点击 ÷ 展示）</div>
                <div><b>CVR</b> — 安装转化率（安装 ÷ 点击）</div>
              </div>
            </div>

            <!-- 对比明细表格 -->
            <div style="margin-top:16px;">
              <div style="font-weight:600;margin-bottom:8px;">📋 明细对比</div>
              <el-table :data="compareItems" size="small" border stripe max-height="400">
                <el-table-column prop="name" label="名称" min-width="140" />
                <el-table-column prop="total_cost" label="花费" min-width="90" sortable>
                  <template #default="{row}">${{ (row.total_cost || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="total_installs" label="安装" min-width="75" sortable>
                  <template #default="{row}">{{ (row.total_installs || 0).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column prop="avg_cpi" label="CPI" min-width="80" sortable>
                  <template #default="{row}">${{ (row.avg_cpi || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="total_in_app" label="应用内操作" min-width="90" sortable>
                  <template #default="{row}">{{ (row.total_in_app || 0).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column prop="total_impressions" label="展示" min-width="85" sortable>
                  <template #default="{row}">{{ (row.total_impressions || 0).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column prop="total_clicks" label="点击" min-width="75" sortable>
                  <template #default="{row}">{{ (row.total_clicks || 0).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column prop="ctr" label="CTR" min-width="75" sortable>
                  <template #default="{row}">{{ ((row.ctr || 0) * 100).toFixed(2) }}%</template>
                </el-table-column>
                <el-table-column prop="cvr" label="CVR" min-width="75" sortable>
                  <template #default="{row}">{{ ((row.cvr || 0) * 100).toFixed(2) }}%</template>
                </el-table-column>
              </el-table>
            </div>
          </div>
          <el-empty v-else description="暂无对比数据，请先保存做表数据" />
        </el-tab-pane>

        <!-- 多维分析 -->
        <el-tab-pane label="🔬 多维分析" name="multi">
          <div style="padding:8px;">
            <!-- 维度配置栏 -->
            <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px;">
              <span style="font-weight:600;">X轴：</span>
              <el-select v-model="multiXAxis" style="width:110px;" size="small" @change="loadMultiAnalysis">
                <el-option v-for="m in multiMetrics" :key="m.value" :label="m.label" :value="m.value" />
              </el-select>
              <span style="font-weight:600;">Y轴：</span>
              <el-select v-model="multiYAxis" style="width:110px;" size="small" @change="loadMultiAnalysis">
                <el-option v-for="m in multiMetrics" :key="m.value" :label="m.label" :value="m.value" />
              </el-select>
              <span style="font-weight:600;">气泡：</span>
              <el-select v-model="multiSizeBy" style="width:110px;" size="small" clearable placeholder="无" @change="loadMultiAnalysis">
                <el-option v-for="m in multiMetrics" :key="m.value" :label="m.label" :value="m.value" />
              </el-select>
              <span style="font-weight:600;">分组：</span>
              <el-select v-model="multiGroupBy" style="width:120px;" size="small" @change="loadMultiAnalysis">
                <el-option label="账户" value="account" />
                <el-option label="客户ID" value="customer_id" />
                <el-option label="产品" value="product_name" />
                <el-option label="包/系列" value="campaign" />
              </el-select>
              <el-select v-model="multiFilterProduct" style="width:180px;" size="small" clearable placeholder="全部产品" filterable multiple collapse-tags @change="onMultiProductChange">
                <el-option v-for="p in multiProductOptions" :key="p" :label="p" :value="p" />
              </el-select>
              <el-select v-model="multiFilterCampaign" style="width:150px;" size="small" clearable placeholder="包名筛选" filterable @change="onMultiCampaignChange">
                <el-option v-for="c in multiCampaignOptions" :key="c" :label="c" :value="c" />
              </el-select>
              <el-select v-model="multiFilterAccount" style="width:150px;" size="small" clearable placeholder="账户筛选" filterable @change="loadMultiAnalysis">
                <el-option v-for="a in multiAccountOptions" :key="a" :label="a" :value="a" />
              </el-select>
              <el-checkbox v-model="multiSplitDate" size="small" @change="loadMultiAnalysis">按天拆分</el-checkbox>
              <el-button size="small" @click="loadMultiAnalysis">🔄 刷新</el-button>
            </div>

            <!-- 粘贴实时数据 -->
            <div style="margin-bottom:8px;">
              <el-button size="small" text @click="multiShowPaste=!multiShowPaste">📋 粘贴实时数据 {{ multiShowPaste ? '▲' : '▼' }}</el-button>
            </div>
            <div v-if="multiShowPaste" style="background:#fafafa;border:1px dashed #dcdfe6;border-radius:8px;padding:12px;margin-bottom:12px;">
              <el-input v-model="multiPasteRaw" type="textarea" :rows="5" placeholder="粘贴 Google Ads 原始数据（竖排格式）..." style="margin-bottom:8px;" />
              <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
                <el-checkbox v-model="multiPasteCampaignId" size="small">含广告系列ID（11列）</el-checkbox>
                <el-button size="small" @click="parsePastedData" :loading="multiParseLoading">🔍 解析数据</el-button>
                <span v-if="multiParsedRows.length" style="font-size:13px;color:#059669;">
                  解析成功：{{ multiParsedRows.length }} 条数据
                </span>
                <span v-if="multiParseError" style="font-size:13px;color:#dc2626;">{{ multiParseError }}</span>
              </div>
              <div v-if="multiParsedRows.length" style="margin-top:8px;display:flex;gap:8px;align-items:center;">
                <el-switch v-model="multiCompareOn" size="small" @change="onCompareToggle" />
                <span style="font-size:13px;">加入对比（蓝色=历史，红色=新增）</span>
              </div>
            </div>

            <!-- 散点图 -->
            <div v-if="multiHistPoints.length || multiNewPoints.length || multiPoints.length" ref="multiChart" style="width:100%;height:400px;margin-bottom:12px;"></div>
            <el-empty v-else-if="multiLoaded" description="暂无数据" :image-size="60" />

            <!-- 分析结论 -->
            <div v-if="multiInsights.length || multiAiMessages.length" style="margin-bottom:12px;">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                <span style="font-weight:600;">📊 分析结论</span>
                <el-button v-if="aiEnabled && multiPoints.length" size="small" type="primary" text @click="autoAiAnalysis" :loading="multiAiLoading">🤖 AI 解读</el-button>
              </div>
              <div style="background:#f5f7fa;border-radius:8px;padding:12px;font-size:13px;line-height:1.8;">
                <!-- AI结论 -->
                <div v-for="(msg, i) in multiAiMessages" :key="'ai'+i" style="white-space:pre-wrap;margin-bottom:4px;">
                  <span v-if="msg.role==='assistant'" style="color:#303133;">{{ msg.content }}</span>
                </div>
                <!-- 规则引擎结论（始终显示） -->
                <div v-if="multiInsights.length">
                  <div v-for="(insight, i) in multiInsights" :key="i" style="margin-bottom:2px;">· {{ insight }}</div>
                </div>
              </div>
            </div>

            <!-- AI对话区 -->
            <div v-if="aiEnabled" style="margin-bottom:12px;">
              <div style="font-weight:600;margin-bottom:4px;">💬 对话分析</div>
              <div style="background:#f5f7fa;border-radius:8px;padding:12px;min-height:300px;max-height:500px;overflow-y:auto;margin-bottom:8px;">
                <div v-if="!multiChatHistory.length" style="color:#999;text-align:center;padding-top:60px;">
                  输入问题深入分析，如"哪些账户需要优化？"
                </div>
                <div v-for="(msg, i) in multiChatHistory" :key="'chat'+i" style="margin-bottom:8px;">
                  <div v-if="msg.role==='user'" style="text-align:right;">
                    <span style="background:#409eff;color:#fff;padding:6px 12px;border-radius:12px;display:inline-block;max-width:80%;font-size:13px;">{{ msg.content }}</span>
                  </div>
                  <div v-else style="text-align:left;">
                    <span style="background:#fff;padding:8px 14px;border-radius:12px;display:inline-block;max-width:90%;font-size:13px;white-space:pre-wrap;border:1px solid #e5e7eb;">{{ msg.content }}</span>
                  </div>
                </div>
                <div v-if="multiChatLoading" style="color:#999;font-size:13px;">分析中...</div>
              </div>
              <div style="display:flex;gap:8px;">
                <el-input v-model="multiChatQuestion" placeholder="输入分析问题..." @keyup.enter="sendMultiChat" />
                <el-button type="primary" size="small" @click="sendMultiChat" :loading="multiChatLoading">发送</el-button>
              </div>
            </div>

            <!-- 数据明细表 -->
            <div v-if="multiPoints.length">
              <div style="font-weight:600;margin-bottom:6px;cursor:pointer;" @click="multiTableVisible=!multiTableVisible">
                📋 数据明细 {{ multiTableVisible ? '▲' : '▼' }}
              </div>
              <el-table v-show="multiTableVisible" :data="multiTableData" size="small" border stripe max-height="300">
                <el-table-column prop="name" label="名称" min-width="140" />
                <el-table-column prop="total_cost" label="花费" min-width="90" sortable>
                  <template #default="{row}">${{ (row.total_cost || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="total_installs" label="安装" min-width="75" sortable>
                  <template #default="{row}">{{ (row.total_installs || 0).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column prop="avg_cpi" label="CPI" min-width="80" sortable>
                  <template #default="{row}">${{ (row.avg_cpi || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="ctr" label="CTR" min-width="75" sortable>
                  <template #default="{row}">{{ ((row.ctr || 0) * 100).toFixed(2) }}%</template>
                </el-table-column>
                <el-table-column prop="cvr" label="CVR" min-width="75" sortable>
                  <template #default="{row}">{{ ((row.cvr || 0) * 100).toFixed(2) }}%</template>
                </el-table-column>
                <el-table-column prop="total_impressions" label="展示" min-width="85" sortable>
                  <template #default="{row}">{{ (row.total_impressions || 0).toLocaleString() }}</template>
                </el-table-column>
                <el-table-column prop="total_clicks" label="点击" min-width="75" sortable>
                  <template #default="{row}">{{ (row.total_clicks || 0).toLocaleString() }}</template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </el-tab-pane>

        <!-- 跨用户 -->
        <el-tab-pane label="👥 跨用户" name="crossUser">
          <el-table :data="crossUserData" size="small" border stripe v-if="crossUserData.length">
            <el-table-column prop="display_name" label="用户" width="140">
              <template #default="{row}">{{ row.display_name || row.username || 'User#'+row.user_id }}</template>
            </el-table-column>
            <el-table-column prop="total_cost" label="花费">
              <template #default="{row}">${{ (row.total_cost || 0).toFixed(0) }}</template>
            </el-table-column>
            <el-table-column prop="total_installs" label="安装">
              <template #default="{row}">{{ (row.total_installs || 0).toLocaleString() }}</template>
            </el-table-column>
            <el-table-column prop="avg_cpi" label="CPI">
              <template #default="{row}">${{ (row.avg_cpi || 0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="report_days" label="上报天数" width="80" />
          </el-table>
          <el-empty v-else description="请先选择产品" />
        </el-tab-pane>

        <!-- AI 分析 -->
        <el-tab-pane label="🤖 AI分析" name="ai">
          <div v-if="aiEnabled === false" style="padding:20px;">
            <div style="font-weight:600;margin-bottom:12px;color:#303133;">🤖 AI 分析未启用</div>
            <p style="color:#888;margin-bottom:16px;font-size:13px;">配置 AI 服务后，可在数据分析中获得智能解读和对话分析能力。</p>
            <el-form label-width="80px" style="max-width:420px;">
              <el-form-item label="API Key">
                <el-input v-model="aiForm.api_key" type="password" show-password placeholder="火山方舟 API Key" size="small" />
              </el-form-item>
              <el-form-item label="模型">
                <el-input v-model="aiForm.model" placeholder="deepseek-v4-flash" size="small" />
              </el-form-item>
              <el-form-item label="Endpoint">
                <el-input v-model="aiForm.endpoint" placeholder="https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions" size="small" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" size="small" @click="saveAiConfig" :loading="aiSaving">💾 保存并启用</el-button>
                <span v-if="aiMsg" style="margin-left:8px;font-size:12px;color:#059669;">{{ aiMsg }}</span>
              </el-form-item>
            </el-form>
          </div>
          <div v-else-if="aiEnabled === null" style="text-align:center;padding:40px;">加载中...</div>
          <div v-else style="display:flex;flex-direction:column;height:400px;">
            <div style="display:flex;justify-content:flex-end;margin-bottom:4px;">
              <el-button size="small" text @click="showAiConfig=!showAiConfig">⚙ 配置</el-button>
            </div>
            <div v-if="showAiConfig" style="background:#f5f7fa;border-radius:8px;padding:12px;margin-bottom:8px;">
              <el-form label-width="70px" size="small" inline>
                <el-form-item label="模型">
                  <el-input v-model="aiForm.model" style="width:160px;" />
                </el-form-item>
                <el-form-item label="API Key">
                  <el-input v-model="aiForm.api_key" type="password" show-password style="width:180px;" />
                </el-form-item>
                <el-form-item label="Endpoint">
                  <el-input v-model="aiForm.endpoint" style="width:220px;" />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" size="small" @click="saveAiConfig" :loading="aiSaving">保存</el-button>
                </el-form-item>
              </el-form>
            </div>
            <div style="flex:1;min-height:0;overflow-y:auto;background:#f5f7fa;padding:12px;border-radius:8px;margin-bottom:8px;">
              <div v-if="!aiMessages.length" style="color:#999;text-align:center;padding-top:60px;">
                💬 输入问题开始 AI 分析
              </div>
              <div v-for="(msg, i) in aiMessages" :key="i" style="margin-bottom:8px;">
                <div v-if="msg.role === 'user'" style="text-align:right;">
                  <span style="background:#409eff;color:#fff;padding:6px 12px;border-radius:12px;display:inline-block;max-width:80%;font-size:13px;">{{ msg.content }}</span>
                </div>
                <div v-else style="text-align:left;">
                  <span style="background:#fff;padding:8px 14px;border-radius:12px;display:inline-block;max-width:85%;font-size:13px;white-space:pre-wrap;border:1px solid #e5e7eb;">{{ msg.content }}</span>
                </div>
              </div>
              <div v-if="aiLoading" style="text-align:left;color:#999;">分析中...</div>
            </div>
            <div style="display:flex;gap:8px;">
              <el-input v-model="aiQuestion" placeholder="输入问题，如：哪个系列 CPI 最低？" @keyup.enter="askAI" />
              <el-button type="primary" @click="askAI" :loading="aiLoading">发送</el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick, watch } from 'vue'
import { reportsApi } from '@/api/reports'
import { ElMessage } from 'element-plus'
import api from '@/api/client'
import * as echarts from 'echarts'
import { parseAdsData } from '@/utils/adsParser'

const activeTab = ref('dashboard')
const filterProduct = ref([])
const filterRegion = ref('')
const filterDateRange = ref(null)
const filterProducts = ref([])
const filterRegions = ref([])
const dateDates = ref({})  // { "YYYY-MM-DD": count }
const dateSet = computed(() => new Set(Object.keys(dateDates.value)))

function dateCellClass(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return dateSet.value.has(`${y}-${m}-${d}`) ? 'has-data' : ''
}

// 仪表盘
const dashboardData = ref(null)

// 趋势
const trendProducts = ref([])
const trendProductOptions = computed(() => {
  // 全局选了产品则趋势下拉只显示那些产品
  if (filterProduct.value.length) return filterProduct.value
  return filterProducts.value.map(p => p.name)
})
const trendMetric = ref('cpi')
const trendGroupBy = ref('campaign')
const trendSeries = ref([])
const trendLoading = ref(false)
const trendChart = ref(null)
const trendHidden = ref({})
const trendPalette = ['#5470c6','#91cc75','#fac858','#ee6666','#73c0de','#3ba272','#fc8452','#9a60b4','#ea7ccc','#48b8d0',
  '#d48265','#6e7074','#ca8622','#bda29a','#546570','#c4ccd3','#f6c7b6','#61a0a8','#d48265']

function trendColor(name) {
  const idx = trendSeries.value.findIndex(s => s.name === name)
  return trendPalette[idx % trendPalette.length]
}
function toggleTrendSeries(name) {
  trendHidden.value = { ...trendHidden.value, [name]: !trendHidden.value[name] }
  renderTrendChart()
}

function onMultiProductChange() {
  multiFilterCampaign.value = ''
  multiFilterAccount.value = ''
  loadMultiAnalysis()
}
function onMultiCampaignChange() {
  multiFilterAccount.value = ''
  loadMultiAnalysis()
}

// 对比
const compareGroupBy = ref('product_name')
const compareItems = ref([])

// 跨用户
const crossUserData = ref([])

// AI
const aiEnabled = ref(null)
const aiMessages = ref([])
const aiQuestion = ref('')
const aiLoading = ref(false)

// 多维分析
const multiMetrics = [
  { label: '花费($)', value: 'cost' },
  { label: 'CPI($)', value: 'cpi' },
  { label: 'CTR(%)', value: 'ctr' },
  { label: 'CVR(%)', value: 'cvr' },
  { label: '安装', value: 'installs' },
  { label: '展示', value: 'impressions' },
  { label: '点击', value: 'clicks' },
]
const multiProductOptions = computed(() => {
  if (filterProduct.value.length) return filterProduct.value
  return filterProducts.value.map(p => p.name)
})
const multiXAxis = ref('cost')
const multiYAxis = ref('cpi')
const multiSizeBy = ref('')
const multiGroupBy = ref('account')
const multiFilterProduct = ref([])
const multiFilterCampaign = ref('')
const multiFilterAccount = ref('')
const multiSplitDate = ref(false)
const multiPoints = ref([])
const multiCampaignOptions = ref([])
const multiAccountOptions = ref([])
const multiStats = ref(null)
const multiInsights = ref([])
const multiLoaded = ref(false)
const multiChart = ref(null)
const multiAiMessages = ref([])
const multiChatHistory = ref([])
const multiChatQuestion = ref('')
const multiChatLoading = ref(false)
const multiTableVisible = ref(true)
const multiTableData = computed(() => {
  const pts = multiHistPoints.value.length || multiNewPoints.value.length
    ? [...multiHistPoints.value, ...multiNewPoints.value]
    : multiPoints.value
  return pts.map(p => ({ name: p.name, source: p.source || '', ...p.detail }))
})
// 粘贴区
const multiShowPaste = ref(false)
const multiPasteRaw = ref('')
const multiPasteCampaignId = ref(false)
const multiParsedRows = ref([])
const multiParseError = ref('')
const multiParseLoading = ref(false)
const multiCompareOn = ref(false)
const multiHistPoints = ref([])
const multiNewPoints = ref([])

// 筛选参数
function filterParams() {
  const p = {}
  const prodArr = Array.isArray(filterProduct.value) ? filterProduct.value : (filterProduct.value ? [filterProduct.value] : [])
  if (prodArr.length) p.product_name = prodArr.join(',')
  if (filterRegion.value) p.region = filterRegion.value
  if (filterDateRange.value) {
    p.from_date = filterDateRange.value[0]
    p.to_date = filterDateRange.value[1]
  }
  return p
}

function onGlobalProductChange() {
  multiFilterCampaign.value = ''
  multiFilterAccount.value = ''
  refreshAll()
}

async function refreshAll() {
  loadDates()
  loadDashboard()
  loadTrends()
  loadCompare()
  loadCrossUser()
}

async function loadDates() {
  try {
    const res = await api.get('/ad-reports/dates', { params: filterParams() })
    dateDates.value = res.dates || {}
  } catch { dateDates.value = {} }
}

async function loadDashboard() {
  try {
    const res = await reportsApi.dashboard(filterParams())
    dashboardData.value = res
  } catch { dashboardData.value = null }
}

async function loadTrends() {
  trendHidden.value = {}
  trendLoading.value = true
  try {
    const params = { metric: trendMetric.value, group_by: trendGroupBy.value }
    if (trendProducts.value.length) params.product_name = trendProducts.value.join(',')
    if (filterRegion.value) params.region = filterRegion.value
    if (filterDateRange.value) {
      params.from_date = filterDateRange.value[0]
      params.to_date = filterDateRange.value[1]
    }
    const res = await reportsApi.trends(params)
    trendSeries.value = res.series || []
    await nextTick()
    if (trendSeries.value.length) renderTrendChart()
  } catch { trendSeries.value = [] }
  trendLoading.value = false
}

function renderTrendChart() {
  if (!trendChart.value || !trendSeries.value.length) return
  const container = trendChart.value
  // 确保容器有尺寸
  if (container.clientWidth === 0 || container.clientHeight === 0) return
  let chart = container._echart
  if (!chart) {
    chart = echarts.init(container)
    container._echart = chart
  }
  // 收集所有日期，去重排序
  const allDates = [...new Set(trendSeries.value.flatMap(s => s.data.map(d => d.date)))].sort()
  // 每个系列按日期对齐，缺失日期填 null；跳过隐藏的系列
  const visibleSeries = trendSeries.value.filter(s => !trendHidden.value[s.name])
  const series = visibleSeries.map(s => {
    const dateMap = Object.fromEntries(s.data.map(d => [d.date, d.value]))
    return {
      name: s.name,
      type: 'line',
      data: allDates.map(d => dateMap[d] ?? null),
      smooth: true,
      connectNulls: true,
    }
  })
  chart.clear()
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 30, top: 20, bottom: 20 },
    color: ['#5470c6','#91cc75','#fac858','#ee6666','#73c0de','#3ba272','#fc8452','#9a60b4','#ea7ccc','#48b8d0',
            '#d48265','#6e7074','#ca8622','#bda29a','#546570','#c4ccd3','#f6c7b6','#61a0a8','#d48265'],
    xAxis: { type: 'category', data: allDates },
    yAxis: { type: 'value' },
    series,
  })
  chart.resize()
}

async function loadCompare() {
  try {
    const res = await reportsApi.compare({ ...filterParams(), group_by: compareGroupBy.value })
    compareItems.value = res.items || []
  } catch { compareItems.value = [] }
}

async function loadCrossUser() {
  if (!filterProduct.value.length) { crossUserData.value = []; return }
  try {
    const res = await reportsApi.crossUser({ ...filterParams() })
    crossUserData.value = res.users || []
  } catch { crossUserData.value = [] }
}

const aiForm = reactive({
  api_key: '',
  model: 'deepseek-v4-flash',
  endpoint: 'https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions',
})
const aiSaving = ref(false)
const aiMsg = ref('')
const showAiConfig = ref(false)

async function loadAiConfig() {
  try {
    const res = await api.get('/config/ai')
    if (res.config) {
      aiForm.api_key = res.config.api_key || ''
      aiForm.model = res.config.model || 'deepseek-v4-flash'
      aiForm.endpoint = res.config.endpoint || 'https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions'
    }
  } catch { /* 静默 */ }
}

async function saveAiConfig() {
  aiSaving.value = true
  try {
    await api.post('/config/ai', { ...aiForm, enabled: true, provider: 'volcano' })
    aiEnabled.value = true
    aiMsg.value = '✅ 已启用'
    setTimeout(() => aiMsg.value = '', 2000)
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || ''))
  }
  aiSaving.value = false
}

async function checkAIEnabled() {
  try {
    const res = await reportsApi.analyze({ question: '', filters: {} })
    aiEnabled.value = res.enabled
    if (!res.enabled) await loadAiConfig()
  } catch { aiEnabled.value = false }
}

async function askAI() {
  const q = aiQuestion.value.trim()
  if (!q) return
  aiQuestion.value = ''
  aiMessages.value.push({ role: 'user', content: q })
  aiLoading.value = true
  try {
    const res = await reportsApi.analyze({ question: q, filters: filterParams() })
    if (!res.enabled) {
      aiMessages.value.push({ role: 'assistant', content: 'AI 分析未启用。' })
    } else {
      aiMessages.value.push({ role: 'assistant', content: res.answer || '暂无回复' })
    }
  } catch (e) {
    aiMessages.value.push({ role: 'assistant', content: '请求失败: ' + (e.message || '') })
  }
  aiLoading.value = false
}

// 初始化加载筛选选项
async function loadFilterOptions() {
  try {
    const params = { size: 1 }
    if (filterRegion.value) params.region = filterRegion.value
    if (filterProduct.value.length) params.product_name = filterProduct.value.join(',')
    const res = await reportsApi.list(params)
    filterProducts.value = res.products || []
    filterRegions.value = res.regions || []
  } catch {}
}

onMounted(() => {
  loadFilterOptions()
  loadDates()
  loadDashboard()
  checkAIEnabled()
})

// 地区变化时刷新产品列表 + 联动多维分析
watch(filterRegion, () => {
  trendProducts.value = []
  multiFilterCampaign.value = ''
  multiFilterAccount.value = ''
  loadFilterOptions()
  if (activeTab.value === 'multi') loadMultiAnalysis()
})

// 产品变化时刷新地区列表 + 联动多维分析
watch(filterProduct, () => {
  multiFilterCampaign.value = ''
  multiFilterAccount.value = ''
  loadFilterOptions()
  if (activeTab.value === 'multi') {
    multiFilterProduct.value = filterProduct.value.length ? [...filterProduct.value] : []
    loadMultiAnalysis()
  }
})

watch(activeTab, (tab) => {
  if (tab === 'trends') {
    // 趋势页未选产品则用全局筛选的产品
    if (!trendProducts.value.length && filterProduct.value.length) {
      trendProducts.value = [...filterProduct.value]
    }
    if (trendProducts.value.length) loadTrends()
  }
  if (tab === 'compare') loadCompare()
  if (tab === 'multi') {
    if (!multiFilterProduct.value.length && filterProduct.value.length) {
      multiFilterProduct.value = filterProduct.value[0]
    }
    loadMultiAnalysis()
  }
  if (tab === 'crossUser') loadCrossUser()
  if (tab === 'ai') checkAIEnabled()
})

// ===== 多维分析 =====
function parsePastedData() {
  multiParseError.value = ''
  multiParsedRows.value = []
  multiParseLoading.value = true
  try {
    const { raw } = parseAdsData(multiPasteRaw.value, { includeCampaignId: multiPasteCampaignId.value })
    multiParsedRows.value = raw
    if (!raw.length) multiParseError.value = '未解析到有效数据'
  } catch (e) {
    multiParseError.value = e.message
  }
  multiParseLoading.value = false
}

async function onCompareToggle(on) {
  if (!on) {
    multiHistPoints.value = []
    multiNewPoints.value = []
    await loadMultiAnalysis()
    return
  }
  if (!multiParsedRows.value.length) {
    multiCompareOn.value = false
    return
  }
  multiLoaded.value = false
  try {
    const params = { ...filterParams(), x_axis: multiXAxis.value, y_axis: multiYAxis.value, group_by: multiGroupBy.value }
    if (multiSizeBy.value) params.size_by = multiSizeBy.value
    if (multiFilterProduct.value) params.product_name = multiFilterProduct.value.join(',')
    if (multiFilterCampaign.value) params.campaign = multiFilterCampaign.value
    if (multiFilterAccount.value) params.account = multiFilterAccount.value
    if (multiSplitDate.value) params.split_by_date = '1'
    const res = await reportsApi.multiAnalysisPost({ params, extra_rows: multiParsedRows.value })
    multiHistPoints.value = res.historical || []
    multiNewPoints.value = res.new || []
    multiPoints.value = res.points || []
    multiCampaignOptions.value = res.campaign_options || []
    multiAccountOptions.value = res.account_options || []
    multiStats.value = res.stats || null
    multiInsights.value = res.insights || []
    multiLoaded.value = true
    await nextTick()
    renderScatterChart()
  } catch {
    multiHistPoints.value = []
    multiNewPoints.value = []
    multiLoaded.value = true
  }
}

async function loadMultiAnalysis() {
  multiCompareOn.value = false
  multiHistPoints.value = []
  multiNewPoints.value = []
  multiLoaded.value = false
  try {
    const params = { ...filterParams(), x_axis: multiXAxis.value, y_axis: multiYAxis.value, group_by: multiGroupBy.value }
    if (multiSizeBy.value) params.size_by = multiSizeBy.value
    if (multiFilterProduct.value) params.product_name = multiFilterProduct.value.join(',')
    if (multiFilterCampaign.value) params.campaign = multiFilterCampaign.value
    if (multiFilterAccount.value) params.account = multiFilterAccount.value
    if (multiSplitDate.value) params.split_by_date = '1'
    const res = await reportsApi.multiAnalysis(params)
    multiPoints.value = res.points || []
    multiCampaignOptions.value = res.campaign_options || []
    multiAccountOptions.value = res.account_options || []
    multiStats.value = res.stats || null
    multiInsights.value = res.insights || []
    multiAiMessages.value = []
    multiChatHistory.value = []
    multiLoaded.value = true
    await nextTick()
    renderScatterChart()
  } catch {
    multiPoints.value = []
    multiCampaignOptions.value = []
    multiAccountOptions.value = []
    multiStats.value = null
    multiInsights.value = []
    multiLoaded.value = true
  }
}

function renderScatterChart() {
  const isCompare = multiCompareOn.value && (multiHistPoints.value.length || multiNewPoints.value.length)
  const chartData = isCompare
    ? { hist: multiHistPoints.value, news: multiNewPoints.value }
    : { hist: multiPoints.value, news: [] }
  const allPts = isCompare ? [...chartData.hist, ...chartData.news] : chartData.hist
  if (!multiChart.value || !allPts.length) return

  let chart = multiChart.value._echart
  if (!chart) {
    chart = echarts.init(multiChart.value)
    multiChart.value._echart = chart
  }

  function _makeScatterData(pts) {
    return pts.map(p => ({ value: [p.x, p.y, p.size, p.name], name: p.name }))
  }
  function _tooltipFormatter(params) {
    // 在 allPts 中按 dataIndex + seriesIndex 查找
    const idx = params.seriesIndex === 0 || !isCompare ? params.dataIndex
      : chartData.hist.length + params.dataIndex
    const d = allPts[idx]
    if (!d) return ''
    const dt = d.detail
    const srcTag = d.source ? `【${d.source}】` : ''
    return `<b>${srcTag}${d.name}</b><br/>
      ${d.x_label}: ${d.x.toLocaleString()}<br/>
      ${d.y_label}: ${d.y.toLocaleString()}<br/>
      花费: $${(dt.total_cost||0).toLocaleString()}<br/>
      安装: ${(dt.total_installs||0).toLocaleString()}<br/>
      CPI: $${(dt.avg_cpi||0).toFixed(2)}<br/>
      CTR: ${((dt.ctr||0)*100).toFixed(2)}%<br/>
      CVR: ${((dt.cvr||0)*100).toFixed(2)}%`
  }

  const series = [
    {
      type: 'scatter', name: isCompare ? '历史数据' : '数据',
      data: _makeScatterData(chartData.hist),
      symbolSize: (val) => multiSizeBy.value ? Math.max(8, Math.min(60, Math.sqrt(val[2]) * 30)) : 14,
      label: { show: true, formatter: (p) => p.name, position: 'top', fontSize: 11 },
      itemStyle: { color: '#409eff' },
    },
  ]
  if (isCompare && chartData.news.length) {
    series.push({
      type: 'scatter', name: '新增数据',
      data: _makeScatterData(chartData.news),
      symbolSize: (val) => Math.max(8, Math.min(60, Math.sqrt(val[2]) * 30)),
      symbol: 'diamond',
      label: { show: true, formatter: (p) => p.name, position: 'top', fontSize: 11 },
      itemStyle: { color: '#f56c6c' },
    })
  }

  chart.setOption({
    tooltip: { trigger: 'item', formatter: _tooltipFormatter },
    legend: isCompare ? { data: ['历史数据', '新增数据'], bottom: 0 } : undefined,
    grid: { left: 70, right: 30, top: 20, bottom: isCompare ? 40 : 50 },
    xAxis: { type: 'value', name: allPts[0]?.x_label || 'X', nameLocation: 'center', nameGap: 30 },
    yAxis: { type: 'value', name: allPts[0]?.y_label || 'Y', nameLocation: 'center', nameGap: 40 },
    series,
  }, true)
}

const multiAiLoading = ref(false)

async function autoAiAnalysis() {
  if (!aiEnabled.value || !multiPoints.value.length) return
  multiAiLoading.value = true
  try {
    const ctx = {
      points: multiPoints.value,
      stats: multiStats.value,
      x_axis: multiXAxis.value,
      y_axis: multiYAxis.value,
      group_by: multiGroupBy.value,
    }
    const res = await reportsApi.multiAiChat({
      question: '请基于当前数据给出分析结论，指出关键发现和优化建议',
      context: ctx,
      history: [],
    })
    if (res.enabled && res.answer) {
      multiAiMessages.value = [{ role: 'assistant', content: res.answer }]
    }
  } catch { /* 忽略 AI 错误 */ }
  multiAiLoading.value = false
}

async function sendMultiChat() {
  const q = multiChatQuestion.value.trim()
  if (!q || !aiEnabled.value) return
  multiChatQuestion.value = ''
  multiChatHistory.value.push({ role: 'user', content: q })
  multiChatLoading.value = true
  try {
    const ctx = {
      points: multiPoints.value,
      stats: multiStats.value,
      x_axis: multiXAxis.value,
      y_axis: multiYAxis.value,
      group_by: multiGroupBy.value,
    }
    const res = await reportsApi.multiAiChat({
      question: q,
      context: ctx,
      history: multiChatHistory.value.slice(-10),
    })
    if (res.enabled) {
      multiChatHistory.value.push({ role: 'assistant', content: res.answer || '暂无回复' })
    } else {
      multiChatHistory.value.push({ role: 'assistant', content: 'AI 分析未启用。' })
    }
  } catch (e) {
    multiChatHistory.value.push({ role: 'assistant', content: '请求失败: ' + (e.message || '') })
  }
  multiChatLoading.value = false
}
</script>

<style scoped>
.stat-card {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 16px 20px;
  min-width: 120px;
  text-align: center;
}
.stat-val {
  font-size: 22px;
  font-weight: 700;
  color: #303133;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>

<style>
.analysis-date-picker .has-data {
  background: #ecf5ff;
}
.analysis-date-picker .has-data .el-date-table-cell__text {
  position: relative;
}
.analysis-date-picker .has-data .el-date-table-cell__text::after {
  content: '';
  position: absolute;
  bottom: 2px;
  left: 50%;
  transform: translateX(-50%);
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #409eff;
}
</style>
