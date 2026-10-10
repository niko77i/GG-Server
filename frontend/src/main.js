import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './assets/global.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
app.use(createPinia())
// 平台上下文：**路由是最终依据**（切换平台即导航，见 AppSidebar.switchPlatform）。
// ⚠️ 校正必须挂在 `afterEach` 上：首帧导航是**异步**的（守卫经微任务），而 App.vue 的 onMounted
// 跑在导航解析**之前**（那时 `route.meta` 是空的）—— 曾因此写成一次空操作，刷新症状原样
// （2026-10-11 代码审查抓到）。注册在 `app.use(router)` 之前，确保首帧那次导航也覆盖到。
router.afterEach((to) => { useAuthStore().syncPlatformFromRoute(to.path) })
app.use(router)
app.use(ElementPlus, { locale: zhCn, size: 'large' })
app.mount('#app')
