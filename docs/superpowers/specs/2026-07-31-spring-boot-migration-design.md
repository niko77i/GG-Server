# GG-Server Spring Boot 迁移设计文档

> **文档版本**: v1.10  
> **日期**: 2026-07-31（v1.10 更新于 2026-08-13）  
> **目的**: 将现有 Python Flask 后端完整迁移至 Java Spring Boot + MySQL  
> **新项目名称**: **LM-Server**（`D:\server\cc\LM-Server`，包名 `com.lmserver`）  
> **前置条件**: 前端 Vite/Vue3 不变，仅替换后端 API 层  
> **v1.10 变更**: 掉包通知按产品聚合——`delist/pending` 返回产品聚合结构、`delist/dismiss` 接受 `package_ids[]`、Telegram 通知改为产品级（产品名 + 多系列名，不展示包名/链接）；前端弹窗按产品统一为一条（详见 6.3 说明）
> **v1.9 变更**: 补充 `GoogleSheetsController` 的 `update-zuobiao` 接口产品/包名校验——包系列名与数据广告系列取交集，不匹配且无养户行时报错，有养户行时放行并返回 warning（此前该逻辑在迁移文档中完全缺失）
> **v1.8 变更**: 产品包列表前端交互增强——默认只展示「正常」状态包、状态筛选与排序按钮置于包列表工具栏、Shift 首尾范围选择勾选、按系列名（series_name）排序（降序/升序）+ 恢复默认排序按钮（纯前端，后端无改动，详见附录 F）  
> **v1.7 变更**: 产品创建冲突检测——同名已删除/已暂停产品返回 409 提示恢复（普通用户可恢复，无需管理员确认）；新增 `/api/products/{pid}/restore` 接口；修复 `products_create` 中 sales_person 兼容处理在 db/user_id 初始化前引用的隐患  
> **v1.6 变更**: 账户表格内联编辑扩展（时区/代理/状态）、表格UI整体优化、YouTube标签配置页空白修复  
> **v1.5 变更**: 同步 GG 账户管理最新实现——双向同步（含H列解绑）、软删除/恢复/物理删除、已删除列表  
> **v1.4 变更**: 清账逻辑兜底——改为直接查未清充值记录，不依赖 status_changed_date  
> **v1.3 变更**: FB 数据提取增加回流数据过滤 + $ 金额去重（行数与正常数据一致，仅消耗全为 $0.00）  
> **v1.2 变更**: 确定项目名 LM-Server、包名更新为 com.lmserver  
> **v1.1 变更**: 修正路由计数(226→236)、修正响应格式(items vs data)、修正DDL JSON默认值、新增密码迁移策略、新增前端兼容性矩阵、补充 helpers.py 迁移方案
---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构对比](#2-系统架构对比)
3. [项目结构设计](#3-项目结构设计)
4. [技术栈与依赖](#4-技术栈与依赖)
5. [数据库设计 — 40 张表 MySQL DDL](#5-数据库设计)
6. [API Controller 设计 — 240 个接口](#6-api-controller-设计)
7. [认证与安全](#7-认证与安全)
8. [业务服务层设计](#8-业务服务层设计)
9. [外部集成](#9-外部集成)
10. [配置管理](#10-配置管理)
11. [部署方案](#11-部署方案)
12. [迁移策略](#12-迁移策略)

---

## 1. 项目概述

### 1.1 现有系统规模

| 维度 | 数量 |
|------|------|
| 后端代码行数 | ~19,400 行 Python |
| API 路由 | **240 个** |
| 数据库表 | **40 张** |
| 前端页面 | 25 个 Vue 组件 |
| 外部集成 | 10 个（Google Sheets/Ads/AI/FFmpeg/邮件/Telegram 等） |
| 用户角色 | 5 级（developer / admin / viewer / user / hidden） |
| 平台隔离 | 2 个（GG Google Ads / FB Facebook Ads） |

### 1.2 功能模块清单

| 模块 | 路由数 | 说明 |
|------|--------|------|
| 认证系统 | 12 | 登录、注册、JWT、个人信息、改密 |
| GG 产品管理 | 17 | 产品 CRUD、包管理、在跑人员、掉包检测 |
| GG 账户管理 | 21 | 广告账户 CRUD、MCC 关联、批量操作、Sheet 双向同步、软删除/恢复/物理删除 |
| GG MCC 管理 | 8 | MCC CRUD、关联、详情 |
| GG 充值管理 | 5 | 单个/批量充值、Sheet 写入 |
| GG 广告报告 | 17 | 报告 CRUD、去重、分析、AI 对话、导出 |
| GG YouTube | 16 | 视频导入/列表/编辑/消费追踪、标签管理 |
| GG 文案管理 | 5 | 文案导入/列表/编辑/删除/批量 |
| FB BM 管理 | 7 | BM CRUD、封禁迁移 |
| FB 账户管理 | 8 | 账户 CRUD、BM 关联、软删除/恢复 |
| FB 产品管理 | 10 | 产品 CRUD、线名、在跑人员、BM 关联 |
| FB Pixel BM | 5 | Pixel BM CRUD |
| FB Pixel | 5 | Pixel CRUD、关联 |
| FB 数据提取 | 3 | 解析、去重、保存（异步写 Sheet） |
| FB 报告 | 9 | 报告 CRUD、统计、导出、Sheet 同步/重试 |
| 视频/音频 | 16 | AI 视频生成、FFmpeg 合成、音频替换、历史 |
| 图片抓取 | 5 | Google Play 截图抓取、上传 |
| 字体管理 | 7 | 字体导入/预览/上传 |
| 数据导入导出 | 3 | 用户级导入导出、历史 |
| 管理员 | 11 | 用户管理、数据导入、定时任务触发 |
| 系统配置 | 9 | AI 配置、Sheets 配置、账户设置 |
| 选项数据 | 20 | 代理/状态/MCC等级/商务/地区 CRUD |
| 审计/掉包 | 4 | 审计日志、掉包通知 |
| 工具类 | 5 | 文件浏览、翻译、用户查询 |
| 系统/静态 | 3 | 首页、健康检查 |

---

## 2. 系统架构对比

### 2.1 当前架构 (Python)

```
┌──────────────┐     ┌─────────────────────────────────┐
│  Vue 3 前端   │────▶│  Flask (单文件 main.py 9652行)    │
│  Vite 开发服  │     │  + auth_routes.py (205行)        │
│  Hash Router  │     │  + fb_routes.py (1455行)         │
└──────────────┘     │  + 15个业务模块                    │
                      │  + SQLite (WAL模式)               │
                      │  + Google Sheets/Ads API         │
                      │  + FFmpeg 子进程                  │
                      │  + SMTP / Telegram Bot           │
                      └─────────────────────────────────┘
```

### 2.2 目标架构 (Spring Boot)

```
┌──────────────┐     ┌─────────────────────────────────────────┐
│  Vue 3 前端   │────▶│  Spring Boot 3.x (JDK 17+)              │
│  (不变)       │     │                                         │
│  Vite        │     │  ┌─ Controller 层 (按模块分包)          │
│  baseURL: /api│     │  │  AuthController, FbController,      │
│              │     │  │  AccountController, ProductController │
│              │     │  │  ... (20+ Controller)                │
│              │     │  ├─ Service 层                           │
│              │     │  │  AuthService, SheetsService,          │
│              │     │  │  AdsService, AiService,              │
│              │     │  │  VideoService, EmailService ...      │
│              │     │  ├─ Repository 层 (JPA/MyBatis)         │
│              │     │  ├─ Security (Spring Security + JWT)    │
│              │     │  └─ Config (application.yml)            │
│              │     │                                         │
│              │     │  ┌─ MySQL 8.0                           │
│              │     │  │  连接池: HikariCP (默认)             │
│              │     │  └─ Redis (可选, 缓存/Session)          │
│              │     │                                         │
│              │     │  外部集成:                               │
│              │     │  Google Sheets API (Java SDK)            │
│              │     │  Google Ads API (Java SDK)               │
│              │     │  FFmpeg (ProcessBuilder)                │
│              │     │  SMTP (Spring Mail)                     │
│              │     │  Telegram Bot API (RestTemplate)        │
│              │     │  AI API (RestTemplate)                  │
│              │     └─────────────────────────────────────────┘
└──────────────┘
```

### 2.3 关键差异

| 维度 | Python Flask | Spring Boot |
|------|-------------|-------------|
| 并发模型 | Waitress 40线程 + GIL | 内嵌 Tomcat NIO，真正多线程 |
| 代码组织 | main.py 单文件近万行 | Controller → Service → Repository 三层分离 |
| 数据库 | SQLite (WAL) | MySQL 8.0 (HikariCP 连接池) |
| 认证 | flask-jwt-extended | Spring Security + jjwt |
| 异步 | threading.Thread | @Async + CompletableFuture |
| 定时任务 | threading.Timer | @Scheduled |
| 缓存 | 内存 dict + TTL | Caffeine / Redis |
| 类型安全 | 动态类型 | 编译期检查 |
| 部署 | pyinstaller EXE | java -jar fat JAR |

---

## 3. 项目结构设计

### 3.1 Maven/Gradle 项目结构

```
lm-server/
├── pom.xml (Maven)
├── src/
│   ├── main/
│   │   ├── java/com/lmserver/
│   │   │   ├── LmServerApplication.java          # 启动类
│   │   │   │
│   │   │   ├── config/                            # 配置类
│   │   │   │   ├── SecurityConfig.java            # Spring Security
│   │   │   │   ├── JwtConfig.java                 # JWT 配置
│   │   │   │   ├── WebConfig.java                 # CORS
│   │   │   │   ├── AsyncConfig.java               # 异步线程池
│   │   │   │   ├── CacheConfig.java               # Caffeine 缓存
│   │   │   │   ├── GoogleSheetsConfig.java        # Sheets SDK
│   │   │   │   ├── GoogleAdsConfig.java           # Ads SDK
│   │   │   │   └── MailConfig.java                # 邮件配置
│   │   │   │
│   │   │   ├── security/                          # 安全组件
│   │   │   │   ├── JwtTokenProvider.java          # Token 生成/验证
│   │   │   │   ├── JwtAuthenticationFilter.java   # JWT 过滤器
│   │   │   │   ├── PlatformGuardFilter.java       # GG/FB 平台守卫
│   │   │   │   └── UserPrincipal.java             # 用户主体
│   │   │   │
│   │   │   ├── controller/                        # 控制器 (按模块分包)
│   │   │   │   ├── auth/
│   │   │   │   │   └── AuthController.java        # /api/auth/*
│   │   │   │   ├── fb/
│   │   │   │   │   ├── FbBmController.java        # /api/fb/bms/*
│   │   │   │   │   ├── FbAccountController.java   # /api/fb/accounts/*
│   │   │   │   │   ├── FbProductController.java   # /api/fb/products/*
│   │   │   │   │   ├── FbPixelBmController.java   # /api/fb/pixel-bms/*
│   │   │   │   │   ├── FbPixelController.java     # /api/fb/pixels/*
│   │   │   │   │   ├── FbExtractController.java   # /api/fb/extract/*
│   │   │   │   │   └── FbReportController.java    # /api/fb/reports/*
│   │   │   │   ├── gg/
│   │   │   │   │   ├── ProductController.java     # /api/products/*
│   │   │   │   │   ├── AccountController.java     # /api/accounts/*
│   │   │   │   │   ├── MccController.java         # /api/mcc/*
│   │   │   │   │   ├── RechargeController.java    # /api/recharge/*
│   │   │   │   │   ├── AdReportController.java    # /api/ad-reports/*
│   │   │   │   │   ├── YoutubeController.java     # /api/youtube/*
│   │   │   │   │   └── CopywritingController.java # /api/copywriting/*
│   │   │   │   ├── admin/
│   │   │   │   │   ├── AdminUserController.java   # /api/admin/users/*
│   │   │   │   │   └── AdminDataController.java   # /api/admin/data/*
│   │   │   │   ├── ScrapeController.java          # /api/scrape/*
│   │   │   │   ├── VideoController.java           # /api/video/*
│   │   │   │   ├── FontController.java            # /api/fonts/*
│   │   │   │   ├── ConfigController.java          # /api/config/*
│   │   │   │   ├── SettingsController.java        # /api/settings/*
│   │   │   │   ├── OptionController.java          # /api/agents|statuses|.../*
│   │   │   │   ├── DataController.java            # /api/data/*
│   │   │   │   └── UtilityController.java         # /api/browse|translate/*
│   │   │   │
│   │   │   ├── service/                           # 业务服务层
│   │   │   │   ├── AuthService.java
│   │   │   │   ├── FbService.java                 # FB 平台核心业务
│   │   │   │   ├── AccountService.java            # GG 账户业务
│   │   │   │   ├── ProductService.java            # GG 产品业务
│   │   │   │   ├── MccService.java
│   │   │   │   ├── RechargeService.java
│   │   │   │   ├── AdReportService.java
│   │   │   │   ├── YoutubeService.java
│   │   │   │   ├── CopywritingService.java
│   │   │   │   ├── ScrapeService.java
│   │   │   │   ├── VideoService.java
│   │   │   │   ├── DataImportExportService.java
│   │   │   │   ├── AuditService.java
│   │   │   │   ├── DelistService.java
│   │   │   │   ├── OptionService.java
│   │   │   │   ├── sheets/
│   │   │   │   │   ├── GoogleSheetsService.java   # Sheets 核心读写
│   │   │   │   │   ├── GgSheetsWriter.java        # GG 做表数据写入
│   │   │   │   │   └── FbSheetsWriter.java        # FB 做表数据写入
│   │   │   │   ├── ads/
│   │   │   │   │   └── GoogleAdsService.java      # Google Ads API
│   │   │   │   ├── ai/
│   │   │   │   │   ├── AiVideoService.java        # AI 视频策略接口
│   │   │   │   │   └── impl/                      # 5个Provider实现
│   │   │   │   │       ├── SeedanceProvider.java
│   │   │   │   │       ├── DoubaoProvider.java
│   │   │   │   │       ├── DoubaoFastProvider.java
│   │   │   │   │       ├── VeoProvider.java
│   │   │   │   │       └── AtlasProvider.java
│   │   │   │   ├── notification/
│   │   │   │   │   ├── NotificationService.java   # 接口
│   │   │   │   │   ├── EmailSender.java
│   │   │   │   │   └── TelegramSender.java
│   │   │   │   └── delist/
│   │   │   │       └── DelistChecker.java
│   │   │   │
│   │   │   ├── repository/                        # 数据访问层 (JPA)
│   │   │   │   ├── UserRepository.java
│   │   │   │   ├── AccountRepository.java
│   │   │   │   ├── FbAccountRepository.java
│   │   │   │   ├── FbBmRepository.java
│   │   │   │   ├── FbProductRepository.java
│   │   │   │   ├── FbPixelRepository.java
│   │   │   │   ├── ProductRepository.java
│   │   │   │   ├── MccRepository.java
│   │   │   │   ├── RechargeRecordRepository.java
│   │   │   │   ├── AdReportRepository.java
│   │   │   │   ├── FbAdReportRepository.java
│   │   │   │   ├── VideoRepository.java
│   │   │   │   ├── CopywritingRepository.java
│   │   │   │   ├── AuditLogRepository.java
│   │   │   │   ├── ConfigRepository.java
│   │   │   │   └── ... (40个Repository)
│   │   │   │
│   │   │   ├── entity/                            # JPA 实体 (40个)
│   │   │   │   ├── User.java
│   │   │   │   ├── Account.java
│   │   │   │   ├── FbAccount.java
│   │   │   │   ├── FbBm.java
│   │   │   │   ├── ... (40个Entity)
│   │   │   │
│   │   │   ├── dto/                               # 数据传输对象
│   │   │   │   ├── request/                       # 请求 DTO
│   │   │   │   │   ├── LoginRequest.java
│   │   │   │   │   ├── CreateAccountRequest.java
│   │   │   │   │   ├── SaveExtractRequest.java
│   │   │   │   │   └── ... (按模块分类)
│   │   │   │   └── response/                      # 响应 DTO
│   │   │   │       ├── ApiResponse.java           # 统一响应 {success, data, error}
│   │   │   │       ├── PagedResponse.java         # 分页响应
│   │   │   │       └── ...
│   │   │   │
│   │   │   ├── enums/                             # 枚举
│   │   │   │   ├── UserRole.java                  # developer/admin/viewer/user/hidden
│   │   │   │   ├── Platform.java                  # gg/fb
│   │   │   │   └── AccountStatus.java             # 存活/死亡/验证/限额
│   │   │   │
│   │   │   ├── exception/                         # 异常处理
│   │   │   │   ├── GlobalExceptionHandler.java    # @ControllerAdvice
│   │   │   │   ├── BusinessException.java
│   │   │   │   ├── UnauthorizedException.java
│   │   │   │   └── PlatformForbiddenException.java
│   │   │   │
│   │   │   └── util/                              # 工具类
│   │   │       ├── JwtUtil.java
│   │   │       ├── PasswordUtil.java              # BCrypt
│   │   │       ├── DateUtil.java
│   │   │       └── FfmpegUtil.java
│   │   │
│   │   └── resources/
│   │       ├── application.yml                    # 主配置
│   │       ├── application-dev.yml                # 开发环境
│   │       ├── application-prod.yml               # 生产环境
│   │       └── service-account.json               # Google SA 密钥
│   │
│   └── test/
│       └── java/com/ggserver/
│           ├── controller/                        # Controller 测试
│           ├── service/                           # Service 测试
│           └── repository/                        # Repository 测试
```

### 3.2 包命名规范

```
基础包: com.lmserver
Controller: com.lmserver.controller.{模块}
Service:    com.lmserver.service.{模块}
Repository: com.lmserver.repository
Entity:     com.lmserver.entity
DTO:        com.lmserver.dto.{request|response}
Config:     com.lmserver.config
Security:   com.lmserver.security
```

---

## 4. 技术栈与依赖

### 4.1 Maven pom.xml 核心依赖

```xml
<parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.3.0</version>
</parent>

<properties>
    <java.version>17</java.version>
    <jjwt.version>0.12.5</jjwt.version>
</properties>

<dependencies>
    <!-- Web -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
    </dependency>

    <!-- Security + JWT -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-security</artifactId>
    </dependency>
    <dependency>
        <groupId>io.jsonwebtoken</groupId>
        <artifactId>jjwt-api</artifactId>
        <version>${jjwt.version}</version>
    </dependency>
    <dependency>
        <groupId>io.jsonwebtoken</groupId>
        <artifactId>jjwt-impl</artifactId>
        <version>${jjwt.version}</version>
        <scope>runtime</scope>
    </dependency>
    <dependency>
        <groupId>io.jsonwebtoken</groupId>
        <artifactId>jjwt-jackson</artifactId>
        <version>${jjwt.version}</version>
        <scope>runtime</scope>
    </dependency>

    <!-- Database -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>
    <dependency>
        <groupId>com.mysql</groupId>
        <artifactId>mysql-connector-j</artifactId>
        <scope>runtime</scope>
    </dependency>
    <!-- H2 for testing -->
    <dependency>
        <groupId>com.h2database</groupId>
        <artifactId>h2</artifactId>
        <scope>test</scope>
    </dependency>

    <!-- Validation -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-validation</artifactId>
    </dependency>

    <!-- Mail -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-mail</artifactId>
    </dependency>

    <!-- Async -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter</artifactId>
    </dependency>

    <!-- Cache -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-cache</artifactId>
    </dependency>
    <dependency>
        <groupId>com.github.ben-manes.caffeine</groupId>
        <artifactId>caffeine</artifactId>
    </dependency>

    <!-- Google APIs -->
    <dependency>
        <groupId>com.google.api-client</groupId>
        <artifactId>google-api-client</artifactId>
        <version>2.4.0</version>
    </dependency>
    <dependency>
        <groupId>com.google.apis</groupId>
        <artifactId>google-api-services-sheets</artifactId>
        <version>v4-rev612-1.25.0</version>
    </dependency>
    <dependency>
        <groupId>com.google.auth</groupId>
        <artifactId>google-auth-library-oauth2-http</artifactId>
        <version>1.23.0</version>
    </dependency>
    <dependency>
        <groupId>com.google.api-ads</groupId>
        <artifactId>google-ads</artifactId>
        <version>34.0.0</version>
    </dependency>

    <!-- HTML Parsing (替代 BeautifulSoup) -->
    <dependency>
        <groupId>org.jsoup</groupId>
        <artifactId>jsoup</artifactId>
        <version>1.17.2</version>
    </dependency>

    <!-- Image Processing (替代 Pillow) -->
    <dependency>
        <groupId>net.coobird</groupId>
        <artifactId>thumbnailator</artifactId>
        <version>0.4.20</version>
    </dependency>

    <!-- JSON -->
    <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-databind</artifactId>
    </dependency>

    <!-- Lombok -->
    <dependency>
        <groupId>org.projectlombok</groupId>
        <artifactId>lombok</artifactId>
        <optional>true</optional>
    </dependency>

    <!-- API 文档 (Swagger) -->
    <dependency>
        <groupId>org.springdoc</groupId>
        <artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>
        <version>2.6.0</version>
    </dependency>

    <!-- Entity↔DTO 自动转换 -->
    <dependency>
        <groupId>org.mapstruct</groupId>
        <artifactId>mapstruct</artifactId>
        <version>1.5.5.Final</version>
    </dependency>
    <dependency>
        <groupId>org.mapstruct</groupId>
        <artifactId>mapstruct-processor</artifactId>
        <version>1.5.5.Final</version>
        <scope>provided</scope>
    </dependency>

    <!-- 熔断器（保护外部 API 调用） -->
    <dependency>
        <groupId>io.github.resilience4j</groupId>
        <artifactId>resilience4j-spring-boot3</artifactId>
        <version>2.2.0</version>
    </dependency>

    <!-- 速率限制 -->
    <dependency>
        <groupId>com.bucket4j</groupId>
        <artifactId>bucket4j-core</artifactId>
        <version>8.7.0</version>
    </dependency>

    <!-- Test -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-test</artifactId>
        <scope>test</scope>
    </dependency>
    <dependency>
        <groupId>org.springframework.security</groupId>
        <artifactId>spring-security-test</artifactId>
        <scope>test</scope>
    </dependency>
</dependencies>
```

---

## 5. 数据库设计

> **数据库版本要求**: MySQL 8.0.13+（`DEFAULT (CURRENT_DATE)` 括号表达式需要此版本）

### 5.1 从 SQLite 到 MySQL 的变更

| SQLite 特性 | MySQL 替代 |
|-------------|-----------|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGINT AUTO_INCREMENT PRIMARY KEY` |
| `TEXT` | `VARCHAR(n)` 或 `TEXT` |
| `TEXT DEFAULT (datetime('now','localtime'))` | `DATETIME DEFAULT CURRENT_TIMESTAMP` |
| `TEXT DEFAULT '[]'` (JSON) | `JSON` 类型 |
| `UNIQUE(name, owner_id)` | 同名 |
| 外键 `ON DELETE CASCADE` | 同名 |
| WAL 模式 | InnoDB（默认） |
| 无连接池 | HikariCP（默认） |

### 5.2 完整 MySQL DDL

> **说明**: 以下为全部 40 张表的 MySQL 8.0 DDL。执行顺序应按分类依次执行。

```sql
-- ============================================================
-- GG-Server MySQL 8.0 完整建库脚本
-- 字符集: utf8mb4, 排序: utf8mb4_unicode_ci
-- 引擎: InnoDB
-- ============================================================

CREATE DATABASE IF NOT EXISTS ggserver
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE ggserver;

-- ============================================================
-- 一、用户和认证相关 (2 张表)
-- ============================================================

-- 1. users — 用户表
CREATE TABLE users (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    username         VARCHAR(20)  NOT NULL UNIQUE COMMENT '用户名（唯一）',
    password         VARCHAR(255) NOT NULL          COMMENT '密码（BCrypt 哈希）',
    role             VARCHAR(20)  NOT NULL DEFAULT 'user'
                     COMMENT '角色: developer/admin/viewer/user/hidden',
    display_name     VARCHAR(100) DEFAULT ''        COMMENT '显示名称',
    custom_name      VARCHAR(100) DEFAULT ''        COMMENT '自定义名称',
    email            VARCHAR(255) DEFAULT ''        COMMENT '邮箱',
    telegram_username VARCHAR(100) DEFAULT ''       COMMENT 'Telegram 用户名（不带@）',
    platform         VARCHAR(10)  DEFAULT 'gg'     COMMENT '所属平台: gg/fb',
    config           JSON         DEFAULT NULL      COMMENT '用户配置JSON（偏好设置等）',
    token_version    INT          DEFAULT 0         COMMENT 'JWT Token版本号（改密/禁用时递增）',
    created_at       DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    last_login       DATETIME     NULL              COMMENT '最后登录时间',
    created_by       BIGINT       NULL              COMMENT '创建者用户ID（自引用）',
    INDEX idx_users_role (role),
    INDEX idx_users_platform (platform),
    CONSTRAINT fk_users_created_by FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='用户表';

-- 2. config — 系统配置键值表
CREATE TABLE config (
    `key`  VARCHAR(255) PRIMARY KEY COMMENT '配置键',
    `value` TEXT         NULL     COMMENT '配置值（JSON字符串）'
) ENGINE=InnoDB COMMENT='系统配置键值表';

-- ============================================================
-- 二、GG (Google) 选项表 (5 张)
-- ============================================================

-- 3. agents — 代理/渠道选项表
CREATE TABLE agents (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL COMMENT '代理名称',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_agents_name_owner (name, owner_id),
    CONSTRAINT fk_agents_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='代理选项表';

-- 4. account_statuses — 账户状态选项表
CREATE TABLE account_statuses (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(50)  NOT NULL COMMENT '状态名称（存活/死亡/验证/限额）',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    platform   VARCHAR(10)  DEFAULT 'gg' COMMENT '平台隔离: gg/fb',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_statuses_name_owner (name, owner_id),
    CONSTRAINT fk_statuses_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='账户状态选项表';

-- 5. mcc_levels — MCC 等级选项表
CREATE TABLE mcc_levels (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL COMMENT '等级名称',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_mcc_levels_name_owner (name, owner_id),
    CONSTRAINT fk_mcc_levels_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='MCC等级选项表';

-- 6. sales_persons — 商务/销售人员选项表
CREATE TABLE sales_persons (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL COMMENT '商务名称',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    platform   VARCHAR(10)  DEFAULT 'gg' COMMENT '平台隔离: gg/fb',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sp_name_owner (name, owner_id),
    CONSTRAINT fk_sp_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='商务选项表';

-- 7. regions — 地区与时区管理
CREATE TABLE regions (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL COMMENT '地区名称',
    timezone   VARCHAR(50)  NOT NULL DEFAULT '' COMMENT '时区',
    platform   VARCHAR(10)  DEFAULT 'gg' COMMENT '平台隔离: gg/fb',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_regions_name_platform (name, platform)
) ENGINE=InnoDB COMMENT='地区与时区表';

-- ============================================================
-- 三、GG MCC 与账户 (5 张)
-- ============================================================

-- 8. mcc — MCC 管理表
CREATE TABLE mcc (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(255) NOT NULL COMMENT 'MCC 名称',
    mcc_id          VARCHAR(50)  NOT NULL UNIQUE COMMENT 'Google MCC ID',
    level_id        BIGINT       NULL     COMMENT 'MCC 等级外键',
    parent_mcc_id   BIGINT       NULL     COMMENT '父MCC ID（自引用）',
    owner_id        BIGINT       NULL     COMMENT '归属用户ID',
    shared_user_ids JSON         DEFAULT ('[]') COMMENT '共享用户ID列表',
    -- ↓ Spring Boot新增字段（Python版无），用于MCC凭证管理 ↓
    login_email     VARCHAR(255) DEFAULT '' COMMENT '【新增】登录邮箱',
    login_password  VARCHAR(255) DEFAULT '' COMMENT '【新增】登录密码',
    backup_email    VARCHAR(255) DEFAULT '' COMMENT '【新增】备用邮箱',
    backup_phone    VARCHAR(50)  DEFAULT '' COMMENT '【新增】备用手机号',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_mcc_level (level_id),
    INDEX idx_mcc_parent (parent_mcc_id),
    INDEX idx_mcc_owner (owner_id),
    CONSTRAINT fk_mcc_level FOREIGN KEY (level_id) REFERENCES mcc_levels(id),
    CONSTRAINT fk_mcc_parent FOREIGN KEY (parent_mcc_id) REFERENCES mcc(id),
    CONSTRAINT fk_mcc_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='MCC管理表';

-- 9. accounts — GG 广告账户表
CREATE TABLE accounts (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    name                VARCHAR(255) NOT NULL COMMENT '账户名称',
    account_id          VARCHAR(50)  NOT NULL UNIQUE COMMENT 'Google 广告账户ID',
    timezone            VARCHAR(50)  DEFAULT '' COMMENT '时区',
    agent_id            BIGINT       NULL     COMMENT '代理外键',
    status_id           BIGINT       NULL     COMMENT '状态外键',
    mcc_id              BIGINT       NULL     COMMENT '所属MCC外键',
    acquired_date       DATE         DEFAULT (CURRENT_DATE) COMMENT '获取日期',
    death_date          DATE         NULL     COMMENT '死亡日期',
    status_changed_date DATE         NULL     COMMENT '状态变更日期',
    owner_id            BIGINT       NULL     COMMENT '归属用户ID',
    deleted_at          DATETIME     NULL     COMMENT '软删除时间',
    created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_accounts_mcc (mcc_id),
    INDEX idx_accounts_owner (owner_id),
    INDEX idx_accounts_status (status_id),
    INDEX idx_accounts_agent (agent_id),
    INDEX idx_accounts_list (owner_id, status_id, deleted_at),
    INDEX idx_accounts_created (created_at),
    CONSTRAINT fk_accounts_agent FOREIGN KEY (agent_id) REFERENCES agents(id),
    CONSTRAINT fk_accounts_status FOREIGN KEY (status_id) REFERENCES account_statuses(id),
    CONSTRAINT fk_accounts_mcc FOREIGN KEY (mcc_id) REFERENCES mcc(id),
    CONSTRAINT fk_accounts_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='GG广告账户表';

-- 10. account_mcc_history — 账户 MCC 变更历史
CREATE TABLE account_mcc_history (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id   BIGINT       NOT NULL COMMENT '账户ID',
    old_mcc_id   BIGINT       NULL     COMMENT '旧MCC ID',
    new_mcc_id   BIGINT       NULL     COMMENT '新MCC ID',
    changed_by   BIGINT       NULL     COMMENT '操作人ID',
    change_type  VARCHAR(20)  NOT NULL DEFAULT 'manual' COMMENT '变更类型: manual/auto',
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_acmh_account (account_id),
    INDEX idx_acmh_changed_by (changed_by),
    CONSTRAINT fk_acmh_account FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    CONSTRAINT fk_acmh_changed_by FOREIGN KEY (changed_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='账户MCC变更历史';

-- 11. recharge_records — 充值记录表
CREATE TABLE recharge_records (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id     VARCHAR(50)  NOT NULL COMMENT '关联账户ID（引用 accounts.account_id）',
    amount         VARCHAR(50)  NOT NULL COMMENT '充值金额',
    agent_id       BIGINT       NULL     COMMENT '代理外键',
    operator       VARCHAR(100) DEFAULT '' COMMENT '操作员',
    status         VARCHAR(50)  DEFAULT '' COMMENT '充值状态',
    sheets_synced  TINYINT      DEFAULT 0 COMMENT 'Google Sheets 同步标记',
    sheets_error   TEXT         NULL     COMMENT 'Sheets 同步错误信息',
    created_by     BIGINT       NULL     COMMENT '创建者ID',
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_recharge_account (account_id),
    INDEX idx_recharge_created_by (created_by),
    CONSTRAINT fk_recharge_agent FOREIGN KEY (agent_id) REFERENCES agents(id),
    CONSTRAINT fk_recharge_created_by FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='充值记录表';

-- 12. sheets_sync_log — Google Sheets 同步日志
CREATE TABLE sheets_sync_log (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id        BIGINT       NOT NULL COMMENT '用户ID',
    product_name   VARCHAR(255) NOT NULL DEFAULT '' COMMENT '产品名称',
    spreadsheet_id VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Google Sheets 表ID',
    sheet_gid      VARCHAR(100) NOT NULL DEFAULT '' COMMENT 'Sheet GID',
    status         VARCHAR(50)  NOT NULL DEFAULT 'failed' COMMENT '同步状态',
    error_msg      TEXT         NULL     COMMENT '错误信息',
    rows_json      JSON         NULL     COMMENT '待同步行数据',
    retry_count    INT          DEFAULT 0 COMMENT '重试次数',
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_ssl_user_product (user_id, product_name),
    CONSTRAINT fk_ssl_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='Sheets同步日志';

-- ============================================================
-- 四、GG 产品与包 (7 张)
-- ============================================================

-- 13. products — GG 产品表
CREATE TABLE products (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_name    VARCHAR(255) NULL     COMMENT '产品名称',
    kpi             VARCHAR(255) NULL     COMMENT 'KPI指标',
    region          VARCHAR(100) NULL     COMMENT '地区',
    status          VARCHAR(50)  DEFAULT '' COMMENT '状态',
    customer        VARCHAR(255) DEFAULT '' COMMENT '客户名称',
    sales_person_id BIGINT       NULL     COMMENT '商务外键',
    mcc_id          BIGINT       NULL     COMMENT '所属MCC外键',
    agency_ratio    DOUBLE       NULL     COMMENT '代理比例',
    owner_id        BIGINT       NULL     COMMENT '归属用户ID',
    runner_ids      JSON         DEFAULT ('[]') COMMENT '在跑人员ID列表',
    is_archived     TINYINT      DEFAULT 0 COMMENT '是否归档',
    deleted_at      DATETIME     NULL     COMMENT '软删除时间',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_products_name (product_name),
    INDEX idx_products_region (region),
    INDEX idx_products_mcc (mcc_id),
    INDEX idx_products_owner (owner_id),
    INDEX idx_products_sp (sales_person_id),
    INDEX idx_products_created (created_at),
    CONSTRAINT fk_products_sp FOREIGN KEY (sales_person_id) REFERENCES sales_persons(id),
    CONSTRAINT fk_products_mcc FOREIGN KEY (mcc_id) REFERENCES mcc(id),
    CONSTRAINT fk_products_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='GG产品表';

-- 14. product_runners — 产品在跑人员关联表
CREATE TABLE product_runners (
    product_id BIGINT NOT NULL COMMENT '产品ID',
    user_id    BIGINT NOT NULL COMMENT '用户ID',
    PRIMARY KEY (product_id, user_id),
    INDEX idx_pr_user (user_id),
    CONSTRAINT fk_pr_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT fk_pr_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='产品在跑人员关联';

-- 15. packages — 产品包/素材系列表
CREATE TABLE packages (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id    BIGINT       NULL     COMMENT '所属产品ID',
    series_name   VARCHAR(255) NULL     COMMENT '系列名称',
    package_name  VARCHAR(255) NULL     COMMENT '包名称',
    url           TEXT         NULL     COMMENT '素材URL/地址',
    status        VARCHAR(50)  DEFAULT '' COMMENT '状态',
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_packages_product (product_id),
    CONSTRAINT fk_packages_product FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB COMMENT='产品包表';

-- 16. copywritings — 文案管理表
CREATE TABLE copywritings (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    region        VARCHAR(100) NOT NULL DEFAULT '通用' COMMENT '所属地区',
    content       TEXT         NOT NULL COMMENT '文案内容',
    owner_id      BIGINT       NULL     COMMENT '归属用户ID',
    effectiveness VARCHAR(50)  DEFAULT '' COMMENT '成效标记',
    is_public     TINYINT      DEFAULT 0 COMMENT '是否公开',
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_copywritings_region (region),
    INDEX idx_copywritings_owner (owner_id),
    CONSTRAINT fk_copywritings_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='文案管理表';

-- 17. product_assets — 产品成效素材关联
CREATE TABLE product_assets (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id      BIGINT       NOT NULL COMMENT '产品ID',
    video_id        VARCHAR(50)  NOT NULL COMMENT '视频ID',
    video_owner_id  BIGINT       NOT NULL DEFAULT 1 COMMENT '视频归属用户ID',
    added_by        BIGINT       NULL     COMMENT '添加者ID',
    added_at        DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_assets_product_video (product_id, video_id),
    INDEX idx_pa_video_owner (video_id, video_owner_id),
    CONSTRAINT fk_pa_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT fk_pa_added_by FOREIGN KEY (added_by) REFERENCES users(id),
    CONSTRAINT fk_pa_video_ref FOREIGN KEY (video_id, video_owner_id) REFERENCES videos(id, owner_id)
) ENGINE=InnoDB COMMENT='产品素材关联';

-- 17. scrape_cache — 爬取缓存表
CREATE TABLE scrape_cache (
    package_name VARCHAR(255) PRIMARY KEY COMMENT '包名称（主键）',
    image_count  INT          DEFAULT 0 COMMENT '图片数量',
    saved_path   TEXT         NULL     COMMENT '保存路径',
    logo_path    TEXT         NULL     COMMENT 'Logo路径',
    last_scraped DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '最后爬取时间',
    scraped_by   BIGINT       NULL     COMMENT '爬取操作人ID',
    CONSTRAINT fk_sc_cache_user FOREIGN KEY (scraped_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='爬取缓存表';

-- 18. import_history — 导入历史记录
CREATE TABLE import_history (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id            BIGINT       NULL     COMMENT '操作人ID',
    file_name          VARCHAR(255) NULL     COMMENT '文件名',
    file_type          VARCHAR(20)  NULL     COMMENT '文件类型: db/json',
    products_count     INT DEFAULT 0,
    packages_count     INT DEFAULT 0,
    accounts_count     INT DEFAULT 0,
    mcc_count          INT DEFAULT 0,
    videos_count       INT DEFAULT 0,
    copywritings_count INT DEFAULT 0,
    tags_count         INT DEFAULT 0,
    skipped_count      INT DEFAULT 0,
    status             VARCHAR(20)  DEFAULT 'success' COMMENT '状态',
    error_msg          TEXT         NULL     COMMENT '错误信息',
    created_at         DATETIME     DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ih_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='导入历史';

-- ============================================================
-- 五、YouTube / 视频 (9 张)
-- ============================================================

-- 19. videos — YouTube 视频表
CREATE TABLE videos (
    id            VARCHAR(50)  NOT NULL COMMENT '视频YouTube ID',
    owner_id      BIGINT       NOT NULL DEFAULT 1 COMMENT '归属用户ID',
    url           TEXT         NULL     COMMENT '视频URL',
    title         VARCHAR(500) NULL     COMMENT '视频标题',
    region        VARCHAR(100) DEFAULT '通用' COMMENT '地区',
    frame_type    VARCHAR(50)  DEFAULT '非融帧' COMMENT '融帧类型',
    effectiveness VARCHAR(50)  DEFAULT '' COMMENT '成效评估',
    product_name  VARCHAR(255) DEFAULT '' COMMENT '关联产品名称',
    review_status VARCHAR(50)  DEFAULT '能过审' COMMENT '审核状态',
    is_public     TINYINT      DEFAULT 0 COMMENT '是否公开',
    channel_name  VARCHAR(255) DEFAULT '' COMMENT '频道名称',
    imported_at   DATETIME     NULL     COMMENT '导入时间',
    PRIMARY KEY (id, owner_id),
    INDEX idx_videos_owner (owner_id),
    INDEX idx_videos_region (region),
    INDEX idx_videos_imported (imported_at),
    CONSTRAINT fk_videos_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='YouTube视频表';

-- 20. tags — 通用标签键值表
CREATE TABLE tags (
    `key`  VARCHAR(100) PRIMARY KEY COMMENT '标签键',
    `value` JSON         NULL     COMMENT '标签值（JSON数组）'
) ENGINE=InnoDB COMMENT='通用标签表';

-- 21. video_history — 视频生成历史
CREATE TABLE video_history (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    package    VARCHAR(255) NOT NULL COMMENT '所属包名',
    name       VARCHAR(255) DEFAULT '' COMMENT '历史记录名称',
    settings   JSON         NOT NULL COMMENT '设置JSON',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_history_pkg (package)
) ENGINE=InnoDB COMMENT='视频生成历史';

-- 22. video_tasks — 视频任务记录
CREATE TABLE video_tasks (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id     VARCHAR(100) NOT NULL UNIQUE COMMENT '任务唯一标识',
    package     VARCHAR(255) DEFAULT '' COMMENT '所属包名',
    status      VARCHAR(20)  DEFAULT 'pending' COMMENT '状态',
    progress    DOUBLE       DEFAULT 0 COMMENT '进度（0~1）',
    message     TEXT         NULL     COMMENT '状态信息',
    output_path VARCHAR(500) DEFAULT '' COMMENT '输出路径',
    settings    JSON         NULL     COMMENT '任务设置',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME     NULL     COMMENT '完成时间',
    INDEX idx_tasks_status (status)
) ENGINE=InnoDB COMMENT='视频任务记录';

-- 23. audio_replace_history — 音频替换历史
CREATE TABLE audio_replace_history (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    video_name  VARCHAR(255) NOT NULL COMMENT '视频文件名',
    audio_name  VARCHAR(255) NOT NULL COMMENT '替换音频文件名',
    output_name VARCHAR(255) NOT NULL COMMENT '输出文件名',
    output_path VARCHAR(500) NOT NULL COMMENT '输出路径',
    size_mb     DOUBLE       NOT NULL COMMENT '文件大小（MB）',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB COMMENT='音频替换历史';

-- 24. ad_reports — GG 广告投放报告
CREATE TABLE ad_reports (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id         BIGINT       NOT NULL COMMENT '上传用户ID',
    product_name    VARCHAR(255) NOT NULL COMMENT '产品名称',
    region          VARCHAR(100) NOT NULL COMMENT '地区',
    report_date     DATE         NOT NULL COMMENT '报告日期',
    account         VARCHAR(255) NOT NULL DEFAULT '' COMMENT '账户名称',
    customer_id     VARCHAR(100) NOT NULL DEFAULT '' COMMENT '客户ID',
    campaign        VARCHAR(255) NOT NULL DEFAULT '' COMMENT '广告系列',
    cost            DOUBLE       DEFAULT 0 COMMENT '消耗',
    impressions     INT          DEFAULT 0 COMMENT '展示次数',
    clicks          INT          DEFAULT 0 COMMENT '点击次数',
    installs        DOUBLE       DEFAULT 0 COMMENT '安装数',
    in_app_actions  DOUBLE       DEFAULT 0 COMMENT '应用内操作',
    cost_per_in_app DOUBLE       DEFAULT 0 COMMENT '单次应用内操作成本',
    saved_at        DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '保存时间',
    INDEX idx_ar_user_product_date (user_id, product_name, report_date),
    INDEX idx_ar_date (report_date),
    INDEX idx_ar_dedup (user_id, product_name, customer_id, campaign, report_date),
    CONSTRAINT fk_ar_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='GG广告投放报告';

-- 25. video_consumption — 视频消耗追踪
CREATE TABLE video_consumption (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    video_id       VARCHAR(50)  NOT NULL COMMENT '视频ID',
    video_owner_id BIGINT       NOT NULL DEFAULT 1 COMMENT '视频归属用户ID',
    user_id        BIGINT       NOT NULL COMMENT '录入用户ID',
    product_id     BIGINT       NULL     COMMENT '关联产品ID',
    amount         DOUBLE       NOT NULL DEFAULT 0 COMMENT '消耗金额',
    consume_date   DATE         NOT NULL DEFAULT (CURRENT_DATE) COMMENT '消耗日期',
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_vc_video (video_id, video_owner_id),
    INDEX idx_vc_user (user_id),
    INDEX idx_vc_product (product_id),
    INDEX idx_vc_date (consume_date),
    CONSTRAINT fk_vc_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_vc_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT fk_vc_video_ref FOREIGN KEY (video_id, video_owner_id) REFERENCES videos(id, owner_id)
) ENGINE=InnoDB COMMENT='视频消耗追踪';

-- ============================================================
-- 六、掉包检测与审计 (4 张)
-- ============================================================

-- 26. delist_checks — 掉包检测结果
CREATE TABLE delist_checks (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    package_id  BIGINT       NOT NULL UNIQUE COMMENT '包ID（唯一）',
    product_id  BIGINT       NOT NULL COMMENT '产品ID',
    is_delisted TINYINT      DEFAULT 0 COMMENT '是否掉包',
    checked_at  DATETIME     NULL     COMMENT '检测时间',
    error_msg   TEXT         NULL     COMMENT '错误信息',
    INDEX idx_dc_product (product_id),
    CONSTRAINT fk_dc_package FOREIGN KEY (package_id) REFERENCES packages(id),
    CONSTRAINT fk_dc_product FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB COMMENT='掉包检测结果';

-- 27. delist_notifications — 掉包通知状态
CREATE TABLE delist_notifications (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    package_id      BIGINT   NOT NULL COMMENT '包ID',
    user_id         BIGINT   NOT NULL COMMENT '用户ID',
    first_notified  TINYINT  DEFAULT 0 COMMENT '是否已首次通知',
    dismissed_at    DATETIME NULL     COMMENT '关闭时间',
    reminder_count  INT      DEFAULT 0 COMMENT '提醒次数',
    UNIQUE KEY uk_dn_package_user (package_id, user_id),
    INDEX idx_dn_user (user_id),
    CONSTRAINT fk_dn_package FOREIGN KEY (package_id) REFERENCES packages(id),
    CONSTRAINT fk_dn_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='掉包通知状态';

-- 28. audit_log — 审计日志
CREATE TABLE audit_log (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     BIGINT       NOT NULL COMMENT '操作人ID',
    action      VARCHAR(50)  NOT NULL COMMENT '操作类型（如: delete_product）',
    target_type VARCHAR(50)  NOT NULL COMMENT '目标类型（如: product）',
    target_id   BIGINT       NOT NULL COMMENT '目标ID',
    target_name VARCHAR(255) DEFAULT '' COMMENT '目标名称',
    detail      JSON         NULL     COMMENT '详情',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_audit_action (action),
    INDEX idx_audit_created (created_at),
    INDEX idx_audit_user (user_id),
    CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='审计日志';

-- ============================================================
-- 七、FB 平台 (11 张)
-- ============================================================

-- 29. fb_bms — FB 商务管理平台表
CREATE TABLE fb_bms (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(255) NOT NULL COMMENT 'BM 名称',
    bm_id      VARCHAR(50)  NOT NULL UNIQUE COMMENT 'Facebook BM ID',
    note       TEXT         NULL     COMMENT '备注',
    status     VARCHAR(20)  DEFAULT 'normal' COMMENT '状态: normal/deleted',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    deleted_at DATETIME     NULL     COMMENT '软删除时间',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_fb_bms_owner (owner_id),
    INDEX idx_fb_bms_status (status),
    INDEX idx_fb_bms_list (owner_id, status, deleted_at),
    CONSTRAINT fk_fb_bms_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB BM表';

-- 30. fb_accounts — FB 广告账户表
CREATE TABLE fb_accounts (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    name                VARCHAR(255) NOT NULL COMMENT '账户名称',
    account_id          VARCHAR(50)  NOT NULL UNIQUE COMMENT 'FB 账户ID',
    timezone            VARCHAR(50)  DEFAULT '' COMMENT '时区',
    status_id           BIGINT       NULL     COMMENT '状态外键',
    acquired_date       DATE         DEFAULT (CURRENT_DATE) COMMENT '获取日期',
    status_changed_date DATE         NULL     COMMENT '状态变更日期',
    owner_id            BIGINT       NULL     COMMENT '归属用户ID',
    deleted_at          DATETIME     NULL     COMMENT '软删除时间',
    created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_fb_accounts_owner (owner_id),
    INDEX idx_fb_accounts_list (owner_id, status_id, deleted_at),
    INDEX idx_fb_accounts_created (created_at),
    CONSTRAINT fk_fb_accounts_status FOREIGN KEY (status_id) REFERENCES account_statuses(id),
    CONSTRAINT fk_fb_accounts_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB广告账户表';

-- 31. fb_account_bm — FB 账户-BM 关联表
CREATE TABLE fb_account_bm (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id BIGINT   NOT NULL COMMENT '账户ID',
    bm_id      BIGINT   NOT NULL COMMENT 'BM ID',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fab_account_bm (account_id, bm_id),
    INDEX idx_fab_bm (bm_id),
    CONSTRAINT fk_fab_account FOREIGN KEY (account_id) REFERENCES fb_accounts(id) ON DELETE CASCADE,
    CONSTRAINT fk_fab_bm FOREIGN KEY (bm_id) REFERENCES fb_bms(id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='FB账户-BM关联';

-- 32. fb_account_bm_history — FB 账户-BM 变更历史
CREATE TABLE fb_account_bm_history (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    account_id  BIGINT       NOT NULL COMMENT '账户ID',
    old_bm_id   BIGINT       NULL     COMMENT '旧BM ID',
    new_bm_id   BIGINT       NULL     COMMENT '新BM ID',
    changed_by  BIGINT       NULL     COMMENT '操作人ID',
    change_type VARCHAR(20)  NOT NULL DEFAULT 'manual' COMMENT '变更类型',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fabmh_account (account_id),
    CONSTRAINT fk_fabmh_account FOREIGN KEY (account_id) REFERENCES fb_accounts(id),
    CONSTRAINT fk_fabmh_old_bm FOREIGN KEY (old_bm_id) REFERENCES fb_bms(id),
    CONSTRAINT fk_fabmh_new_bm FOREIGN KEY (new_bm_id) REFERENCES fb_bms(id),
    CONSTRAINT fk_fabmh_user FOREIGN KEY (changed_by) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB账户BM变更历史';

-- 33. fb_products — FB 产品表
CREATE TABLE fb_products (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_name    VARCHAR(255) NOT NULL COMMENT '产品名称',
    kpi             VARCHAR(255) DEFAULT '' COMMENT 'KPI指标',
    region          VARCHAR(100) DEFAULT '' COMMENT '地区',
    status          VARCHAR(50)  DEFAULT 'active' COMMENT '状态',
    sales_person_id BIGINT       NULL     COMMENT '商务外键',
    agency_ratio    DOUBLE       DEFAULT 0 COMMENT '代理比例',
    owner_id        BIGINT       NULL     COMMENT '归属用户ID',
    is_archived     TINYINT      DEFAULT 0 COMMENT '是否归档',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_fb_products_owner (owner_id),
    INDEX idx_fb_products_sp (sales_person_id),
    CONSTRAINT fk_fb_products_sp FOREIGN KEY (sales_person_id) REFERENCES sales_persons(id),
    CONSTRAINT fk_fb_products_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB产品表';

-- 34. fb_product_runners — FB 产品在跑人员关联
CREATE TABLE fb_product_runners (
    product_id BIGINT NOT NULL COMMENT '产品ID',
    user_id    BIGINT NOT NULL COMMENT '用户ID',
    PRIMARY KEY (product_id, user_id),
    INDEX idx_fpr_user (user_id),
    CONSTRAINT fk_fpr_product FOREIGN KEY (product_id) REFERENCES fb_products(id) ON DELETE CASCADE,
    CONSTRAINT fk_fpr_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB产品在跑人员关联';

-- 35. fb_product_bms — FB 产品-BM 关联表
CREATE TABLE fb_product_bms (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id BIGINT NOT NULL COMMENT '产品ID',
    bm_id      BIGINT NOT NULL COMMENT 'BM ID',
    UNIQUE KEY uk_fpb_product_bm (product_id, bm_id),
    INDEX idx_fpb_bm (bm_id),
    CONSTRAINT fk_fpb_product FOREIGN KEY (product_id) REFERENCES fb_products(id) ON DELETE CASCADE,
    CONSTRAINT fk_fpb_bm FOREIGN KEY (bm_id) REFERENCES fb_bms(id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='FB产品-BM关联';

-- 36. fb_pixel_bms — FB Pixel BM 管理
CREATE TABLE fb_pixel_bms (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(255) NOT NULL COMMENT '名称',
    bm_id      VARCHAR(50)  NOT NULL UNIQUE COMMENT 'FB BM ID',
    note       TEXT         NULL     COMMENT '备注',
    status     VARCHAR(20)  DEFAULT 'normal' COMMENT '状态',
    owner_id   BIGINT       NULL     COMMENT '归属用户ID',
    deleted_at DATETIME     NULL     COMMENT '软删除时间',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_fpbms_owner (owner_id),
    INDEX idx_fpbms_list (owner_id, status, deleted_at),
    CONSTRAINT fk_fpbms_owner FOREIGN KEY (owner_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB Pixel BM表';

-- 37. fb_pixels — FB Pixel 表
CREATE TABLE fb_pixels (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    pixel_bm_id BIGINT       NOT NULL COMMENT '所属 Pixel BM',
    pixel_name  VARCHAR(255) NOT NULL COMMENT 'Pixel 名称',
    pixel_id    VARCHAR(50)  NOT NULL UNIQUE COMMENT 'Pixel ID',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_fp_bm (pixel_bm_id),
    CONSTRAINT fk_fp_bm FOREIGN KEY (pixel_bm_id) REFERENCES fb_pixel_bms(id) ON DELETE CASCADE
) ENGINE=InnoDB COMMENT='FB Pixel表';

-- 38. fb_lines — FB 广告线/落地页
CREATE TABLE fb_lines (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id BIGINT       NOT NULL COMMENT '产品ID',
    line_name  VARCHAR(255) NOT NULL COMMENT '线路名称',
    link       TEXT         NULL     COMMENT '链接地址',
    pixel_id   BIGINT       NULL     COMMENT '关联Pixel',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fl_product_line (product_id, line_name),
    INDEX idx_fl_product (product_id),
    INDEX idx_fl_pixel (pixel_id),
    CONSTRAINT fk_fl_product FOREIGN KEY (product_id) REFERENCES fb_products(id) ON DELETE CASCADE,
    CONSTRAINT fk_fl_pixel FOREIGN KEY (pixel_id) REFERENCES fb_pixels(id) ON DELETE SET NULL
) ENGINE=InnoDB COMMENT='FB广告线';

-- 39. fb_ad_reports — FB 广告投放报告
CREATE TABLE fb_ad_reports (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id           BIGINT       NOT NULL COMMENT '上传用户ID',
    product_name      VARCHAR(255) NOT NULL COMMENT '产品名称',
    line_name         VARCHAR(255) DEFAULT '' COMMENT '线路名称',
    report_date       DATE         NOT NULL COMMENT '报告日期',
    account_name      VARCHAR(255) DEFAULT '' COMMENT '账户名称',
    account_id        VARCHAR(50)  DEFAULT '' COMMENT '账户ID',
    cost              DOUBLE       DEFAULT 0 COMMENT '消耗',
    impressions       INT          DEFAULT 0 COMMENT '展示次数',
    clicks            INT          DEFAULT 0 COMMENT '点击次数',
    registrations     INT          DEFAULT 0 COMMENT '注册数',
    purchases         INT          DEFAULT 0 COMMENT '购买数',
    cost_per_purchase DOUBLE       DEFAULT 0 COMMENT '单次购买成本',
    updated_at        DATETIME     NULL     COMMENT '更新时间',
    saved_at          DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '保存时间',
    -- 去重唯一索引：(用户, 产品, 线名, 账户ID, 日期)
    UNIQUE KEY uk_far_upsert (user_id, product_name, line_name, account_id, report_date),
    INDEX idx_far_user_date (user_id, report_date),
    INDEX idx_far_product_date (product_name, report_date),
    CONSTRAINT fk_far_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB COMMENT='FB广告投放报告';

-- ============================================================
-- 八、初始化数据
-- ============================================================

-- 默认 developer 账户（密码: admin123，BCrypt 编码）
INSERT INTO users (username, password, role, display_name, platform)
VALUES ('admin', '$2a$10$...', 'developer', '系统管理员', 'gg');

-- 默认标签数据
INSERT INTO tags (`key`, `value`) VALUES
('regions', '["巴西","菲律宾","孟加拉","印尼","东南亚通用","通用"]'),
('frame_types', '["融帧","非融帧"]'),
('effectiveness', '["","成效","一般"]'),
('review_statuses', '["能过审","不能过审"]'),
('product_names', '["p222","93ok"]');

-- 默认账户状态
INSERT INTO account_statuses (name, owner_id, platform) VALUES
('存活', NULL, 'gg'),
('死亡', NULL, 'gg'),
('验证', NULL, 'gg'),
('限额', NULL, 'gg');

-- FB 平台账户状态（与 GG 独立）
INSERT INTO account_statuses (name, owner_id, platform) VALUES
('存活', NULL, 'fb'),
('死亡', NULL, 'fb'),
('验证', NULL, 'fb'),
('限额', NULL, 'fb');
```

---

## 6. API Controller 设计

### 6.1 统一响应格式

保持与现有前端完全兼容。**关键兼容性说明**：Python `helpers.py` 的 `ok()` 函数对 `dict` 参数做展平处理，
导致分页列表使用 `items` 字段名而非 `data`。前端代码统一读取 `response.items`，Java 端必须保持一致。

```json
// 单对象成功响应（Python: ok(non_dict) → {"success": true, "data": ...}）
{
    "success": true,
    "data": { ... }
}

// 分页列表响应（Python: ok({'items':..., 'total':...}) → 展平到顶层）
{
    "success": true,
    "items": [...],            // 注意：字段名是 items，不是 data
    "total": 100,
    "page": 1,
    "size": 20
}

// 纯列表响应（无分页，Python: ok([...]) → {"success": true, "data": [...]}）
{
    "success": true,
    "data": [...]
}

// 错误响应
{
    "success": false,
    "error": "错误描述"
}
```

```java
// 统一响应 DTO
@Data
@AllArgsConstructor
@NoArgsConstructor
public class ApiResponse<T> {
    private boolean success;
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private T data;
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private String error;

    public static <T> ApiResponse<T> ok(T data) {
        return new ApiResponse<>(true, data, null);
    }

    public static <T> ApiResponse<T> ok() {
        return new ApiResponse<>(true, null, null);
    }

    public static <T> ApiResponse<T> fail(String error) {
        return new ApiResponse<>(false, null, error);
    }
}

// 分页响应（独立类 — 字段名必须与 Python 对齐：items 而非 data）
@Data
public class PagedResponse<T> {
    private boolean success = true;
    private List<T> items;      // 关键：使用 items，不是 data
    private long total;
    private int page;
    private int size;

    public static <T> PagedResponse<T> of(List<T> items, long total, int page, int size) {
        PagedResponse<T> resp = new PagedResponse<>();
        resp.setItems(items);
        resp.setTotal(total);
        resp.setPage(page);
        resp.setSize(size);
        return resp;
    }
}
```

### 6.2 Controller 示例

以下选取代表性的 Controller 展示设计思路，完整 20+ Controller 按相同模式实现。

#### AuthController

```java
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;
    private final JwtTokenProvider jwtTokenProvider;

    // POST /api/auth/login
    @PostMapping("/login")
    public ApiResponse<LoginResponse> login(@Valid @RequestBody LoginRequest req) {
        LoginResult result = authService.login(req.getUsername(), req.getPassword());
        if (result == null) {
            return ApiResponse.fail("Invalid credentials or account disabled");
        }
        return ApiResponse.ok(LoginResponse.builder()
            .accessToken(result.getAccessToken())
            .refreshToken(result.getRefreshToken())
            .user(result.getUser())
            .build());
    }

    // POST /api/auth/register
    @PostMapping("/register")
    public ApiResponse<UserDto> register(@Valid @RequestBody RegisterRequest req) {
        UserDto user = authService.register(
            req.getUsername(), req.getPassword(), req.getDisplayName());
        if (user == null) return ApiResponse.fail("Registration failed");
        return ApiResponse.ok(user);
    }

    // GET /api/auth/me
    @GetMapping("/me")
    public ApiResponse<UserDto> me(@AuthenticationPrincipal UserPrincipal principal) {
        UserDto user = authService.getUserById(principal.getUserId());
        if (user == null) return ApiResponse.fail("User not found");
        return ApiResponse.ok(user);
    }

    // PUT /api/auth/password
    @PutMapping("/password")
    public ApiResponse<Void> changePassword(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody ChangePasswordRequest req) {
        authService.changePassword(principal.getUserId(),
            req.getOldPassword(), req.getNewPassword());
        return ApiResponse.ok();
    }

    // PUT /api/auth/profile
    @PutMapping("/profile")
    public ApiResponse<UserDto> updateProfile(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody UpdateProfileRequest req) {
        UserDto updated = authService.updateProfile(principal.getUserId(),
            req.getDisplayName());
        return ApiResponse.ok(updated);
    }

    // GET /api/auth/names
    @GetMapping("/names")
    public ApiResponse<List<UserNameDto>> userNames(
            @AuthenticationPrincipal UserPrincipal principal) {
        return ApiResponse.ok(authService.getUserNames(principal));
    }

    // ... 其余 auth 路由 (custom-name, email, telegram-username)
}
```

#### FbBmController

```java
@RestController
@RequestMapping("/api/fb/bms")
@RequiredArgsConstructor
@FbPlatformRequired  // 自定义注解：需要 JWT + FB 平台
public class FbBmController {

    private final FbService fbService;

    // GET /api/fb/bms/list
    @GetMapping("/list")
    public PagedResponse<FbBmDto> list(
            @AuthenticationPrincipal UserPrincipal principal,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String status) {
        return fbService.listBms(principal.getUserId(), page, size, status);
    }

    // GET /api/fb/bms/unified — 统一列表（含 Pixel BM）
    @GetMapping("/unified")
    public PagedResponse<FbBmDto> listUnified(
            @AuthenticationPrincipal UserPrincipal principal,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String search,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String bmType) {
        return fbService.listUnifiedBms(principal.getUserId(), page, size,
            search, status, bmType);
    }

    // POST /api/fb/bms/create
    @PostMapping("/create")
    public ApiResponse<Long> create(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody CreateFbBmRequest req) {
        Long id = fbService.createBm(principal.getUserId(),
            req.getName(), req.getBmId(), req.getNote());
        return ApiResponse.ok(id);
    }

    // PUT /api/fb/bms/{bid}
    @PutMapping("/{bid}")
    public ApiResponse<Void> update(
            @AuthenticationPrincipal UserPrincipal principal,
            @PathVariable Long bid,
            @Valid @RequestBody UpdateFbBmRequest req) {
        fbService.updateBm(principal.getUserId(), bid,
            req.getName(), req.getNote());
        return ApiResponse.ok();
    }

    // DELETE /api/fb/bms/{bid}
    @DeleteMapping("/{bid}")
    public ApiResponse<Void> delete(
            @AuthenticationPrincipal UserPrincipal principal,
            @PathVariable Long bid) {
        fbService.softDeleteBm(principal.getUserId(), bid);
        return ApiResponse.ok();
    }

    // POST /api/fb/bms/{bid}/ban-and-migrate
    @PostMapping("/{bid}/ban-and-migrate")
    public ApiResponse<BanMigrateResult> banAndMigrate(
            @AuthenticationPrincipal UserPrincipal principal,
            @PathVariable Long bid,
            @Valid @RequestBody BanMigrateRequest req) {
        return ApiResponse.ok(fbService.banAndMigrate(bid,
            req.getTargetBmId(), req.getTargetBmName()));
    }

    // GET /api/fb/bms/options
    @GetMapping("/options")
    public ApiResponse<List<OptionDto>> options() {
        return ApiResponse.ok(fbService.getBmOptions());
    }
}
```

#### AccountController (GG)

```java
@RestController
@RequestMapping("/api/accounts")
@RequiredArgsConstructor
public class AccountController {

    private final AccountService accountService;

    // GET /api/accounts/list
    @GetMapping("/list")
    public PagedResponse<AccountDto> list(
            @AuthenticationPrincipal UserPrincipal principal,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String search,
            @RequestParam(required = false) Long statusId,
            @RequestParam(required = false) Long mccId,
            @RequestParam(required = false) Long agentId,
            @RequestParam(required = false) String sort,
            @RequestParam(required = false) String order) {
        return accountService.listAccounts(principal.getUserId(),
            AccountQuery.builder()
                .page(page).size(size)
                .search(search).statusId(statusId)
                .mccId(mccId).agentId(agentId)
                .sort(sort).order(order)
                .build());
    }

    // POST /api/accounts/create
    @PostMapping("/create")
    public ApiResponse<Long> create(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody CreateAccountRequest req) {
        return ApiResponse.ok(accountService.createAccount(
            principal.getUserId(), req));
    }

    // PUT /api/accounts/{aid}
    @PutMapping("/{aid}")
    public ApiResponse<Void> update(
            @AuthenticationPrincipal UserPrincipal principal,
            @PathVariable Long aid,
            @Valid @RequestBody UpdateAccountRequest req) {
        accountService.updateAccount(principal.getUserId(), aid, req);
        return ApiResponse.ok();
    }

    // POST /api/accounts/batch-update
    @PostMapping("/batch-update")
    public ApiResponse<Long> batchUpdate(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody BatchUpdateRequest req) {
        return ApiResponse.ok(accountService.batchUpdate(principal.getUserId(), req));
    }

    // POST /api/accounts/sync-from-sheet（双向同步）
    //   dry_run=true: 返回 diff（to_create / to_update / unchanged）
    //   dry_run=false: 执行创建+状态更新 → db.commit() → 系统→Sheet 同步 F列(备注)+H列(是否解绑)
    //   跳过 H列="解绑" 的账户，跳过系统已逻辑删除的账户
    @PostMapping("/sync-from-sheet")
    public ApiResponse<SyncResult> syncFromSheet(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody SyncRequest req) {
        return ApiResponse.ok(accountService.syncFromSheet(
            principal.getUserId(), req));
    }

    // DELETE /api/accounts/{aid} — 软删除（设 deleted_at，后台写 Sheet H列"解绑"）
    // POST /api/accounts/{aid}/restore — 恢复（清 deleted_at，后台清 Sheet H列）
    // DELETE /api/accounts/{aid}/permanent — 物理删除（不可恢复，清充值记录+MCC历史）
    // GET /api/accounts/deleted — 已删除账户列表
    // ... 其余路由 (batch-delete, batch-lookup, lookup, recharge-records, mcc-history, ...)
}
```

#### ProductController (GG)

```java
@RestController
@RequestMapping("/api/products")
@RequiredArgsConstructor
public class ProductController {

    private final ProductService productService;

    // POST /api/products/create — 创建产品（含同名冲突检测）
    //   前置：校验 product_name → 初始化上下文（db/user_id）→ sales_person 兼容处理
    //   sales_person 兼容：仅传 sales_person（字符串）时，查/建 sales_persons 表得到 sales_person_id
    //     （Python 原实现曾把该处理放在 db/user_id 初始化之前，存在 UnboundLocalError 隐患，迁移时注意顺序）
    //   逻辑：先按 product_name 查同名产品（不过滤 is_archived/deleted_at/status）
    //     · 同名产品已删除 (is_archived=1 或 deleted_at 非空) → 返回 409 + {conflict:"deleted", product_id, product_name}
    //     · 同名产品已暂停 (status="paused")               → 返回 409 + {conflict:"paused", product_id, product_name}
    //     · 同名产品正常                                     → 追加包/更新字段 + 加入 runner
    //     · 无同名产品                                       → 新建
    //   前端收到 409 后弹窗询问"该产品已删除/已暂停，是否恢复？"
    @PostMapping("/create")
    public ApiResponse<Long> create(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody CreateProductRequest req) {
        return productService.createProduct(principal.getUserId(), req);
    }

    // POST /api/products/{pid}/restore — 恢复已删除或已暂停的产品
    //   普通用户可操作（无需 developer/admin 确认）
    //   · 已删除产品：is_archived=0, deleted_at=null，并从 audit_log 快照恢复关联包
    //   · 已暂停产品：status=""（恢复正常）
    @PostMapping("/{pid}/restore")
    public ApiResponse<RestoreResult> restore(
            @AuthenticationPrincipal UserPrincipal principal,
            @PathVariable Long pid) {
        return ApiResponse.ok(productService.restoreProduct(pid));
    }
}
```

> **说明（v1.7 新增）**：原 Python `products_create` 的 existing 查询未过滤 `is_archived`/`deleted_at`，
> 导致创建与已删除产品同名的产品时静默更新旧记录（返回 200 但产品不可见）。
> 迁移时改为：创建接口先做冲突检测返回 409，新增独立 restore 接口统一处理"已删除/已暂停"两类恢复，
> 且恢复不再要求 developer 权限。

#### GoogleSheetsController

```java
@RestController
@RequestMapping("/api/google-sheets")
@RequiredArgsConstructor
public class GoogleSheetsController {

    private final GoogleSheetsService sheetsService;

    // POST /api/google-sheets/update-zuobiao — 做表数据写入（产品校验 + 入库 + 后台同步 Sheet）
    //   前置校验：
    //     1. product_name 必填（空 → 400 "产品名不能为空"）
    //     2. rows 必填（空 → 400 "做表数据不能为空"）
    //   产品/包名校验（核心，迁移易漏，详见下方 validateProductMatches）：
    //     查该 product_name 下正常状态包的 series_name，与 rows 的 campaign 求交集
    //       · 有交集                          → 放行
    //       · 无交集 且 无养户行(is_yanghu)    → 400 "产品选择有误！..."
    //       · 无交集 但有养户行                → 放行，响应附 warning 字段（前端弹警告）
    //   通过后：非养户行入库 ad_reports（同键覆盖）→ 后台线程写 Sheets
    @PostMapping("/update-zuobiao")
    public ApiResponse<UpdateZuobiaoResponse> updateZuobiao(
            @AuthenticationPrincipal UserPrincipal principal,
            @Valid @RequestBody UpdateZuobiaoRequest req) {
        return ApiResponse.ok(sheetsService.updateZuobiao(principal.getUserId(), req));
    }

    // GET /api/google-sheets/sync-status — 查询指定产品 Sheets 同步失败记录（含行数据）
    // POST /api/google-sheets/retry-sync — 手动重试做表数据 Sheets 同步
    // GET /api/google-sheets/status — Google Sheets API 配置状态
    // GET /api/google-sheets/sheets — 读取 spreadsheet 所有 sheet 列表
}
```

产品/包名校验逻辑（Service 层）：

```java
/**
 * 校验产品包系列与数据广告系列是否匹配。
 * @return 匹配/无包返回 null；不匹配但有养户行时返回 warning 文案；不匹配且无养户行时抛 BusinessException。
 */
private String validateProductMatches(String productName, List<ZuobiaoRow> rows) {
    // 1. 查该产品下正常状态的包系列名
    Set<String> pkgNames = packageRepository
        .findSeriesNamesByProductName(productName).stream()
        .map(s -> s == null ? "" : s.trim())
        .filter(s -> !s.isEmpty())
        .collect(Collectors.toSet());
    if (pkgNames.isEmpty()) {
        return null;  // 产品无包，跳过校验
    }
    // 2. 取数据中的广告系列名，求交集
    Set<String> campaigns = rows.stream()
        .map(r -> r.getCampaign() == null ? "" : r.getCampaign().trim())
        .filter(s -> !s.isEmpty())
        .collect(Collectors.toSet());
    Set<String> matched = new HashSet<>(pkgNames);
    matched.retainAll(campaigns);
    if (!matched.isEmpty()) {
        return null;  // 有交集，放行
    }
    // 3. 无交集 → 看是否含养户行
    boolean hasYanghu = rows.stream().anyMatch(ZuobiaoRow::isYanghu);
    if (!hasYanghu) {
        throw new BusinessException(
            "产品选择有误！「" + productName + "」的包系列与数据中的广告系列不匹配，请重新选择产品。");
    }
    // 4. 有养户行但非养户行不匹配 → 放行并返回警告
    return "⚠️ 产品「" + productName + "」的包系列与数据中的非养户广告系列不匹配，请确认产品选择是否正确。";
}
```

> **说明（v1.9 新增）**：此校验在 Python 位于 `main.py` 的 `google_sheets_update_zuobiao` 接口层
> （不在 `google_sheets_service.upsert_zuobiao` 服务函数内），迁移文档此前未记录，极易遗漏。
> 三种场景行为对照：
>
> | 场景 | 行为 |
> |------|------|
> | 非养户行与包系列有交集 | 正常放行 |
> | 无交集 + 无养户行 | 阻断，400 "产品选择有误！..." |
> | 无交集 + 有养户行 | 放行 + 响应 `warning` 字段（前端 8 秒警告弹窗，可关闭） |
>
> 前端 `ToolkitView.vue` 收到 `warning` 后调用 `ElMessage.warning({ duration: 8000, showClose: true })`。

### 6.3 完整 Controller 清单

| Controller | 路由前缀 | 接口数 | 认证 |
|---|---|---|---|
| `AuthController` | `/api/auth/*` | 12 | 混合 |
| `FbBmController` | `/api/fb/bms/*` | 7 | JWT + FB |
| `FbAccountController` | `/api/fb/accounts/*` | 8 | JWT + FB |
| `FbProductController` | `/api/fb/products/*` | 8 | JWT + FB |
| `FbLineController` | `/api/fb/lines/*` | 3 | JWT + FB |
| `FbPixelBmController` | `/api/fb/pixel-bms/*` | 5 | JWT + FB |
| `FbPixelController` | `/api/fb/pixels/*` | 5 | JWT + FB |
| `FbExtractController` | `/api/fb/extract/*` | 3 | JWT + FB |
| `FbReportController` | `/api/fb/reports/*` | 9 | JWT + FB |
| `FbUserController` | `/api/fb/users` | 1 | JWT + FB |
| `ProductController` | `/api/products/*` | 18 | JWT + 混合 |
| `AccountController` | `/api/accounts/*` | 21 | JWT |
| `MccController` | `/api/mcc/*` | 8 | JWT |
| `RechargeController` | `/api/recharge/*` | 5 | JWT |
| `AdReportController` | `/api/ad-reports/*` | 17 | JWT |
| `YoutubeController` | `/api/youtube/*` | 16 | JWT |
| `ScrapeController` | `/api/scrape/*` | 5 | JWT |
| `VideoController` | `/api/video/*`, `/api/audio*` | 16 | 混合 |
| `FontController` | `/api/fonts/*` | 7 | 无 |
| `CopywritingController` | `/api/copywriting/*` | 5 | JWT |
| `AdminUserController` | `/api/admin/users/*` | 8 | JWT + Admin |
| `AdminDataController` | `/api/admin/data/*` | 2 | Admin |
| `AdminTriggerController` | `/api/admin/trigger-*` | 2 | Developer |
| `ConfigController` | `/api/config/*` | 6 | JWT |
| `SettingsController` | `/api/settings/*` | 2 | JWT |
| `OptionController` | `/api/{agents\|statuses\|mcc-levels\|sales-persons\|regions}/*` | 20 | JWT |
| `DataController` | `/api/data/*` | 3 | JWT |
| `AuditController` | `/api/audit-log/*` | 2 | JWT |
| `DelistController` | `/api/delist/*` | 2 | JWT |
| `UtilityController` | `/api/browse-*`, `/api/translate` | 5 | 混合 |
| `GoogleSheetsController` | `/api/google-sheets/*` | 4 | JWT |
| `GoogleAdsController` | `/api/google-ads/*` | 2 | 无 |
| **合计** | | **240** | |

> **说明（v1.10 新增）**：`DelistController` 的 `delist/pending` 返回**产品聚合**结构
> （`{ product_id, product_name, series_names[], package_ids[], type, reminder_count }`），
> `delist/dismiss` 入参为 `package_ids[]`（批量）。对应 Python 端 `delist_pending` / `delist_dismiss`
> 已同步改造为按产品聚合/批量关闭；前端 `App.vue` 按产品统一弹窗、`ProductPanel.vue` 支持多包跳转高亮。

---

## 7. 认证与安全

### 7.1 整体架构

```
                    ┌─────────────────────┐
                    │   SecurityFilterChain │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────▼────────┐ ┌────▼─────┐ ┌───────▼───────┐
     │ JwtAuthFilter    │ │ CORS     │ │ PlatformGuard │
     │ (解析JWT,设置    │ │ Filter   │ │ Filter        │
     │  SecurityContext) │ │          │ │ (GG-only前缀  │
     └────────┬────────┘ └──────────┘ │  拦截FB用户)  │
              │                       └───────────────┘
     ┌────────▼────────┐
     │ Controller       │
     │ @Authentication  │
     │ Principal +      │
     │ @FbPlatformReq   │
     │ @AdminRequired   │
     └─────────────────┘
```

### 7.2 Spring Security 配置

```java
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    private final JwtTokenProvider jwtTokenProvider;

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .csrf(CsrfConfigurer::disable)
            .cors(Customizer.withDefaults())
            .sessionManagement(sm ->
                sm.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                // 公开路由
                .requestMatchers(
                    "/api/auth/login",
                    "/api/auth/register",
                    "/api/auth/refresh"
                ).permitAll()
                .requestMatchers(HttpMethod.GET,
                    "/api/products/{pid}/detail",
                    "/api/image",
                    "/api/video/download",
                    "/api/video/progress",
                    "/api/fonts/**",
                    "/api/font-file",
                    "/api/health"
                ).permitAll()
                // 其余全部需要认证
                .anyRequest().authenticated()
            )
            .addFilterBefore(
                new JwtAuthenticationFilter(jwtTokenProvider),
                UsernamePasswordAuthenticationFilter.class)
            .addFilterAfter(
                new PlatformGuardFilter(),
                JwtAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Value("${cors.allowed-origins:http://localhost:5173,http://127.0.0.1:5173}")
    private List<String> allowedOrigins;

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOriginPatterns(allowedOrigins);  // 生产环境白名单
        config.setAllowedMethods(List.of("GET","POST","PUT","DELETE","OPTIONS"));
        config.setAllowedHeaders(List.of(
            "Authorization", "Content-Type", "Accept", "X-Requested-With"));
        config.setExposedHeaders(List.of("x-new-access-token"));
        config.setAllowCredentials(true);
        config.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }
}
```

### 7.3 JWT Token 提供者

```java
@Component
public class JwtTokenProvider {

    @Value("${jwt.secret}")
    private String secret;

    @Value("${jwt.access-token-expiration:3600000}") // 1小时
    private long accessTokenExpiration;

    @Value("${jwt.refresh-token-expiration:2592000000}") // 30天
    private long refreshTokenExpiration;

    // 启动时强制校验：禁止使用默认弱密钥
    @PostConstruct
    public void validateSecret() {
        if (secret == null || secret.isBlank() || secret.length() < 32
                || secret.startsWith("your-256-bit-secret")) {
            throw new IllegalStateException(
                "【安全错误】JWT_SECRET 不能使用默认值！请设置环境变量 JWT_SECRET。\n"
                + "生成命令: openssl rand -base64 64");
        }
    }

    private SecretKey getSigningKey() {
        return Keys.hmacShaKeyFor(Decoders.BASE64.decode(secret));
    }

    // 生成 Access Token（含 tokenVersion 支持强制失效）
    public String createAccessToken(Long userId, String role, String platform, int tokenVersion) {
        return Jwts.builder()
            .subject(String.valueOf(userId))
            .claim("role", role)
            .claim("platform", platform)
            .claim("tokenVersion", tokenVersion)
            .issuedAt(new Date())
            .expiration(new Date(System.currentTimeMillis() + accessTokenExpiration))
            .signWith(getSigningKey())
            .compact();
    }

    // 验证 Token（含 tokenVersion 校验）
    public boolean validateToken(String token, int currentTokenVersion) {
        try {
            Claims claims = Jwts.parser().verifyWith(getSigningKey()).build()
                .parseSignedClaims(token).getPayload();
            int tv = claims.get("tokenVersion", Integer.class);
            return tv == currentTokenVersion;
        } catch (JwtException | IllegalArgumentException e) {
            return false;
        }
    }

    public Date getExpiration(String token) {
        return Jwts.parser().verifyWith(getSigningKey()).build()
            .parseSignedClaims(token).getPayload().getExpiration();
    }

    public long getAccessTokenExpiration() { return accessTokenExpiration; }

    // 提取字段
    private Claims getClaims(String token) {
        return Jwts.parser().verifyWith(getSigningKey()).build()
            .parseSignedClaims(token).getPayload();
    }

    public Long getUserId(String token) {
        return Long.parseLong(getClaims(token).getSubject());
    }

    public String getRole(String token) {
        return getClaims(token).get("role", String.class);
    }

    public String getPlatform(String token) {
        return getClaims(token).get("platform", String.class);
    }

    public int getTokenVersion(String token) {
        return getClaims(token).get("tokenVersion", Integer.class);
    }
}
```

### 7.4 JWT 认证过滤器

```java
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final JwtTokenProvider jwtTokenProvider;

    @Override
    protected void doFilterInternal(HttpServletRequest request,
            HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {

        String token = resolveToken(request);

        if (token != null && jwtTokenProvider.validateToken(token)) {
            Long userId = jwtTokenProvider.getUserId(token);
            String role = jwtTokenProvider.getRole(token);
            String platform = jwtTokenProvider.getPlatform(token);

            UserPrincipal principal = new UserPrincipal(userId, role, platform);
            UsernamePasswordAuthenticationToken auth =
                new UsernamePasswordAuthenticationToken(
                    principal, null, getAuthorities(role));

            SecurityContextHolder.getContext().setAuthentication(auth);

            // 滑动过期：仅剩余有效期 < 30% 时才签发新 token
            Date expiration = jwtTokenProvider.getExpiration(token);
            long remaining = expiration.getTime() - System.currentTimeMillis();
            if (remaining < jwtTokenProvider.getAccessTokenExpiration() * 0.3) {
                String newToken = jwtTokenProvider.createAccessToken(
                    userId, role, platform, jwtTokenProvider.getTokenVersion(token));
                response.setHeader("x-new-access-token", newToken);
            }
        }

        chain.doFilter(request, response);
    }

    private String resolveToken(HttpServletRequest request) {
        String bearer = request.getHeader("Authorization");
        if (bearer != null && bearer.startsWith("Bearer ")) {
            return bearer.substring(7);
        }
        return null;
    }

    private Collection<? extends GrantedAuthority> getAuthorities(String role) {
        return List.of(new SimpleGrantedAuthority("ROLE_" + role.toUpperCase()));
    }
}
```

### 7.5 自定义注解

```java
// @FbPlatformRequired — FB 平台 + JWT 认证
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
public @interface FbPlatformRequired {}

// @AdminRequired — 管理员权限
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
public @interface AdminRequired {}

// @DeveloperRequired — 开发者权限
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
public @interface DeveloperRequired {}

// @RejectViewer — 拒绝 observer 角色
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
public @interface RejectViewer {}
```

对应 AOP 切面示例：

```java
@Aspect
@Component
@RequiredArgsConstructor
public class PlatformGuardAspect {

    @Around("@within(fbPlatformRequired) || @annotation(fbPlatformRequired)")
    public Object checkFbPlatform(ProceedingJoinPoint pjp,
            FbPlatformRequired fbPlatformRequired) throws Throwable {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        UserPrincipal principal = (UserPrincipal) auth.getPrincipal();

        if (!principal.isDeveloper() && !"fb".equals(principal.getPlatform())) {
            throw new PlatformForbiddenException("FB platform required");
        }
        return pjp.proceed();
    }
}
```

### 7.6 平台守卫过滤器

```java
public class PlatformGuardFilter extends OncePerRequestFilter {

    // GG 专属路由（FB 用户不能访问）—— AntPathMatcher 防路径绕过
    private static final Set<String> GG_ONLY_PATTERNS = Set.of(
        "/api/ad-reports/**", "/api/accounts/**", "/api/mcc/**",
        "/api/products/**", "/api/scrape/**", "/api/video/**",
        "/api/youtube/**", "/api/settings/**", "/api/google-sheets/**"
    );
    private final AntPathMatcher pathMatcher = new AntPathMatcher();

    @Override
    protected void doFilterInternal(HttpServletRequest request,
            HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {

        String path = request.getRequestURI();

        // 用 AntPathMatcher 而非 startsWith 防路径遍历绕过
        boolean isGgOnly = GG_ONLY_PATTERNS.stream()
            .anyMatch(p -> pathMatcher.match(p, path));
        if (!isGgOnly) {
            chain.doFilter(request, response);
            return;
        }

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof UserPrincipal principal) {
            if (!principal.isDeveloper() && "fb".equals(principal.getPlatform())) {
                response.setStatus(403);
                response.setContentType("application/json;charset=UTF-8");
                response.getWriter().write(
                    "{\"success\":false,\"error\":\"Platform access denied\"}");
                return;
            }
        }

        chain.doFilter(request, response);
    }
}
```

---

## 8. 业务服务层设计

### 8.1 Google Sheets 服务

这是最核心的业务服务，需要完整保留 Python 版本的 upsert 逻辑。

```java
@Service
@Slf4j
public class GoogleSheetsService {

    @Value("${google.sheets.credentials-path}")
    private String credentialsPath;

    private static final String APPLICATION_NAME = "GG-Server";
    private static final List<String> SCOPES =
        List.of("https://www.googleapis.com/auth/spreadsheets");

    private Sheets sheetsService;

    @PostConstruct
    public void init() throws Exception {
        GoogleCredentials credentials = GoogleCredentials
            .fromStream(new FileInputStream(credentialsPath))
            .createScoped(SCOPES);
        // 使用服务账号时不需要 refresh token

        this.sheetsService = new Sheets.Builder(
            GoogleNetHttpTransport.newTrustedTransport(),
            JacksonFactory.getDefaultInstance(),
            new HttpCredentialsAdapter(credentials))
            .setApplicationName(APPLICATION_NAME)
            .build();
    }

    /**
     * GG 做表数据 upsert（对应 Python upsert_zuobiao）
     * 列映射 A-N（14列）：日期|运营|客户名称|商务|投放国家|渠道号|
     *   系列名|包名|账户ID|素材图|落地页|账号消耗(¥)|广告系列
     * M = F*L (利润), N = F-K+M (客户实际消耗)
     */
    public UpsertResult upsertZuobiao(String spreadsheetId, List<ZuobiaoRow> rows,
            String productName, String region, String reportDate,
            String salesPerson, Double agencyRatio, String operatorName) {
        try {
            // 1. 获取表格信息
            Spreadsheet spreadsheet = sheetsService.spreadsheets()
                .get(spreadsheetId).execute();

            String sheetName = spreadsheet.getSheets().get(0)
                .getProperties().getTitle();

            // 2. 读取现有数据 A-N
            ValueRange existingData = sheetsService.spreadsheets().values()
                .get(spreadsheetId, "'" + sheetName + "'!A:N").execute();
            List<List<Object>> existing = existingData.getValues();
            if (existing == null) existing = new ArrayList<>();

            // 3. 找最后一行（只看 A 列日期，不看其他列）
            int lastRow = 0;
            String lastDate = "";
            for (int i = existing.size() - 1; i >= 0; i--) {
                List<Object> row = existing.get(i);
                if (!row.isEmpty() && row.get(0) != null
                        && !row.get(0).toString().isBlank()) {
                    lastRow = i + 1;
                    lastDate = row.get(0).toString().trim();
                    break;
                }
            }

            // 4. 新日期空一行
            if (reportDate != null && !reportDate.isEmpty()
                    && !lastDate.isEmpty() && !lastDate.equals(reportDate)) {
                lastRow++;
            }

            // 5. 构建去重索引: (A=日期, C=客户名称, I=账户ID, M=广告系列)
            Map<String, Integer> existingMap = new HashMap<>();
            for (int i = 0; i < existing.size(); i++) {
                List<Object> row = existing.get(i);
                if (row.size() > 8 && row.get(0) != null && row.get(8) != null) {
                    String key = row.get(0).toString().trim() + "|"
                        + (row.size() > 8 ? row.get(8).toString().trim() : "");
                    existingMap.put(key, i);
                }
            }

            // 6. 自动扩容
            int maxRows = spreadsheet.getSheets().get(0)
                .getProperties().getGridProperties().getRowCount();
            int needed = lastRow + rows.size() + 1;
            if (needed > maxRows) {
                // batchUpdate appendDimension
                Request request = new Request()
                    .setAppendDimension(new AppendDimensionRequest()
                        .setSheetId(spreadsheet.getSheets().get(0)
                            .getProperties().getSheetId())
                        .setDimension("ROWS")
                        .setLength(needed - maxRows + 100));
                sheetsService.spreadsheets().batchUpdate(spreadsheetId,
                    new BatchUpdateSpreadsheetRequest()
                        .setRequests(List.of(request))).execute();
            }

            // 7. 构建批量更新
            List<Request> updateRequests = new ArrayList<>();
            List<List<Object>> newRowUpdates = new ArrayList<>();
            int updated = 0, appended = 0;

            for (ZuobiaoRow zuobiaoRow : rows) {
                List<Object> rowData = zuobiaoRow.toSheetRow(); // 14列
                String dedupKey = reportDate + "|" + zuobiaoRow.getAccountId();

                if (existingMap.containsKey(dedupKey)) {
                    int rowIdx = existingMap.get(dedupKey);
                    // 更新已有行
                    updateRequests.add(buildUpdateRequest(sheetName, rowIdx + 1, rowData));
                    updated++;
                } else {
                    lastRow++;
                    updateRequests.add(buildUpdateRequest(sheetName, lastRow, rowData));
                    appended++;
                }
            }

            // 8. 批量执行更新
            if (!updateRequests.isEmpty()) {
                sheetsService.spreadsheets().values().batchUpdate(spreadsheetId,
                    new BatchUpdateValuesRequest()
                        .setValueInputOption("USER_ENTERED")
                        .setData(updateRequests.stream()
                            .map(r -> new ValueRange()
                                .setRange(r.getRange())
                                .setValues(List.of(r.getValues())))
                            .toList()))
                    .execute();
            }

            return UpsertResult.builder()
                .updated(updated).appended(appended)
                .sheetName(sheetName).build();
        } catch (Exception e) {
            log.error("Sheets upsert failed", e);
            throw new BusinessException("Google Sheets 写入失败: " + e.getMessage());
        }
    }

    /**
     * FB 做表数据写入（对应 Python upsert_fb_reports）
     * 列映射 A-L（12列）：日期|运营|账户名称|广告账户ID|账号消耗|
     *   报给客户|客户名称|商务|投放国家|渠道号|平台实际|代投比例
     */
    public UpsertResult upsertFbReports(Long userId, String productName,
            String lineName, String reportDate, List<FbReportRow> records) {
        // 逻辑同上，区别：
        //   1. 读取用户 Sheets 配置（按 platform 选 key）
        //   2. 按 用户名+月份 匹配表格
        //   3. 去重键：(日期, 账户ID, 产品名, 线名)
        //   4. 12列输出
        //   详略（代码结构与 upsertZuobiao 类似）
    }
    /**
     * 「我的看板」Sheet 双向同步（对应 Python accounts_sync_from_sheet + update_cell_by_account_id）
     *
     * 我的看板列结构（A-H，8列）：
     *   A=运营, B=账户ID, C=所属渠道, D=国家, E=时区, F=备注, G=是否封户, H=是否解绑
     *
     * Sheet→系统 (dry_run):
     *   1. 读取 A:H 列
     *   2. 门禁校验：A列运营 == 当前用户 display_name
     *   3. 跳过 H列="解绑" 的账户
     *   4. 按 B列 account_id 匹配系统账户（含软删除）
     *   5. 系统没有 → to_create；系统有+未删除 → 根据 G列封户值建议状态；
     *      系统有+已删除 → 跳过
     *
     * Sheet→系统 (execute):
     *   1. 创建新账户（name/MCC留空，状态默认"存活"，代理自动创建）
     *   2. 执行确认后的状态变更（不触发清账逻辑，同步 death_date）
     *
     * 系统→Sheet (execute后自动):
     *   1. 重新查询所有匹配账户最新状态（含 deleted_at）
     *   2. F列(备注) ← 系统状态
     *   3. H列(是否解绑) ← 已删除写"解绑"，未删除清空
     *
     * 系统→Sheet (状态变更时自动):
     *   accounts_update / batch_update 状态变更时，后台线程更新 F列(备注)
     *   accounts_delete 时后台写 H列"解绑"
     *   accounts_restore 时后台清 H列
     */
    public SyncResult syncFromSheet(Long userId, SyncRequest req) {
        // dry_run: 比对返回 diff
        // execute: 执行 + commit + 系统→Sheet 同步
    }

    /** 按 account_id 更新 Sheet 指定列 */
    public void updateCellByAccountId(String spreadsheetId, String sheetName,
            String accountId, String value, int colIndex) {
        // colIndex: 5=F列(备注), 7=H列(是否解绑)
    }

    /** 通用读取 Sheet 指定范围 */
    public List<List<Object>> readSheetValues(String spreadsheetId,
            String sheetName, String range) {
        // 返回二维列表
    }
}
```

### 8.2 FB 数据提取服务

```java
@Service
@RequiredArgsConstructor
@Slf4j
public class FbExtractService {

    private final FbAdReportRepository fbAdReportRepository;
    private final GoogleSheetsService sheetsService;
    private final JdbcTemplate jdbc;

    /**
     * 解析提取文本 → 结构化数据（含尾部校验）
     * 对应 Python: POST /api/fb/extract/parse
     *
     * 解析流程：
     * 1. 找到"数据透视表"~"总成效"范围，动态分组提取每行账户数据
     * 2. "总成效"之后不再丢弃，改为提取校验数据：
     *    - 正则 "已显示\d+/(\d+)行" 提取声明总行数
     *    - 收集 $ 金额取最大值，验证其后紧跟"总花费"作为声明总消耗
     * 3. 返回 ParseResult{data, warnings, groupSize, validation}
     */
    public ParseResult parseExtract(String text, boolean sorted) {
        List<String> lines = List.of(text.split("\\n"));

        // 找到"数据透视表"~"总成效"范围
        int startIdx = -1, endIdx = -1;
        for (int i = 0; i < lines.size(); i++) {
            String line = lines.get(i).trim();
            if (line.contains("数据透视表") && startIdx < 0) startIdx = i + 1;
            if (line.contains("总成效") && endIdx < 0) endIdx = i;
        }
        if (startIdx < 0) throw new BusinessException("未找到\"数据透视表\"标记");
        if (endIdx < 0) endIdx = lines.size();

        // 解析尾部校验数据（"总成效"之后的内容）
        List<String> tailLines = lines.subList(endIdx, lines.size());
        int declaredRows = 0;
        double declaredSpend = 0.0;

        Pattern rowCountPattern = Pattern.compile("已显示\\d+/(\\d+)行");
        for (int i = 0; i < tailLines.size(); i++) {
            String line = tailLines.get(i).trim();
            Matcher m = rowCountPattern.matcher(line);
            if (m.find()) declaredRows = Integer.parseInt(m.group(1));

            if (line.startsWith("$")) {
                double amt = Double.parseDouble(line.replace("$", "").replace(",", ""));
                // 检查该行或后两行是否包含"总花费"
                String nearby = line + " " + String.join(" ",
                    tailLines.subList(Math.min(i + 1, tailLines.size()),
                                      Math.min(i + 3, tailLines.size())));
                if (nearby.contains("总花费")) {
                    declaredSpend = Math.max(declaredSpend, amt);
                }
            }
        }

        // ... 动态分组、提取每组 account_name/account_id/cost 等（与 Python 一致）

        // === 每组提取后的过滤逻辑（2026-08-01 新增） ===
        // 1. 去重：收集到的 $ 金额用 distinct 去重，相同值视为重复数据只保留一个
        // 2. 回流过滤：去重后若所有 $ 金额均为 0，跳过该行（回流数据：有账号名+ID但无实际消耗）
        // 3. 警告：去重后才判断 len > 2，避免重复 $ 金额导致误报警告

        List<FbReportRow> data = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        // ... 构建 data 和 warnings

        // 构建校验对象
        double extractedSpend = data.stream().mapToDouble(FbReportRow::getCost).sum();
        ValidationResult validation = ValidationResult.builder()
            .declaredRows(declaredRows)
            .extractedRows(data.size())
            .declaredSpend(Math.round(declaredSpend * 100.0) / 100.0)
            .extractedSpend(Math.round(extractedSpend * 100.0) / 100.0)
            .build();

        return ParseResult.builder()
            .data(data).warnings(warnings).groupSize(groups.get(0).size())
            .validation(validation)
            .build();
    }

    /**
     * 检查重复
     * 对应 Python: POST /api/fb/extract/check-duplicates
     */
    public DuplicateResult checkDuplicates(String productName, String lineName,
            String reportDate, List<FbReportRow> records) {
        // 按 (user_id, product_name, line_name, account_id, report_date)
        // 查询已有记录，返回重复项
    }

    /**
     * 保存提取数据（含异步写 Sheets）
     * 对应 Python: POST /api/fb/extract/save
     */
    @Transactional
    public int saveExtract(Long userId, String productName, String lineName,
            String reportDate, List<FbReportRow> records) {
        // 1. 写入 MySQL（fb_ad_reports 表 upsert）
        int saved = 0;
        for (FbReportRow rec : records) {
            int updated = jdbc.update("""
                INSERT INTO fb_ad_reports
                  (user_id, product_name, line_name, report_date,
                   account_name, account_id, cost, impressions, clicks,
                   registrations, purchases, cost_per_purchase)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON DUPLICATE KEY UPDATE
                  account_name=VALUES(account_name), cost=VALUES(cost),
                  impressions=VALUES(impressions), clicks=VALUES(clicks),
                  registrations=VALUES(registrations),
                  purchases=VALUES(purchases),
                  cost_per_purchase=VALUES(cost_per_purchase),
                  updated_at=CURRENT_TIMESTAMP
                """,
                userId, productName, lineName, reportDate,
                rec.getAccountName(), rec.getAccountId(), rec.getCost(),
                rec.getImpressions(), rec.getClicks(),
                rec.getRegistrations(), rec.getPurchases(),
                rec.getCostPerPurchase());
            saved += updated;
        }

        // 2. 先持久化 Sheets 同步日志
        SheetsSyncLog syncLog = sheetsSyncLogRepository.save(
            SheetsSyncLog.builder()
                .userId(userId).productName(productName)
                .status("pending").rowsJson(toJson(records)).build());

        // 3. 异步写 Sheets（用 Spring 管理的业务线程池，不用 CompletableFuture）
        taskExecutor.execute(() -> {
            try {
                sheetsService.upsertFbReports(userId, productName,
                    lineName, reportDate, records);
                syncLog.setStatus("synced");
                sheetsSyncLogRepository.save(syncLog);
            } catch (Exception e) {
                log.error("[FB-Sheets] 写入失败: {}", e.getMessage());
                syncLog.setStatus("failed");
                syncLog.setErrorMsg(e.getMessage().substring(0, 500));
                syncLog.setRetryCount(syncLog.getRetryCount() + 1);
                sheetsSyncLogRepository.save(syncLog);
            }
        });

        return saved;
    }
}
```

### 8.3 其他核心服务设计概要

| 服务 | 关键功能 | Spring 技术 |
|------|---------|------------|
| **AccountService** | GG 账户 CRUD、批量操作、Sheet 同步 | JPA + @Transactional |
| **ProductService** | GG 产品 CRUD、包管理、在跑人员 | JPA |
| **MccService** | MCC CRUD、层级管理 | JPA |
| **RechargeService** | 充值提交、批量充值、Sheet 写入 | JPA + @Async |
| **AdReportService** | 报告 CRUD、去重、分析、AI 对话、CSV 导出 | JPA + RestTemplate |
| **YoutubeService** | 视频导入/列表/编辑、消费追踪 | JPA |
| **ScrapeService** | Google Play 截图抓取 | Jsoup |
| **VideoService** | AI 视频生成、FFmpeg 合成 | ProcessBuilder + @Async |
| **AuthService** | 登录/注册、JWT 签发、角色管理 | BCrypt + jjwt |
| **DataImportExportService** | 数据导入导出、备份恢复 | Jackson |
| **DelistService** | 掉包检测、通知 | @Scheduled + RestTemplate |
| **NotificationService** | 邮件 + Telegram 通知 | JavaMailSender + RestTemplate |
| **FbService** | FB 全平台业务（BM/账户/产品/Pixel） | JPA + @Transactional |
| **OptionService** | 选项表 CRUD | JPA |

### 8.4 账户状态变更清账（v1.4 加固）

**需求**: GG 账户从"存活"变更为非存活状态（如"死亡"）时，自动在 `recharge_records` 表中插入一条 `amount='清'` 的清算记录，并同步到 Google Sheets 充值表。

**现存问题**: 原逻辑依赖 `status_changed_date` 字段判断是否有"存活期间"的充值 → 该字段在账户创建时未设置，且可能因各种路径（Sheet 同步、直接改库等）不准确，导致清账被跳过。

**兜底方案**: 改为**直接查数据状态**，不依赖任何外部字段：

```sql
SELECT COUNT(*) FROM recharge_records r1
WHERE r1.account_id = ? AND r1.amount != '清'
AND NOT EXISTS (
    SELECT 1 FROM recharge_records r2
    WHERE r2.account_id = r1.account_id
      AND r2.amount = '清'
      AND r2.created_at > r1.created_at
)
```

逻辑：
1. 找到该账户下所有非"清"的充值记录
2. 检查每条充值之后是否存在"清"记录（`amount='清' AND created_at > 充值时间`）
3. 如果有未清的充值 → `need_clear = true` → 插入清账记录
4. **防重复**: `NOT EXISTS` 子查询天然阻止——已有"清"记录的充值不会被重复计算

**涉及位置**（Python → Java 迁移对照）:

| Python | Java | 说明 |
|--------|------|------|
| `accounts_update()` (单账户更新) | `AccountController.update()` → `AccountService` | 相同兜底 SQL |
| `accounts_batch_update()` (批量更新) | `AccountController.batchUpdate()` → `AccountService` | 相同兜底 SQL |

**与旧逻辑对比**:

| | 旧逻辑 | 新逻辑 |
|---|---|---|
| 判断依据 | `status_changed_date` | 充值表实际数据 |
| 依赖字段 | 必须正确维护 | 无外部依赖 |
| 重复清账 | 依赖时间比较 | NOT EXISTS 子查询天然防重复 |
| Sheet 同步路径 | 明确跳过 | 同样跳过（该路径不改状态） |

### 8.5 定时任务

```java
@Component
@Slf4j
public class ScheduledTasks {

    private final DelistChecker delistChecker;
    private final DataImportExportService dataService;

    // 每周清理（对应 Python _start_weekly_cleanup）
    @Scheduled(cron = "${scheduler.weekly-cleanup:0 0 2 * * SUN}")
    public void weeklyCleanup() {
        log.info("执行每周清理...");
        // 清理过期软删除记录等
    }

    // 掉包检测（可配置间隔）
    @Scheduled(cron = "${scheduler.delist-check:0 0 9 * * *}")
    public void checkDelist() {
        log.info("执行掉包检测...");
        delistChecker.checkAllActiveProducts();
    }
}
```

### 8.6 异步配置

```java
@Configuration
@EnableAsync
public class AsyncConfig implements AsyncConfigurer {

    @Bean("ggAsyncExecutor")
    public Executor taskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(5);
        executor.setMaxPoolSize(20);
        executor.setQueueCapacity(100);
        executor.setThreadNamePrefix("gg-async-");
        executor.setRejectedExecutionHandler(
            new ThreadPoolExecutor.CallerRunsPolicy());
        executor.initialize();
        return executor;
    }

    @Override
    public Executor getAsyncExecutor() {
        return taskExecutor();
    }

    @Override
    public AsyncUncaughtExceptionHandler getAsyncUncaughtExceptionHandler() {
        return (ex, method, params) ->
            log.error("Async method {} failed", method.getName(), ex);
    }
}
```

> **使用规范**: `@Async` 必须指定线程池名 `@Async("ggAsyncExecutor")`，禁止无参 `@Async` 或 `CompletableFuture.runAsync()`。

---

## 9. 外部集成

### 9.1 Google Sheets API

```yaml
# application.yml
google:
  sheets:
    credentials-path: ${GOOGLE_SHEETS_CREDENTIALS_PATH:config/service-account.json}
    application-name: GG-Server
```

实现类：`GoogleSheetsService`（详见 8.1 节）

### 9.2 Google Ads API

```java
@Service
@Slf4j
public class GoogleAdsService {

    /**
     * 列出经理账户下所有子账户
     */
    public List<String> listAccounts(GoogleAdsCredentials creds) {
        GoogleAdsClient client = buildClient(creds);
        // 使用 CustomerServiceClient 列出账户
        // ...
    }

    /**
     * 拉取广告系列报告
     */
    public List<CampaignReportRow> fetchCampaignReport(
            GoogleAdsCredentials creds, String accountId,
            String startDate, String endDate) {
        GoogleAdsClient client = buildClient(creds);
        String query = """
            SELECT campaign.name, metrics.cost_micros,
                   metrics.impressions, metrics.clicks,
                   metrics.ctr, metrics.conversions, metrics.cost_per_conversion
            FROM campaign
            WHERE segments.date BETWEEN '%s' AND '%s'
            """.formatted(startDate, endDate);
        // 执行 GAQL 查询
        // ...
    }

    private GoogleAdsClient buildClient(GoogleAdsCredentials creds) {
        return GoogleAdsClient.newBuilder()
            .setClientId(creds.getClientId())
            .setClientSecret(creds.getClientSecret())
            .setRefreshToken(creds.getRefreshToken())
            .setDeveloperToken(creds.getDeveloperToken())
            .setLoginCustomerId(Long.parseLong(creds.getManagerId()))
            .build();
    }
}
```

### 9.3 AI 视频生成

使用 **策略模式** 支持 5 个 Provider：

```java
// 接口
public interface AiVideoProvider {
    String generateVideo(String imagePath, int duration, String apiKey);
    String getProviderName();
}

// 豆包实现
@Component
public class DoubaoProvider implements AiVideoProvider {
    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${ai.doubao.endpoint:https://ark.cn-beijing.volces.com/api/v3}")
    private String endpoint;

    @Override
    public String generateVideo(String imagePath, int duration, String apiKey) {
        // 1. 图片编码 base64
        // 2. POST 提交任务
        // 3. 轮询直到完成
        // 4. 下载 MP4
    }
}

// 工厂
@Component
@RequiredArgsConstructor
public class AiVideoProviderFactory {
    private final List<AiVideoProvider> providers;

    public AiVideoProvider getProvider(String name) {
        return providers.stream()
            .filter(p -> p.getProviderName().equalsIgnoreCase(name))
            .findFirst()
            .orElseThrow(() -> new BusinessException("Unknown provider: " + name));
    }
}
```

### 9.4 FFmpeg 视频处理

```java
@Component
@Slf4j
public class FfmpegService {

    @Value("${ffmpeg.path:ffmpeg}")
    private String ffmpegPath;

    @Value("${ffprobe.path:ffprobe}")
    private String ffprobePath;

    public String generateVideo(VideoTaskParams params) throws Exception {
        List<String> command = buildFfmpegCommand(params);

        ProcessBuilder pb = new ProcessBuilder(command);
        pb.redirectErrorStream(true);

        Process process = pb.start();

        // 有界输出读取（防 OOM）
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int total = 0, maxBytes = 10 * 1024 * 1024;
        try (InputStream is = process.getInputStream()) {
            int n;
            while ((n = is.read(buf)) != -1) {
                total += n;
                if (total > maxBytes) { process.destroyForcibly(); throw new BusinessException("FFmpeg输出超限"); }
                out.write(buf, 0, n);
            }
        }

        // 5 分钟超时
        if (!process.waitFor(300, TimeUnit.SECONDS)) {
            process.destroyForcibly();
            throw new BusinessException("FFmpeg 超时（5分钟）");
        }

        if (process.exitValue() != 0)
            throw new BusinessException("FFmpeg 失败: " + out.toString("UTF-8"));

        return params.getOutputPath();
    }

    // 并发限制：最多 2 个 FFmpeg 进程
    private final Semaphore ffmpegSemaphore = new Semaphore(2);

    public String generateVideoWithLimit(VideoTaskParams params) throws Exception {
        if (!ffmpegSemaphore.tryAcquire(5, TimeUnit.MINUTES))
            throw new BusinessException("FFmpeg 队列已满");
        try { return generateVideo(params); }
        finally { ffmpegSemaphore.release(); }
    }

    private List<String> buildFfmpegCommand(VideoTaskParams params) {
        // 构建完整 FFmpeg 滤镜链命令
        // 背景层 + 图片 xfade + Logo overlay + 文案 drawtext + 音频
        // ...
    }
}
```

### 9.5 邮件发送

```java
@Service
@RequiredArgsConstructor
public class EmailSender {

    private final JavaMailSender mailSender;

    @Value("${spring.mail.username}")
    private String fromAddress;

    @Async
    public void sendDelistNotification(List<String> recipients,
            PackageInfo pkgInfo) {
        try {
            MimeMessage message = mailSender.createMimeMessage();
            MimeMessageHelper helper = new MimeMessageHelper(message, "UTF-8");

            helper.setFrom(fromAddress, "GG-Server");
            helper.setSubject("[GG-Server] 检测到包掉包 - " + pkgInfo.getPackageName());
            helper.setText(buildDelistEmailBody(pkgInfo), false);
            helper.setTo(recipients.toArray(new String[0]));

            mailSender.send(message);
            log.info("掉包邮件已发送: {} → {}", pkgInfo.getPackageName(), recipients);
        } catch (Exception e) {
            log.error("发送邮件失败", e);
        }
    }
}
```

### 9.6 Telegram 通知

```java
@Service
@Slf4j
public class TelegramSender {

    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${notification.telegram.bot-token}")
    private String botToken;

    @Value("${notification.telegram.chat-id}")
    private String chatId;

    // 产品级掉包通知：一个产品一条消息，展示产品名 + 多个系列名（不展示包名/链接）
    @Async
    public void sendProductDelistNotification(String productName,
            List<String> seriesNames, List<String> usernames) {
        String text = buildProductHtmlMessage(productName, seriesNames, usernames);
        String url = "https://api.telegram.org/bot" + botToken + "/sendMessage";

        Map<String, Object> body = Map.of(
            "chat_id", chatId,
            "text", text,
            "parse_mode", "HTML",
            "disable_web_page_preview", true
        );

        try {
            restTemplate.postForEntity(url, body, String.class);
            log.info("Telegram 产品级掉包通知已发送: {}", productName);
        } catch (Exception e) {
            log.error("Telegram 发送失败", e);
        }
    }

    private String buildProductHtmlMessage(String productName, List<String> seriesNames,
            List<String> usernames) {
        StringBuilder sb = new StringBuilder("<b>【GG-Server 掉包通知】</b>\n");
        if (!usernames.isEmpty()) {
            sb.append("\n").append(usernames.stream()
                .map(u -> "@" + u).collect(Collectors.joining(" ")));
        }
        sb.append("\n<b>产品：</b>").append(escapeHtml(productName)).append("\n");
        sb.append("<b>掉包系列：</b>\n");
        for (String sn : seriesNames) {
            sb.append("· ").append(escapeHtml(sn)).append("\n");
        }
        sb.append("\n该产品的多个包已被下架，请尽快将包状态设置为\"掉包\"。");
        return sb.toString();
    }
}
```

> **说明（v1.10 新增）**：对应 Python `telegram_sender.py` 的 `send_product_delist_notification`，消息不再包含包名与链接。

### 9.7 Google Play 抓取 (Jsoup)

```java
@Service
public class ScrapeService {

    public ScrapeResult scrapeImages(String url) throws IOException {
        Document doc = Jsoup.connect(url)
            .userAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
                "AppleWebKit/537.36 Chrome/120.0.0.0")
            .timeout(30000)
            .get();

        // 提取 <c-wiz jsrenderer='UZStuc'> 下所有 <img>
        Element cWiz = doc.selectFirst("c-wiz[jsrenderer=UZStuc]");
        List<String> imageUrls = new ArrayList<>();
        if (cWiz != null) {
            for (Element img : cWiz.select("img")) {
                String src = img.attr("src");
                if (src.contains("=w")) {
                    src = src.replaceAll("=w\\d+-h\\d+", "=w1200-h1200");
                }
                imageUrls.add(src);
            }
        }

        return new ScrapeResult(imageUrls.stream().distinct().toList());
    }

    public String scrapeLogo(String url) throws IOException {
        Document doc = Jsoup.connect(url)
            .userAgent("...").timeout(30000).get();

        Element logoDiv = doc.selectFirst("div.Mqg6jb.Mhrnjf");
        if (logoDiv != null) {
            Element img = logoDiv.selectFirst("img");
            if (img != null) return img.attr("src");
        }
        return null;
    }
}
```

---

## 10. 配置管理

### 10.1 application.yml 主配置

```yaml
server:
  port: ${SERVER_PORT:5001}

spring:
  application:
    name: lm-server

  # 数据库
  datasource:
    url: jdbc:mysql://${DB_HOST:localhost}:${DB_PORT:3306}/ggserver
          ?useUnicode=true&characterEncoding=utf8mb4
          &serverTimezone=Asia/Shanghai&useSSL=false
    username: ${DB_USERNAME:root}
    password: ${DB_PASSWORD:}
    driver-class-name: com.mysql.cj.jdbc.Driver
    hikari:
      maximum-pool-size: 30        # 30+ 用户 + 异步任务
      minimum-idle: 10
      connection-timeout: 30000
      idle-timeout: 600000
      max-lifetime: 1800000        # 30 min，低于 MySQL wait_timeout
      leak-detection-threshold: 10000

  # JPA
  jpa:
    hibernate:
      ddl-auto: validate  # 生产环境用 validate, 开发用 update
    show-sql: false
    properties:
      hibernate:
        dialect: org.hibernate.dialect.MySQLDialect
        format_sql: true

  # 邮件
  mail:
    host: ${SMTP_HOST:}
    port: ${SMTP_PORT:465}
    username: ${SMTP_USERNAME:}
    password: ${SMTP_PASSWORD:}
    properties:
      mail:
        smtp:
          ssl:
            enable: true
          auth: true

  # 文件上传
  servlet:
    multipart:
      max-file-size: 500MB
      max-request-size: 500MB

  # 缓存
  cache:
    type: caffeine
    caffeine:
      spec: expireAfterWrite=60s

# JWT
jwt:
  secret: ${JWT_SECRET:your-256-bit-secret-key-here-minimum-32-characters}
  access-token-expiration: 3600000       # 1 小时
  refresh-token-expiration: 2592000000   # 30 天

# Google
google:
  sheets:
    credentials-path: ${GOOGLE_SHEETS_CREDENTIALS_PATH:config/service-account.json}

# AI
ai:
  doubao:
    endpoint: https://ark.cn-beijing.volces.com/api/v3
  seedance:
    endpoint: https://api.atlascloud.ai/v1

# FFmpeg
ffmpeg:
  path: ${FFMPEG_PATH:ffmpeg}
  ffprobe-path: ${FFPROBE_PATH:ffprobe}

# 通知
notification:
  telegram:
    bot-token: ${TELEGRAM_BOT_TOKEN:}
    chat-id: ${TELEGRAM_CHAT_ID:}

# 定时任务
scheduler:
  weekly-cleanup: "0 0 2 * * SUN"
  delist-check: "0 0 9 * * *"

# 日志
logging:
  level:
    com.lmserver: INFO
    org.springframework.security: WARN
  file:
    path: ./logs
```

### 10.2 环境变量对照表

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `SERVER_PORT` | 服务端口 | 5001 |
| `DB_HOST` | MySQL 主机 | localhost |
| `DB_PORT` | MySQL 端口 | 3306 |
| `DB_USERNAME` | 数据库用户名 | root |
| `DB_PASSWORD` | 数据库密码 | (空) |
| `JWT_SECRET` | JWT 签名密钥 | (需设置) |
| `GOOGLE_SHEETS_CREDENTIALS_PATH` | Sheets SA 密钥路径 | config/service-account.json |
| `SMTP_HOST/USERNAME/PASSWORD` | SMTP 配置 | (空) |
| `TELEGRAM_BOT_TOKEN/CHAT_ID` | Telegram 配置 | (空) |
| `FFMPEG_PATH` | FFmpeg 可执行文件路径 | ffmpeg |

---

## 11. 部署方案

### 11.1 开发环境

```bash
# 启动 MySQL（Docker）
docker run -d --name ggserver-mysql \
  -e MYSQL_ROOT_PASSWORD=root123 \
  -e MYSQL_DATABASE=ggserver \
  -p 3306:3306 \
  mysql:8.0

# 启动 Spring Boot
mvn spring-boot:run -Dspring-boot.run.profiles=dev

# 前端（不变）
cd frontend && npm run dev
```

### 11.2 生产环境

```bash
# 编译
mvn clean package -DskipTests

# 运行
java -jar target/lm-server-0.1.0-SNAPSHOT.jar \
  --server.port=5001 \
  --spring.datasource.url=jdbc:mysql://localhost:3306/ggserver \
  --spring.datasource.username=gguser \
  --spring.datasource.password=xxx \
  --jwt.secret=<your-secret-key> \
  --google.sheets.credentials-path=/opt/ggserver/config/service-account.json
```

### 11.3 前端代理配置

前端 `vite.config.js` 中的代理目标改为 Spring Boot 端口：

```javascript
// frontend/vite.config.js
server: {
  proxy: {
    '/api': {
      target: 'http://127.0.0.1:5001',  // Spring Boot 端口（不变）
      changeOrigin: true
    }
  }
}
```

### 11.4 Tailscale 部署架构

```
                    Tailscale 网络
    ┌──────────────────┼──────────────────┐
    │                  │                  │
┌───▼───┐       ┌─────▼─────┐      ┌────▼────┐
│ 用户A  │       │  服务器     │      │  用户B   │
│ 浏览器 │──────▶│ SpringBoot │◀─────│ 浏览器   │
│        │       │ :5001      │      │         │
└───────┘       │ MySQL :3306│      └─────────┘
                │ (Docker)   │
                └────────────┘
```

---

## 12. 迁移策略

### 12.1 数据迁移脚本

从 SQLite 导出到 MySQL：

```sql
-- 方案1: 使用工具
-- sqlite3 temp/app.db .dump | python sqlite_to_mysql.py

-- 方案2: 手动导出 CSV 后导入 MySQL
-- 每个表执行：.mode csv, .output table.csv, SELECT * FROM table;
```

关键转换：

| SQLite 值 | MySQL 转换 |
|-----------|-----------|
| `datetime('now','localtime')` | `CURRENT_TIMESTAMP` 由 MySQL 自动处理 |
| `'[]'` (JSON 字符串) | `JSON_ARRAY()` 或 `'[]'`（MySQL JSON 列） |
| `"role != 'developer'"` (SQL拼接) | JPA 参数化查询 |
| 自增 ID 从 1 开始 | 保持原值 (`SET foreign_key_checks=0; INSERT; SET foreign_key_checks=1;`) |

### 12.2 渐进式迁移建议

```
第一阶段（1-2周）：搭架子
├── Spring Boot 项目初始化
├── MySQL 建库建表
├── 数据迁移
├── 认证模块（JWT + Spring Security）
└── 前端代理指向新后端

第二阶段（2-3周）：GG 核心业务
├── 产品管理 → 账户管理 → MCC → 充值
├── 广告报告 → YouTube → 文案
└── 选项管理 → 设置 → 数据导入导出

第三阶段（2-3周）：FB 核心业务
├── BM 管理 → 账户管理 → 产品管理
├── Pixel → 数据提取 → 报告
└── Sheets 写表

第四阶段（1-2周）：辅助功能
├── 视频/AI/FFmpeg
├── 邮件/Telegram
├── 抓取/掉包检测
└── 管理员功能

第五阶段（1周）：测试与上线
├── 接口测试（与前端联调）
├── 性能测试
├── 文档完善
└── 正式切换
```

### 12.3 向后兼容检查清单

- [ ] 所有 236 个 API 路径不变
- [ ] JWT Token 格式保持 `Authorization: Bearer xxx`
- [ ] 响应格式保持 `{success, data/error}`（去掉 Python 的 `success` 外层包裹? → 保留，前端依赖）
- [ ] 分页格式保持 `{items, total, page, size}`
- [ ] 滑动过期 header `x-new-access-token` 保持
- [ ] CORS 配置允许前端跨域
- [ ] Hash Router 兼容（`window.location.hash` 平台检测）
- [ ] 文件上传 multipart/form-data 兼容
- [ ] CSV 导出响应头一致

### 12.4 密码哈希迁移

**问题**：Python 使用 `werkzeug.security.generate_password_hash()`（默认 `pbkdf2:sha256`），
Spring Boot 使用 BCrypt。两种哈希算法不兼容，迁移后现有用户密码无法直接验证。

**方案：兼容登录 + 自动升级**

```java
@Service
public class AuthService {

    // 新密码使用 BCrypt
    public String encodePassword(String rawPassword) {
        return passwordEncoder.encode(rawPassword);
    }

    // 验证密码 — 兼容两种哈希
    public boolean verifyPassword(String rawPassword, User user) {
        String storedHash = user.getPassword();

        // 1. BCrypt 哈希（新格式，$2a$ 开头）
        if (storedHash.startsWith("$2a$") || storedHash.startsWith("$2b$")) {
            boolean match = passwordEncoder.matches(rawPassword, storedHash);
            return match;
        }

        // 2. 旧 pbkdf2:sha256 哈希（werkzeug 格式）
        if (storedHash.startsWith("pbkdf2:sha256:")) {
            boolean match = verifyPbkdf2(rawPassword, storedHash);
            if (match) {
                // 自动升级为 BCrypt
                user.setPassword(passwordEncoder.encode(rawPassword));
                userRepository.save(user);
                log.info("用户 {} 密码已自动升级为 BCrypt", user.getUsername());
            }
            return match;
        }

        return false;
    }

    private boolean verifyPbkdf2(String rawPassword, String hash) {
        // 解析 werkzeug 格式: pbkdf2:sha256:iterations$salt$hash
        // 使用 Java PBKDF2WithHmacSHA256 验证
        String[] parts = hash.split("\\$");
        String[] methodParts = parts[0].split(":");
        int iterations = Integer.parseInt(methodParts[2]);
        String salt = parts[1];
        String expectedHash = parts[2];

        try {
            SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            KeySpec spec = new PBEKeySpec(rawPassword.toCharArray(),
                salt.getBytes(StandardCharsets.UTF_8), iterations, 256);
            byte[] derived = factory.generateSecret(spec).getEncoded();
            // werkzeug 使用 hex 编码
            String derivedHex = HexFormat.of().formatHex(derived);
            return derivedHex.equals(expectedHash);
        } catch (Exception e) {
            log.error("PBKDF2 verification error", e);
            return false;
        }
    }
}
```

**迁移步骤**：
1. 数据迁移时保持 `users.password` 字段原值不变
2. 用户首次登录时自动完成密码升级（透明的，无需用户操作）
3. 经过一段过渡期（如 3 个月）后，可移除旧哈希兼容逻辑

### 12.5 前端兼容性验证矩阵

迁移时必须逐接口验证响应格式，重点检查以下差异点：

| 检查项 | Python 行为 | Java 目标 | 前端读取 |
|--------|------------|----------|---------|
| 分页列表字段名 | `response.items` | `response.items` | `res.data.items` |
| 单对象字段名 | `response.data` | `response.data` | `res.data.data` |
| 纯列表字段名 | `response.data` | `response.data` | `res.data.data` |
| 分页元数据 | `response.total/page/size` | `response.total/page/size` | 顶层读取 |
| 错误字段名 | `response.error` | `response.error` | `res.data.error` |
| JWT 响应头 | `x-new-access-token` | `x-new-access-token` | axios 拦截器 |

> **验证方法**：迁移一个模块后，先用 Postman/Bruno 对比 Python 和 Java 的响应 JSON，
> 确认结构一致后再进行前端联调。

---

## 附录 A: 文件对照表

| Python 文件 | Java 替代 |
|------------|----------|
| `py/main.py` (9652行) | 拆分为 20+ Controller + 15+ Service |
| `py/auth.py` | `security/` + `AuthService` + `UserRepository` |
| `py/database.py` | JPA Entities + 40个 Repository + `schema.sql` |
| `py/routes/auth_routes.py` | `AuthController` |
| `py/routes/fb_routes.py` | 9个 FB Controller |
| `py/routes/decorators.py` | `@FbPlatformRequired`, `@AdminRequired` AOP |
| `py/routes/helpers.py` | `ApiResponse` / `PagedResponse` + `SecurityUtil` + `RepositoryUtil` |
| `py/utils.py` | `util/` 包（`UrlUtil`, `NaturalSortUtil`, `ImageFormatUtil`） |
| `py/google_sheets_service.py` | `GoogleSheetsService` |
| `py/google_ads_service.py` | `GoogleAdsService` |
| `py/ai_service.py` | `AiVideoProvider` 接口 + 5实现 |
| `py/video_processor.py` | `FfmpegService` |
| `py/email_sender.py` | `EmailSender` |
| `py/telegram_sender.py` | `TelegramSender` |
| `py/scraper.py` | `ScrapeService` |
| `py/delist_checker.py` | `DelistChecker` |
| `py/cache.py` | Caffeine `@Cacheable` |
| `py/resizer.py` | `ImageService` (Thumbnailator) |
| `py/data_service.py` | `DataImportExportService` |
| `py/manage.py` | Spring Shell 或 `CommandLineRunner` |

## 附录 B: 关键技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| ORM | Spring Data JPA | 40 张表，JPA 自动生成 CRUD |
| 数据库 | MySQL 8.0 | 用户要求，功能完整 |
| JSON 列 | MySQL JSON 类型 | runner_ids, settings 等字段原生 JSON 支持 |
| 缓存 | Caffeine | 单机部署，无需 Redis |
| 异步 | @Async + CompletableFuture | Sheets/邮件/Telegram 不阻塞 |
| 认证 | Spring Security + jjwt | 业界标准 |
| 定时任务 | @Scheduled | 替代 threading.Timer |
| FFmpeg | ProcessBuilder | 保持子进程调用方式 |
| HTML 解析 | Jsoup | 完美替代 BeautifulSoup |
| 图片处理 | Thumbnailator | 替代 Pillow 基础操作 |
| 构建工具 | Maven | 更广泛的社区支持 |
| JDK 版本 | 17 (LTS) | 长期支持版本 |

---

> **文档结束** — 本文档涵盖从 Flask+SQLite 到 Spring Boot+MySQL 的全部迁移设计，包含 236 个 API、40 张表、15 个业务服务的完整设计方案。前端不变，仅替换后端。

---

## 附录 C: 后端架构审查与优化

> **审查日期**: 2026-07-31 | **审查员**: 后端架构师 Agent  
> **整体评分**: B（方向正确，安全/可靠性/代码复用待加强）

### C.1 严重问题（已修正）

| # | 问题 | 修正 |
|---|------|------|
| C1 | JWT 每次请求都签发新 token | 仅剩余有效期 < 30% 时续签 |
| C2 | `CompletableFuture.runAsync()` 绕过业务线程池 | 改为 `taskExecutor.execute()` + 持久化 sync_log |
| C3 | `@Transactional` 内异步导致事务不一致 | DB 写入和 Sheets 写入拆为独立方法 |
| C4 | FFmpeg ProcessBuilder 无超时 | 5min 超时 + Semaphore(2) 并发限制 + 有界输出读取 |
| C5 | CORS `*` + `allowCredentials(true)` | 改用白名单 + 明确 headers |
| C6 | JWT Secret 弱默认值 | 启动时 `@PostConstruct` 校验，拒绝默认值 |

### C.2 中等问题（已修正）

| # | 问题 | 修正 |
|---|------|------|
| M1 | FbService 将成上帝类 | 设计文档已拆分 GG/FB Service |
| M2 | 40 个 Repository 平铺 | 建议按 gg/fb/common 分包 |
| M3 | API 无版本控制 | 建议使用 `/api/v1/` 前缀 |
| M4 | Sheets 并发写入无锁 | 建议 `ConcurrentHashMap<String, ReentrantLock>` 按表格加锁 |
| M5 | 缺少速率限制 | pom.xml 已加 Bucket4j 依赖 |
| M6 | JWT 无法主动踢出用户 | `token_version` 字段支持改密/禁用时强制失效 |
| M7 | 缺少结构化错误码 | 建议 `ApiError{code, message, field}` |
| M8 | Refresh Token 无轮换 | 建议每次 refresh 换发新 token |
| M9 | 平台守卫 startsWith 绕过 | 改为 `AntPathMatcher` 通配符匹配 |
| M10 | Google Ads Client 未复用 | 建议 `ConcurrentHashMap` 缓存客户端 |

### C.3 增强建议

| # | 建议 | 状态 |
|---|------|------|
| S1 | GG/FB 平台提取公共基类 | 建议引入 `BaseAccount`、`BaseProduct` |
| S2 | MapStruct 自动 Entity↔DTO 转换 | pom.xml 已加依赖 |
| S3 | Caffeine 缓存分级 | 建议 options 5min / users 10min / sheets-credentials 长期 |
| S4 | Spring Actuator + Prometheus 监控 | 建议添加 |
| S5 | Resilience4j 熔断器保护外部 API | pom.xml 已加依赖 |
| S6 | HikariCP 连池增至 30 | 已修正 |
| S7 | `ad_reports`/`fb_ad_reports` 日期索引 | 已添加 |
| S8 | SpringDoc OpenAPI (Swagger) | pom.xml 已加依赖 |
| S9 | `@Async` 显式指定线程池 | 已添加使用规范 |

---

## 附录 D: 数据库设计审查与修正

> **审查日期**: 2026-07-31 | **审查员**: 数据库优化师 Agent  
> **交叉验证基准**: `py/database.py`、`py/auth.py`  
> **整体评分**: B+（结构完整，3 个阻塞问题已修复）

### D.1 阻塞级修正

| # | 表 | 问题 | 修正 |
|---|-----|------|------|
| D1 | `users` | 缺少 `config` 列（`auth.py` 直接查询） | 已添加 `config JSON` |
| D2 | `product_assets` / `video_consumption` | 缺少对 `videos(id, owner_id)` 的复合外键 | 已添加 `fk_pa_video_ref` / `fk_vc_video_ref` |
| D3 | `video_consumption` | `user_id` 应为 `NOT NULL` | 已修正 |

### D.2 其他修正

| # | 修正内容 |
|---|---------|
| D4 | `mcc` 表 4 个新增列标注 `【新增】` |
| D5 | 补充 FB 平台 `account_statuses` 种子数据 |
| D6 | 补充 `product_names` 标签种子 |
| D7 | 添加 `idx_vc_product`、`idx_accounts_created`、`idx_products_created`、`idx_fb_accounts_created`、`idx_videos_imported` 索引 |
| D8 | `users` 加 `token_version` 支持 JWT 主动失效 |
| D9 | MySQL 版本要求标注：8.0.13+ |

### D.3 数据迁移备忘

- SQLite → MySQL 时用 `SET foreign_key_checks=0` 临时关闭外键检查
- `deleted_at` 字段统一使用 `DATETIME NULL`
- `JSON` 列迁移前用 `JSON_VALID()` 校验
- `videos` 复合主键 `(id, owner_id)` 确保所有引用表 FK 一致

---

## 附录 E: v1.6 前端优化 + YouTube 标签修复

> **日期**: 2026-08-03

### E.1 账户表格内联编辑扩展

**文件**: `frontend/src/views/AdsAccountPanel.vue`

原有账户表格只有"账户名称"和"所属 MCC"两列支持内联编辑。本次扩展到**全部 5 个可编辑字段**：

| 列 | 编辑组件 | API 字段 | 说明 |
|---|---|---|---|
| 账户名称 | `<el-input>` | `{ name }` | 已有，不变 |
| 所属 MCC | `<el-select>` filterable | `{ mcc_id }` | 已有，不变 |
| **时区** | `<el-select>` filterable + allow-create | `{ timezone }` | **新增**，支持输入新区值 |
| **代理** | `<el-select>` filterable + clearable | `{ agent_id }` | **新增**，可清空 |
| **状态** | `<el-select>` filterable | `{ status_id }` | **新增**，后端自动处理状态变更时间+清账 |

交互模式统一：hover 显示 ✏️ 按钮 → 点击切换为编辑组件 → 选择/输入后自动保存 → blur 取消。

### E.2 表格 UI 整体优化

**列宽协调**（全部 10 列重新分配）：

| 列 | 宽度 | 说明 |
|---|---|---|
| 选择框 | width=45 | 不变 |
| 账号名称 | min-width=140 | 中文名需要空间 |
| 账号 ID | min-width=140 | 长数字 ID |
| 所属 MCC | min-width=140 | 两行显示（名/ID） |
| 时区 | min-width=120 | "Asia/Shanghai" |
| 代理 | min-width=140 | 中文代理名 |
| 状态 | min-width=120 | 标签+编辑按钮 |
| 到手时间 | min-width=100 | YYYY-MM-DD |
| 状态变更时间 | min-width=110 | YYYY-MM-DD |
| 操作 | width=200 | 4 个按钮 |

**文本截断统一**：所有 inline-edit-cell 中的 `.inline-cell-text` 统一应用：
```css
white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1 1 auto;
```

**MCC 列改为上下行**：原来单行 `名字 · ID` 改为两行堆叠显示——上行名字、下行 ID，编辑按钮右侧垂直居中。

### E.3 YouTube 标签配置页空白修复

**问题**: 标签配置页（TagsConfig）textarea 全部显示为空，即使用户之前配置过标签。

**根因**:
1. **后端** `GET /api/youtube/tags`：数据库 `tags` 表无记录时返回 `{}`，前端 `store.tags = {}` 导致所有字段 `undefined`
2. **前端** TagsConfig 用 `v-show` 渲染，在父组件 `onMounted` 中 `store.loadTags()` 异步完成前就已挂载

**修复**:
1. **后端** [main.py](py/main.py) — `youtube_tags_get()` 加默认结构兜底：
   ```python
   tags = {
       "regions": [], "frame_types": [], "effectiveness": [],
       "product_names": [], "review_statuses": [],
   }
   ```
2. **前端** [TagsConfig.vue](frontend/src/components/youtube/TagsConfig.vue) — 新增 watch 监听：
   ```javascript
   watch(() => store.tags, () => loadCfgFromStore(), { deep: true })
   ```

### E.4 数据恢复说明

标签数据在 GitHub 的默认种子数据为（设计文档第 1194-1199 行）：
```sql
INSERT INTO tags (`key`, `value`) VALUES
('regions', '["巴西","菲律宾","孟加拉","印尼","东南亚通用","通用"]'),
('frame_types', '["融帧","非融帧"]'),
('effectiveness', '["","成效","一般"]'),
('review_statuses', '["能过审","不能过审"]'),
('product_names', '["p222","93ok"]');
```

迁移到 Spring Boot 后通过 MySQL 种子脚本自动初始化，无需手动配置。

---

## 附录 F: v1.8 产品包列表前端交互增强

> **日期**: 2026-08-13  
> **性质**: 纯前端改动，后端无变更  
> **文件**: `frontend/src/components/ProductCard.vue`

### F.1 需求背景

一个产品可能包含大量包。原实现将产品下所有包一次性展示、仅按「状态分组 → 导入时间」排序，且勾选只能逐个点击。本次增强三点：**状态过滤（默认只看正常包）**、**Shift 首尾范围选择**、**按系列名（series_name）排序**。

### F.2 状态过滤

- `filterStatus` 默认值由 `'all'` 改为 `'normal'`：产品展开后**默认只显示「正常」状态的包**。
- 状态筛选标签（全部/正常/没事件/暂停/掉包/拒登）放在**包列表顶部工具栏左侧**，不放产品栏 header。
- 最前面的 **「全部 N」** 标签（N=总包数）用于回到展示所有包的视图；各状态标签点击显示对应状态的包。
- 当前激活的状态标签以 `effect="dark"` 高亮，非激活为 `light`。

### F.3 Shift 首尾范围选择

- 新增锚点 `anchorId`：记录最近一次单独点击（不带 Shift）的包。
- 普通点击包 checkbox：正常勾选/取消该包，并更新锚点。
- **按住 Shift 点击包 checkbox**：按当前展示顺序，把「锚点包 ↔ 当前包」之间的连续所有包一并勾选（追加语义）。
- checkbox 由 `v-model` 改为 `:checked` 绑定 + `@click.stop.prevent` 手动处理，视觉状态完全由 `checkedIds` 驱动。

### F.4 名字排序

- 排序按钮放在**包列表顶部工具栏左侧**（紧跟状态筛选标签），不放产品栏、不放工具栏右侧。
- 排序键为 **`series_name`（系列名）**，用 `localeCompare(..., undefined, { numeric: true })` 字典序比较（数字感知，`GG-9` 排在 `GG-10` 前）。
- 排序主按钮在 **「降序(Z→A) ↔ 升序(A→Z)」** 之间切换（首次点击进入降序），不在降序/升序/默认三态间循环。
- 进入排序状态后，旁边出现 **「恢复默认排序」** 按钮，点击恢复默认（状态分组 → 导入时间）。
- 排序生效范围（用户确认的规则）：
  - **展示所有包**（`filter='all'`，多状态混合）：只对「正常」包按系列名排序，其它状态包保持底部原有顺序不动；
  - **筛选单一状态**：对当前展示的所有包整体按系列名排序。

### F.5 后端影响

**无**。过滤、排序、勾选均在 `ProductCard.vue` 前端完成（`props.product.packages` 已随产品列表一次性返回）。

迁移到 Spring Boot 后，`GET /api/products/*` 接口只需按当前 Python 实现原样返回 `packages` 数组（原始顺序），**不做**按状态或名字的排序/过滤——这些逻辑由前端负责，迁移时不要在 Service 层重复实现。
