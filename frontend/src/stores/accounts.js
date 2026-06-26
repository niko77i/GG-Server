import { defineStore } from 'pinia'
import { accountsApi, mccApi, settingsApi } from '@/api/accounts'

export const useAccountStore = defineStore('accounts', {
  state: () => ({
    accounts: [],
    acTotal: 0,
    acPage: 1,
    acPageSize: 20,
    acFilters: { search: '', status: '', mcc_id: '', agent: '' },
    mccList: [],
    mccTotal: 0,
    mccPage: 1,
    mccPageSize: 20,
    mccFilters: { search: '', level: '', parent_filter: '' },
    settings: { account_statuses: ['存活','死亡','验证','限额'], account_agents: [], mcc_levels: [] },
  }),

  actions: {
    async loadAccounts() {
      const params = { page: this.acPage, size: this.acPageSize, ...this.acFilters }
      const res = await accountsApi.list(params)
      this.accounts = res.accounts
      this.acTotal = res.total
      return res
    },
    async createAccount(body) { return accountsApi.create(body) },
    async updateAccount(id, body) { return accountsApi.update(id, body) },
    async deleteAccount(id) { await accountsApi.delete(id); return this.loadAccounts() },
    async batchDeleteAccounts(ids) { await accountsApi.batchDelete(ids); return this.loadAccounts() },
    async batchUpdateAccounts(body) { await accountsApi.batchUpdate(body); return this.loadAccounts() },

    async loadMccList() {
      const params = { page: this.mccPage, size: this.mccPageSize, ...this.mccFilters }
      const res = await mccApi.list(params)
      this.mccList = res.mcc_list
      this.mccTotal = res.total
    },
    async createMcc(body) { return mccApi.create(body) },
    async updateMcc(id, body) { return mccApi.update(id, body) },
    async deleteMcc(id) { await mccApi.delete(id); return this.loadMccList() },
    async batchDeleteMcc(ids) { const res = await mccApi.batchDelete(ids); await this.loadMccList(); return res },
    async loadMccDetail(id) { return mccApi.detail(id) },

    async loadSettings() {
      const res = await settingsApi.get()
      this.settings = res.settings
    },
    async saveSettings(body) { return settingsApi.save(body) },
  },
})
