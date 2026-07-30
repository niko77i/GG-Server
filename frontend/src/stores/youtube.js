import { defineStore } from 'pinia'
import { youtubeApi, copywritingApi } from '@/api/youtube'
import { dedupLoader } from '@/utils/dedupLoader'

export const useYoutubeStore = defineStore('youtube', {
  state: () => ({
    videos: [],
    counts: {},
    tags: { regions: [], frame_types: [], effectiveness: [], product_names: [], review_statuses: [] },
    filters: { region: '', frame_type: '', effectiveness: '', product_name: '', review_status: '能过审', from_date: '', to_date: '', scope: 'private', uploader_id: '', channel_name: '' },
    videoDates: {},
    copywritings: [],
    copywritingCounts: {},
    cwScope: 'private',
  }),

  actions: {
    async loadVideos() {
      return dedupLoader(this, 'v', () => {
        return youtubeApi.list(this.filters).then(res => {
          this.videos = res.videos
          this.counts = res.counts
          return res
        })
      })
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
      return dedupLoader(this, 'cw', () => {
        const params = { scope: this.cwScope }
        if (region) params.region = region
        return copywritingApi.list(params).then(res => {
          this.copywritings = res.items
          this.copywritingCounts = res.counts
          return res
        })
      })
    },
    async importCopywritings(body) { return copywritingApi.import(body) },
    async editCopywriting(body) { return copywritingApi.edit(body) },
    async deleteCopywritings(ids) { await copywritingApi.delete({ ids }); return this.loadCopywritings() },
    async batchEditCopywritings(body) { return copywritingApi.batchEdit(body) },
  },
})
