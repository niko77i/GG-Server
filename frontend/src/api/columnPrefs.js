import client from './client'

export const columnPrefsApi = {
  // 拿当前登录用户的全部面板列配置
  get() {
    return client.get('/user/column-prefs')
  },
  // 整体替换某个面板的配置
  save(panel, order, hidden) {
    return client.put('/user/column-prefs', { panel, order, hidden })
  },
}
