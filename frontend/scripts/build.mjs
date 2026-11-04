/**
 * `npm run build` 的包装器：先把 TMP/TEMP 指到**工程内**的 `.tmp/`，再跑 `vite build`。
 *
 * 为什么需要它（2026-11-04 实测）：
 * esbuild 的 `esbuild-transpile` 插件会把转译结果写成临时文件再删除。在 Windows 上
 * 若临时目录不允许删除（受限 shell / 沙箱 / 安全软件锁文件），构建会在最后一步失败：
 *
 *   [vite:esbuild-transpile] remove C:\...\Temp\esbuild-xxxx: Access is denied.
 *
 * 换到工程内目录后一切正常。`vite build` 本身没毛病，所以不动构建配置，只换临时目录。
 *
 * 环境变量必须在 `import('vite')` **之前**设置：esbuild 是子进程，继承的是 Node 进程的
 * 环境变量，动态 import 之后 vite 内部的 esbuild 才会读取它。
 */
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const localTmp = join(here, '..', '.tmp')

mkdirSync(localTmp, { recursive: true })
process.env.TMP = localTmp
process.env.TEMP = localTmp
process.env.TMPDIR = localTmp

const { build } = await import('vite')
await build()
