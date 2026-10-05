/**
 * 产品下拉的显示过滤（做表页）。
 *
 * 做表页的产品下拉默认只列「未暂停」产品，但 zbProducts 必须保持全量 ——
 * zbUpdateSheet / 保存 里靠它 find() 取地区、代投比例，而那里用的是
 * `p?.sales_person || ''` 这种可选链：列表里被筛掉后不会报错，而是静默
 * 往 Google Sheets 写空值。所以过滤只发生在渲染层，不动原始列表。
 *
 * 兼容旧数据：只有 'paused' 才算暂停，'0' / 0 / '' / null 一律视为正常
 * （口径对齐后端 main.py 的 `(prod["status"] or "").strip() == "paused"`）。
 */

export function isPausedProduct(product) {
  const status = product && product.status
  return String(status ?? '').trim() === 'paused'
}

/**
 * 取用于渲染的产品列表。
 * @param {Array} products 全量产品（含已暂停）
 * @param {boolean} showPaused 是否连已暂停一起显示
 */
export function visibleProducts(products, showPaused) {
  const list = products || []
  return showPaused ? list : list.filter((p) => !isPausedProduct(p))
}
