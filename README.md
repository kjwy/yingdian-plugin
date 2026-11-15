# 影癫插件 for Symedia（YingDian Plugin）

面向 **Symedia 媒体服务器**的影癫（MADREEL / dian115）配套插件服务：
每日自动签到、订阅搜索、自动解锁，并把 115 链接推送给 Symedia 完成转存归档。

> 本项目为个人自用的媒体自动化工具，通过影癫 OpenAPI v2 与 Symedia 的 Telegram 能力协作。

## 功能

- **每日签到**：定时（随机时间）调用影癫 OpenAPI 签到，支持普通/幸运签到与结果通知
- **订阅搜索**：按电影/电视剧订阅自动检索影癫资源
  - TMDB 标识 → `list-shares` 查询可解锁分享
  - 或 `rss` 增量订阅（按分类 / 地区 / DT2 TAG 过滤）
- **本地评分排序**：清晰度、片源、HDR、字幕、热度、体积多维度打分，选最优资源
- **自动解锁**：按积分上限、免费优先、官组策略控制是否解锁，并限制解锁速率
- **自动转存**：解锁得到的 115 分享链接推送至 Symedia「115助手」，自动转存 → 归档 → 进 Emby
- **Web 配置界面**：账号状态、签到历史、过滤词、解锁策略、日志

## 架构

```
┌─────────────────────────────┐
│  影癫插件（Docker 服务）      │
│  ├─ Web 配置界面             │
│  ├─ 定时任务（签到/RSS 订阅） │
│  ├─ 评分与解锁策略            │
│  └─ 影癫 OpenAPI v2 客户端   │
└───────────┬─────────────────┘
            │ 115 分享链接
            ▼
┌─────────────────────────────┐
│  Telegram → Symedia 115助手  │
│  转存 → 归档刮削 → Emby      │
└─────────────────────────────┘
```

## 使用到的影癫 OpenAPI 接口

| 接口 | 用途 |
| --- | --- |
| `POST /api/portal/openapi/signin` | 每日签到 |
| `POST /api/portal/openapi/list-shares` | 按 TMDB 查询可解锁分享 |
| `POST /api/portal/openapi/rss` | 增量订阅影视分享 |
| `POST /api/portal/openapi/unlock` | 解锁分享并获取 115 链接 |
| `POST /api/portal/openapi/me` | 账户积分 / VIP / 额度 |

调用遵循 OpenAPI v2 规范：使用官方发放的 SDK 对业务 JSON 做加密 envelope，用户侧仅需填入自己的 OpenAPI Key。

## 计划部署方式

Docker Compose 单容器部署，配置与数据持久化在本地卷，适配飞牛 NAS / 任意 Docker 主机。

## 状态

开发中：配置界面与调度框架已完成设计，正在接入 OpenAPI v2 SDK。

## 免责声明

本项目仅供个人学习与媒体库自动化使用，请遵守影癫站点规则与当地法律法规，仅处理你有权获取的内容。
