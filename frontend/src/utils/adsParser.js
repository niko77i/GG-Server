/**
 * Google Ads 竖排数据清洗工具。
 * 从 ToolkitView 提取，ToolkitView 和 AnalysisView 共用。
 *
 * @param {string} rawText - 粘贴的原始文本
 * @param {object} opts
 * @param {boolean} opts.isYanghu - 养户模式（7列），默认 false
 * @param {boolean} opts.includeCampaignId - 含广告系列ID（11列），默认 false（10列）
 * @returns {{ raw: object[], zuobiao: object[], kehu: object[] }}
 */
export function parseAdsData(rawText, { isYanghu = false, includeCampaignId = false } = {}) {
  const input = rawText.trim()
  if (!input) throw new Error('请输入数据')

  const lines = input.split(/\r?\n/).map(l => l.trim()).filter(l => l)
  const starts = []; lines.forEach((l, i) => { if (l === '添加过滤条件') starts.push(i) })
  if (!starts.length) throw new Error('未找到"添加过滤条件"')
  const startIdx = starts[starts.length - 1]
  const endIdx = lines.indexOf('Total')
  if (endIdx < 0) throw new Error('未找到"Total"')
  if (startIdx >= endIdx) throw new Error('数据顺序异常')

  let step, costIdx, imprIdx, clickIdx
  if (isYanghu) {
    step = 7; costIdx = 4; imprIdx = 5; clickIdx = 6
  } else {
    step = includeCampaignId ? 11 : 10
    costIdx = includeCampaignId ? 5 : 4
    imprIdx = includeCampaignId ? 6 : 5
    clickIdx = includeCampaignId ? 7 : 6
  }

  const validLines = lines.slice(startIdx + 1, endIdx)
  const chunks = []
  for (let i = 0; i < validLines.length; i += step) {
    const row = validLines.slice(i, i + step)
    if (row.length === step && /^\d{3}-\d{3}-\d{4}$/.test(row[1]) && row[costIdx].includes('US$')) {
      chunks.push(row)
    }
  }
  if (!chunks.length) throw new Error('未找到有效数据（请确认费用列是否包含 "US$"）')

  /** @type {object[]} */
  let raw
  if (isYanghu) {
    raw = chunks.map(r => ({
      account: r[0], customerId: r[1],
      campaign: r[2].replace(/-[^-]*$/, '').trim(),
      campaignStatus: r[3] || '',
      cost: parseFloat(r[costIdx].replace(/[^0-9.-]+/g, '')) || 0,
      impressions: parseInt(r[imprIdx].replace(/[^0-9]/g, '')) || 0,
      clicks: parseInt(r[clickIdx].replace(/[^0-9]/g, '')) || 0,
    })).filter(d => d.cost > 0)
  } else {
    const installIdx = includeCampaignId ? 8 : 7
    const inAppIdx = includeCampaignId ? 9 : 8
    const cpiIdx = includeCampaignId ? 10 : 9
    raw = chunks.map(r => ({
      account: r[0], customerId: r[1],
      campaign: r[2].replace(/-[^-]*$/, '').trim(),
      campaignStatus: r[3] || '',
      cost: parseFloat(r[costIdx].replace(/[^0-9.-]+/g, '')) || 0,
      impressions: parseInt(r[imprIdx].replace(/[^0-9]/g, '')) || 0,
      clicks: parseInt(r[clickIdx].replace(/[^0-9]/g, '')) || 0,
      installs: parseFloat((r[installIdx] || '').replace(/[^0-9.-]+/g, '')) || 0,
      inAppActions: parseFloat((r[inAppIdx] || '').replace(/[^0-9.-]+/g, '')) || 0,
      costPerInApp: parseFloat((r[cpiIdx] || '').replace(/[^0-9.-]+/g, '')) || 0,
    })).filter(d => d.cost > 0)
  }

  // 做表聚合
  const zbMap = new Map()
  raw.forEach(d => {
    const key = d.customerId + '|||' + d.campaign
    if (!zbMap.has(key)) zbMap.set(key, { account: d.account, customerId: d.customerId, cost: d.cost, campaign: d.campaign })
    else zbMap.get(key).cost += d.cost
  })
  const zuobiao = Array.from(zbMap.values()).filter(d => d.cost > 0)

  // 客户表聚合
  const khMap = new Map()
  raw.forEach(d => {
    if (!khMap.has(d.campaign)) khMap.set(d.campaign, { campaign: d.campaign, cost: 0, impressions: 0, clicks: 0 })
    const item = khMap.get(d.campaign)
    item.cost += d.cost; item.impressions += d.impressions; item.clicks += d.clicks
  })
  const kehu = Array.from(khMap.values()).filter(d => d.cost > 0)

  return { raw, zuobiao, kehu }
}
