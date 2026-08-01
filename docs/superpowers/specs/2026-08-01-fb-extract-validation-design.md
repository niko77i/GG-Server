# FB 数据提取 — 尾部数据校验

**日期**: 2026-08-01 | **状态**: ✅ 已确认

## 需求

FB 数据提取粘贴解析后，当前"总成效"之后的行（行数统计、总花费）被丢弃。现改为用这些数据做校验：

1. 从"已显示X/Y行"提取总行数 Y，校验解析行数是否匹配
2. 从尾部 `$` 金额（紧跟"总花费"）提取总消耗，校验是否等于各行消耗之和

## 后端改动

**文件**: `py/routes/fb_routes.py` — `_parse_fb_extract()` 函数

在找到 `end_idx`（"总成效"行）后，扫描尾部行：

- 正则 `已显示\d+/(\d+)行` 提取声明总行数
- 收集所有 `$` 开头金额，取最大值作为声明总花费（验证其后紧跟"总花费"）
- 在返回 JSON 中新增 `validation` 字段

```json
{
  "validation": {
    "declared_rows": 8,
    "extracted_rows": 8,
    "declared_spend": 9308.80,
    "extracted_spend": 9308.80
  }
}
```

## 前端改动

**文件**: `frontend/src/views/fb/FbDataExtract.vue` — `handleParse()`

解析成功后对比校验值：

| 校验 | 条件 | 提示 |
|------|------|------|
| 行数不足 | `extracted < declared` | ⚠ 复制的数据小于总行数，请检查 |
| 总消耗不一致 | `abs(extracted - declared) > 0.01` | ⚠ 总消耗不一致，请刷新广告报告后重新复制数据 |

提示使用 `ElMessage.warning`，duration 8 秒。
