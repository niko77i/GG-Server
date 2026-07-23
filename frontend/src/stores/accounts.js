import { defineStore } from 'pinia'
import { accountsApi, mccApi, settingsApi, rechargeApi } from '@/api/accounts'
import { dedupLoader, cachedLoader } from '@/utils/dedupLoader'

export const useAccountStore = defineStore('accounts', {
  state: () => ({
    accounts: [],
    acTotal: 0,
    acPage: 1,
    acPageSize: 20,
    acFilters: { search: '', status: '', mcc_id: '', agent: '', timezone: '' },
    mccList: [],
    mccTotal: 0,
    mccPage: 1,
    mccPageSize: 20,
    mccFilters: { search: '', level: '', parent_filter: '' },
    settings: { account_statuses: ['存活','死亡','验证','限额'], account_agents: [], mcc_levels: [], sales_persons: [] },
  }),

  actions: {
    async loadAccounts() {
      return dedupLoader(this, 'ac', () => {
        const params = { page: this.acPage, size: this.acPageSize, ...this.acFilters }
        return accountsApi.list(params).then(res => {
          this.accounts = res.accounts
          this.acTotal = res.total
          return res
        })
      })
    },
    async createAccount(body) { return accountsApi.create(body) },
    async reassignAccount(id, body) { return accountsApi.reassign(id, body) },
    async updateAccount(id, body) { return accountsApi.update(id, body) },
    async deleteAccount(id) { await accountsApi.delete(id); return this.loadAccounts() },
    async batchDeleteAccounts(ids) { await accountsApi.batchDelete(ids); return this.loadAccounts() },
    async batchUpdateAccounts(body) { await accountsApi.batchUpdate(body); return this.loadAccounts() },

    async loadMccList() {
      return dedupLoader(this, 'mccList', () => {
        const params = { page: this.mccPage, size: this.mccPageSize, ...this.mccFilters }
        return mccApi.list(params).then(res => {
          this.mccList = res.mcc_list
          this.mccTotal = res.total
          return res
        })
      })
    },
    async createMcc(body) { return mccApi.create(body) },
    async updateMcc(id, body) { return mccApi.update(id, body) },
    async deleteMcc(id) { await mccApi.delete(id); return this.loadMccList() },
    async batchDeleteMcc(ids) { const res = await mccApi.batchDelete(ids); await this.loadMccList(); return res },
    async loadMccDetail(id) { return mccApi.detail(id) },
    async linkMcc(id) { return mccApi.link(id) },

    async loadSettings() {
      return cachedLoader(this, 'settings', 300000, () => {
        return settingsApi.get().then(res => {
          this.settings = res.settings
          this._settingsLoaded = true
          return res
        })
      }, () => this._settingsLoaded)
    },
    async saveSettings(body) { return settingsApi.save(body) },
    async rechargeSubmit(body) { return rechargeApi.submit(body) },
    async rechargeBatchSubmit(body) { return rechargeApi.batchSubmit(body) },
  },
})
