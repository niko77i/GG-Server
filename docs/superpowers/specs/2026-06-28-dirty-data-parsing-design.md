# 脏数据解析 — 新增两种格式

**日期**: 2026-06-28  
**状态**: 已确认 → 实现中

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

**搜索范围**：链接行 ±2 行向上 / +5 行向下（覆盖两种场景的行距）

**提取方式**：取前缀后整行内容（含空格），不再 split

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

### 3.3 新的优先级顺序

```
类型2（神包上线）→ 类型7（广告/渠道命名）→ 类型1（APK行）
→ 类型3（应用名）→ 类型4（名称）→ 类型6（首列含-）→ 类型5（包名兜底）
```

类型 7 放在类型 2 之后：有明确前缀标签，匹配精确度高，应在模糊匹配之前。

## 4. 涉及文件

| 项目 | 文件 | 改动 |
|------|------|------|
| GG-Server | `py/main.py` `_guess_series()` | 新增类型 7 代码块 |
| GG-Server | `AGENTS.md` 第 220-227 行 | 更新类型数量 6→7 |
| ImageCrawling | `py/main.py` `_guess_series()` | 同步新增类型 7 |

## 5. 测试验证

用 NOTES.md 中的两组数据测试：

**测试 1**：
```
输入文本：
https://play.google.com/store/apps/details?id=com.KoraCanyonsdfgsdf.koracanyon&gl=un&pli=1
广告命名：RT99-GGB-GG-G34-KoraCanyon

期望输出：RT99-GGB-GG-G34-KoraCanyon
```

**测试 2**：
```
输入文本：
https://play.google.com/store/apps/details?id=com.pebblewhisk.cocoa.twirl.app&gl=un&pli=11
包名：com.pebblewhisk.cocoa.twirl.app
启动类：com.unity3d.player.UnityPlayerActivity
渠道命名：FW66-GGB-GG-G38-Pebblewhisk Cocoa Twirl

期望输出：FW66-GGB-GG-G38-Pebblewhisk Cocoa Twirl
```

## 6. 注意事项

1. 保留空格，不做替换
2. 同时支持全角 `：` 和半角 `:`，与现有类型一致
3. 两个项目必须同步更新
