# 脏数据解析 — 新增两种格式

**日期**: 2026-06-28  
**状态**: 已确认 → 已实现（2026-07-23 审计确认）

---

## 1. 需求描述

`_guess_series()` 脏数据解析函数当前支持 6 种格式。现需新增 2 种格式的支持：

1. **"广告命名"格式**：链接在上方，系列名在下方以 `广告命名：` 前缀标注
2. **"渠道命名"格式**：类似上述，但系列名中可能含空格（如 `FW66-GGB-GG-G38-Pebblewhisk Cocoa Twirl`）

当前逻辑对这 2 种格式均无法正确提取系列名。

## 2. 新增格式详解

### 格式 A：广告命名

```
https://play.google.com/store/apps/details?id=com.KoraCanyonsdfgsdf.koracanyon&gl=un&pli=1
广告命名：RT99-GGB-GG-G34-KoraCanyon
```

- 链接在行 N，系列名在行 N+1
- 前缀 `广告命名：` 或 `广告命名:`
- 系列名不含空格

### 格式 B：渠道命名（含空格）

```
https://play.google.com/store/apps/details?id=com.pebblewhisk.cocoa.twirl.app&gl=un&pli=11
包名：com.pebblewhisk.cocoa.twirl.app
启动类：com.unity3d.player.UnityPlayerActivity
渠道命名：FW66-GGB-GG-G38-Pebblewhisk Cocoa Twirl
```

- 链接在行 N，系列名在行 N+3
- 前缀 `渠道命名：` 或 `渠道命名:`
- 系列名含空格：`FW66-GGB-GG-G38-Pebblewhisk Cocoa Twirl`
- **当前类型 6 只能取到 `FW66-GGB-GG-G38-Pebblewhisk`（split 取首 token），丢失 `Cocoa Twirl`**

## 3. 技术方案

### 3.1 合并为一个新类型

`广告命名：` 和 `渠道命名：` 本质相同——都是 `xx命名：` 前缀行。用一个规则统一处理。

**搜索范围**：链接行向上 2 行到向下 4 行（代码 `range(link_idx - 2, link_idx + 5)`，共覆盖 6 行：link_idx-2 至 link_idx+4），覆盖两种场景的行距

**提取方式**：取前缀后整行内容（含空格），不再 split

### 3.1.1 完整匹配优先级链

`_guess_series()` 按以下顺序尝试匹配，命中即返回：

| 优先级 | 类型 | 搜索范围 | 说明 |
|--------|------|----------|------|
| 1 | 类型2 | 链接上方 1-8 行 | "神包上线"前缀行 |
| 2 | **类型7** | 链接±2/+4 行 | **广告命名/渠道命名前缀行（新增）** |
| 3 | 类型1 | 链接上方最多 10 行 | APK 或包号行 |
| 4 | 类型3 | 链接下方 1-5 行 | "应用名"前缀行 |
| 5 | 类型4 | 链接上方 1-3 行 | "名称"前缀行 |
| 6 | 类型6 | 链接上方最多 3 行 | 首列含 `-` 的行 |
| 7 | 类型5 | 兜底 | `_extract_pkg_from_url(link)` 从 URL 提取包名 |

**特殊 fallback**：当 link 在文本中完全找不到时（`link_idx < 0`），直接走 `_extract_pkg_from_url(link)` 兜底。

**依赖**：`_re_prod` 即 `import re as _re_prod`（第 2173 行），用于正则匹配和清理 token 前缀非单词字符。类型 1 用其 `search` 匹配 `包\d+`，类型 1/6 用其 `sub` 去除 token 前的标点符号。

### 3.2 新增代码（类型 7）

```python
# 类型7（新增）：广告命名/渠道命名 前缀行
for j in range(max(0, link_idx - 2), min(len(lines), link_idx + 5)):
    l = lines[j].strip()
    for prefix in ["广告命名：", "广告命名:", "渠道命名：", "渠道命名:"]:
        if prefix in l:
            name = l.split(prefix)[-1].strip()
            if name:
                return name
```

### 3.3 优先级顺序（详细见 3.1.1 表）

类型 7 放在类型 2 之后：有明确前缀标签，匹配精确度高，应在模糊匹配之前。

## 4. 涉及文件

| 项目 | 文件 | 改动 | 实际状态 |
|------|------|------|----------|
| GG-Server | `py/main.py` `_guess_series()` | 新增类型 7 代码块（第 3206-3212 行） | ✅ 已实现 |
| GG-Server | `AGENTS.md` 第 459-466 行 | 更新类型数量 6→7 | ✅ 已更新 |
| GG-Server | `NOTES.md` | 测试数据（无需改动，已含 4 条） | ✅ 已有 |
| GG-Server | `py/main.py` `/api/products/import-text` | 调用方（无需改动，第 3165 行） | 仅上下文 |
| ImageCrawling | `py/main.py` `_guess_series()` | 同步新增类型 7 | ⚠️ 待核实 |

### 4.1 prefix/suffix 后处理

`/api/products/import-text`（第 3165-3181 行）在 `_guess_series()` 返回系列名后，还会根据用户传入的 `prefix` 和 `suffix` 参数做额外处理：

- **prefix 逻辑**：若系列名尚未以 prefix 开头，且系列名的第一段（`-` 分隔）与 prefix 的第一段相同，则替换前缀段；否则直接拼接
- **suffix 逻辑**：若系列名尚未以 suffix 结尾，则追加 `-suffix`

类型 7 返回的完整系列名（含空格）会正常参与这些后处理逻辑。

## 5. 测试验证

用 NOTES.md 中的 4 组数据测试（2 条广告命名 + 2 条渠道命名）：

**测试 1（广告命名，不含空格）**：
```
输入文本：
https://play.google.com/store/apps/details?id=com.KoraCanyonsdfgsdf.koracanyon&gl=un&pli=1
广告命名：RT99-GGB-GG-G34-KoraCanyon

期望输出：RT99-GGB-GG-G34-KoraCanyon
```

**测试 2（广告命名，不含空格）**：
```
输入文本：
https://play.google.com/store/apps/details?id=com.sdcfgsdfLornSentinel.lornsentinel&gl=un&pli=1
广告命名：RT99-GGB-GG-G34-LornSentinel

期望输出：RT99-GGB-GG-G34-LornSentinel
```

**测试 3（渠道命名，含空格）**：
```
输入文本：
https://play.google.com/store/apps/details?id=com.pebblewhisk.cocoa.twirl.app&gl=un&pli=11
包名：com.pebblewhisk.cocoa.twirl.app
启动类：com.unity3d.player.UnityPlayerActivity
渠道命名：FW66-GGB-GG-G38-Pebblewhisk Cocoa Twirl

期望输出：FW66-GGB-GG-G38-Pebblewhisk Cocoa Twirl
```

**测试 4（渠道命名，含多个空格词）**：
```
输入文本：
https://play.google.com/store/apps/details?id=com.pippin.scallop.tray.zone&gl=un&pli=11
包名：com.pippin.scallop.tray.zone
启动类：com.unity3d.player.UnityPlayerActivity
渠道命名：FW66-GGB-GG-G38-Pippin Scallop Tray

期望输出：FW66-GGB-GG-G38-Pippin Scallop Tray
```

## 6. 注意事项

1. 保留空格，不做替换
2. 同时支持全角 `：` 和半角 `:`，与现有类型一致
3. 两个项目必须同步更新
4. 类型 7 返回的系列名含空格，下游 prefix/suffix 拼接逻辑（`/api/products/import-text` 第 3166-3181 行）依赖 `series.split("-")` 按 `-` 分段——空格不影响此逻辑，但需注意含空格的系列名不会被意外截断

## 7. 实现审计（2026-07-23）

### 7.1 代码验证

| 检查项 | 结果 |
|--------|------|
| 类型 7 代码块已添加 | ✅ `py/main.py` 第 3206-3212 行，与设计文档完全一致 |
| 优先级顺序正确 | ✅ 类型 2 → 类型 7 → 类型 1 → 类型 3 → 类型 4 → 类型 6 → 类型 5 |
| 搜索范围正确 | ✅ `range(link_idx - 2, link_idx + 5)` 覆盖 link_idx-2 至 link_idx+4 |
| 前缀覆盖完整 | ✅ 全角 `广告命名：` `渠道命名：` + 半角 `广告命名:` `渠道命名:` |
| 空格保留 | ✅ `split(prefix)[-1].strip()` 保留前缀后的完整内容 |
| AGENTS.md 已更新 | ✅ 类型数量 6→7，优先级链已更新（第 459-466 行） |

### 7.2 测试覆盖验证

NOTES.md 中 4 条测试数据的代码路径分析：

| 测试 | 系列名在 link_idx | 覆盖情况 |
|------|-------------------|----------|
| KoraCanyon (广告命名) | +1 | 在搜索窗口 link_idx-2 ~ link_idx+4 内 ✅ |
| LornSentinel (广告命名) | +1 | 同上 ✅ |
| Pebblewhisk (渠道命名) | +3 | 同上 ✅ |
| Pippin Scallop Tray (渠道命名) | +3 | 同上 ✅ |

### 7.3 遗留事项

- **ImageCrawling 同步**：设计文档要求 `py/main.py` `_guess_series()` 同步新增类型 7，本次审计未验证（ImageCrawling 项目不在当前仓库内）
- **自动化测试**：当前 `_guess_series()` 无单元测试覆盖，建议后续补充 `pytest` 参数化测试覆盖 7 种类型
