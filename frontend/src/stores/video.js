import { defineStore } from 'pinia'
import { videoApi } from '@/api/video'

export const useVideoStore = defineStore('video', {
  state: () => ({
    images: [],
    logo: null,
    history: {},
    fonts: [],
  }),

  actions: {
    async scanDir(dir) {
      const res = await videoApi.scanDir({ dir })
      this.images = res.images
      this.logo = res.logo
      return res
    },
    async generate(body) { return videoApi.generate(body) },
    async checkProgress(taskId) { return videoApi.progress(taskId) },
    async loadHistory() { const res = await videoApi.historyList(); this.history = res.packages || {}; return res },
    async saveHistory(entry) { return videoApi.historySave({ entry }) },
    async deleteHistory(pkg, indices) { return videoApi.historyDelete({ pkg, indices }) },
    async loadFonts() { const res = await videoApi.fontsList(); this.fonts = res.fonts; return res },
    async audioReplace(body) { return videoApi.audioReplace(body) },
  },
})
