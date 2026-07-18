import { defineStore } from 'pinia'
import { productsApi } from '@/api/products'

export const useProductStore = defineStore('products', {
  state: () => ({
    products: [],
    total: 0,
    page: 1,
    pageSize: 10,
    pausedMode: false,
    filters: { search: '', region: '', mcc_id: '' },
  }),

  actions: {
    async loadProducts(extra = {}) {
      if (this._loading) return this._lastPromise
      this._loading = true
      const params = {
        page: this.page, size: this.pageSize,
        search: this.filters.search || undefined,
        region: this.filters.region || undefined,
        mcc_id: this.filters.mcc_id || undefined,
        status: this.pausedMode ? 'paused' : '',
        runner: extra.runner || undefined,
      }
      const promise = productsApi.list(params).then(res => {
        this.products = res.products
        this.total = res.total
        return res
      }).finally(() => { this._loading = false })
      this._lastPromise = promise
      return promise
    },
    async createProduct(body) { return productsApi.create(body) },
    async updateProduct(id, body) { return productsApi.update(id, body) },
    async deleteProduct(id) { await productsApi.delete(id); return this.loadProducts() },
    async loadProductDetail(id) { return productsApi.detail(id) },
    async addPackage(pid, body) { return productsApi.addPackage(pid, body) },
    async updatePackage(pkgId, body) { return productsApi.updatePackage(pkgId, body) },
    async deletePackage(pkgId) { await productsApi.deletePackage(pkgId); return this.loadProducts() },
    async batchDeletePackages(ids) { await productsApi.batchDeletePackages(ids); return this.loadProducts() },
    async importText(body) { return productsApi.importText(body) },
  },
})
