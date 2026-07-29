import { defineStore } from 'pinia'
import { accountsApi, mccApi, settingsApi, rechargeApi, optionApi } from '@/api/accounts'
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
    settings: { recharge_sheet_id: '', sheet_mappings: { recharge: '充值表', received_accounts: '已接账户明细', my_dashboard: '我的看板' } },
    options: {
      agents: [],
      statuses: [],
      mccLevels: [],
      salesPersons: [],
    },
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
          this.settings = {
            recharge_sheet_id: (res.settings && res.settings.recharge_sheet_id) || '',
            sheet_mappings: (res.settings && res.settings.sheet_mappings) || { recharge: '充值表', received_accounts: '已接账户明细', my_dashboard: '我的看板' },
          }
          this._settingsLoaded = true
          return res
        })
      }, () => this._settingsLoaded)
    },
    async saveSettings(body) { return settingsApi.save(body) },
    async rechargeSubmit(body) { return rechargeApi.submit(body) },
    async rechargeBatchSubmit(body) { return rechargeApi.batchSubmit(body) },
    async syncFromSheet(body) {
      return accountsApi.syncFromSheet(body)
    },
    async restoreAccount(id) {
      await accountsApi.restore(id)
      return this.loadAccounts()
    },
    async permanentDeleteAccount(id) {
      await accountsApi.permanentDelete(id)
    },
    async loadDeletedAccounts() {
      const res = await accountsApi.listDeleted()
      return res.accounts || []
    },

    // ---- option actions: agents ----
    async loadAgents() {
      const res = await optionApi.agents.list()
      this.options.agents = res.agents || []
      return this.options.agents
    },
    async createAgent(name) { const res = await optionApi.agents.create(name); await this.loadAgents(); return res },
    async renameAgent(id, name) { await optionApi.agents.rename(id, name); await this.loadAgents() },
    async deleteAgent(id) { await optionApi.agents.delete(id); await this.loadAgents() },

    // ---- option actions: statuses ----
    async loadStatuses() {
      const res = await optionApi.statuses.list()
      this.options.statuses = res.statuses || []
      return this.options.statuses
    },
    async createStatus(name) { const res = await optionApi.statuses.create(name); await this.loadStatuses(); return res },
    async renameStatus(id, name) { await optionApi.statuses.rename(id, name); await this.loadStatuses() },
    async deleteStatus(id) { await optionApi.statuses.delete(id); await this.loadStatuses() },

    // ---- option actions: mcc levels ----
    async loadMccLevels() {
      const res = await optionApi.mccLevels.list()
      this.options.mccLevels = res.mcc_levels || []
      return this.options.mccLevels
    },
    async createMccLevel(name) { const res = await optionApi.mccLevels.create(name); await this.loadMccLevels(); return res },
    async renameMccLevel(id, name) { await optionApi.mccLevels.rename(id, name); await this.loadMccLevels() },
    async deleteMccLevel(id) { await optionApi.mccLevels.delete(id); await this.loadMccLevels() },

    // ---- option actions: sales persons ----
    async loadSalesPersons() {
      const res = await optionApi.salesPersons.list()
      this.options.salesPersons = res.sales_persons || []
      return this.options.salesPersons
    },
    async createSalesPerson(name) { const res = await optionApi.salesPersons.create(name); await this.loadSalesPersons(); return res },
    async renameSalesPerson(id, name) { await optionApi.salesPersons.rename(id, name); await this.loadSalesPersons() },
    async deleteSalesPerson(id) { await optionApi.salesPersons.delete(id); await this.loadSalesPersons() },
  },
})
