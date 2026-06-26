import { defineStore } from 'pinia'
import { youtubeApi, copywritingApi } from '@/api/youtube'

export const useYoutubeStore = defineStore('youtube', {
  state: () => ({
    videos: [],
    counts: {},
    tags: { regions: [], frame_types: [], effectiveness: [], product_names: [], review_statuses: [] },
    filters: { region: '', frame_type: '', effectiveness: '', product_name: '', review_status: '能过审', from_date: '', to_date: '' },
    videoDates: {},
    copywritings: [],
    copywritingCounts: {},
  }),

  actions: {
    async loadVideos() {
      const res = await youtubeApi.list(this.filters)
      this.videos = res.videos
      this.counts = res.counts
    },
    async importVideos(body) { return youtubeApi.import(body) },
    async deleteVideos(ids) { await youtubeApi.delete({ ids }); return this.loadVideos() },
    async editVideo(body) { return youtubeApi.edit(body) },
    async batchEditVideos(body) { return youtubeApi.batchEdit(body) },
    async loadTags() { const res = await youtubeApi.tagsGet(); this.tags = res.tags; return res },
    async saveTags(body) { return youtubeApi.tagsSave(body) },
    async loadDates(params = {}) { const res = await youtubeApi.dates(params); this.videoDates = res.dates; return res },

    // 文案管理
    async loadCopywritings(region = '') {
      const res = await copywritingApi.list(region ? { region } : {})
      this.copywritings = res.items
      this.copywritingCounts = res.counts
    },
    async importCopywritings(body) { return copywritingApi.import(body) },
    async editCopywriting(body) { return copywritingApi.edit(body) },
    async deleteCopywritings(ids) { await copywritingApi.delete({ ids }); return this.loadCopywritings() },
    async batchEditCopywritings(body) { return copywritingApi.batchEdit(body) },
  },
})
