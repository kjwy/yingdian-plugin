# 架构与设计说明

## 目标

对标 Symedia 内置的「HDHive配置 / HDHive订阅」插件，为影癫提供等价能力：
签到、订阅搜索、自动解锁与转存。

## 模块划分

| 模块 | 职责 |
| --- | --- |
| `web` | FastAPI 提供配置界面与手动操作入口 |
| `store` | SQLite 保存设置、签到记录、解锁记录、RSS 游标 |
| `dian115` | 影癫 OpenAPI v2 客户端（基于官方 Python SDK） |
| `scoring` | 分享评分：清晰度 / 片源 / HDR / 字幕 / 热度 / 体积 |
| `scheduler` | 定时签到、RSS 轮询、订阅补查 |
| `notify` | Telegram 推送：签到结果、解锁结果、115 链接 |

## 执行流程

1. **签到**：每日随机时间 → `signin(mode)` → 记录结果 → 通知
2. **订阅搜索**：
   - 有 `rss` 事件时：读取事件 → 匹配订阅媒体 → 选 share_id → `unlock`
   - 无事件时：TMDB 搜索 → `list-shares` → 本地评分 → `unlock`
3. **转存**：`unlock` 返回 115 链接 → 推送到 Symedia 115助手 → 自动转存归档

## 配置项（对标 HDHive 插件）

- OpenAPI Key、服务地址
- 启用定时签到、签到通知
- 解锁积分上限、解锁速率限制（次/分钟）
- 电影 / 电视剧过滤词（正则）
- 最大解锁积分、只订阅免费资源、解锁官组资源
- 启用 API 搜索、RSS 过滤条件
- Telegram bot token 与目标群 chat id
