# 影癫插件 for Symedia（YingDian Plugin）

面向 **Symedia 媒体服务器**的影癫（MADREEL / dian115）配套插件服务：
每日自动签到、订阅搜索、自动解锁，并把 115 链接推送给 Symedia 完成转存归档。

![status](https://img.shields.io/badge/status-alpha-orange)

## 功能

- **每日签到**：随机时间窗口内自动签到（普通/幸运），支持结果推送 Telegram
- **订阅搜索**：
  - 按 TMDB 标识查询 `list-shares` 获取候选分享
  - 或启用 `rss` 增量订阅（按分类/地区/DT2 TAG 过滤）
- **本地评分排序**：清晰度 / 片源 / HDR / 字幕 / 热度 / 体积
- **自动解锁**：积分上限、只订阅免费、解锁速率限制（默认 3 次/分钟）
- **自动转存**：解锁得到的 115 链接推送至 Symedia「115助手」，转存 → 归档 → Emby
- **Web 界面**：账号状态、签到历史、解锁日志、订阅管理、配置、手动搜索

## 部署（飞牛 NAS / Docker）

```bash
# 1. 上传项目到 NAS，例如 /vol1/docker/yingdian-plugin
cd /vol1/docker/yingdian-plugin

# 2. 启动
docker compose up -d --build

# 3. 打开界面
#    http://<NAS-IP>:8899
```

首次启动默认是**模拟模式**（不调用真实接口），可以先熟悉界面。
在「设置」里填好 OpenAPI Key 和 Telegram 后，把 `docker-compose.yml` 里的
`YDP_MOCK=1` 改成 `YDP_MOCK=0`，并把官方 SDK 的 `.whl` 放进 `sdk/` 目录后重新构建：

```bash
docker compose up -d --build
```

## 配置项（对标 Symedia 的 HDHive 插件）

| 分类 | 配置 |
| --- | --- |
| OpenAPI | 服务地址、OpenAPI Key、模拟模式 |
| 签到 | 启用定时签到、普通/幸运、随机时间窗口、签到推送 |
| 解锁与筛选 | 解锁积分上限、解锁速率限制、电影/电视剧过滤词、只订阅免费、解锁官组 |
| RSS 订阅 | 启用、轮询间隔、过滤条件（分类/地区/TAG） |
| Telegram | Bot Token、目标群 Chat ID、消息模板 |
| 其它 | TMDB API Key（片名搜索）、时区 |

## 使用的影癫 OpenAPI 接口

| 接口 | 用途 |
| --- | --- |
| `POST /api/portal/openapi/signin` | 每日签到 |
| `POST /api/portal/openapi/list-shares` | 按 TMDB 查询可解锁分享 |
| `POST /api/portal/openapi/rss` | 增量订阅影视分享 |
| `POST /api/portal/openapi/unlock` | 解锁并获取 115 链接 |
| `POST /api/portal/openapi/me` | 积分 / VIP / 额度 |

> OpenAPI v2 要求「用户 API Key + 已审批开发者应用 SDK」双凭证，
> 因此需要先在 [影癫门户](https://m.dian115.com/me/openapi-key) 申请开发者并下载官方 SDK。

## 项目结构

```
app/
├─ main.py        FastAPI 路由与页面
├─ config.py      配置读写（data/config.json）
├─ store.py       SQLite：签到/解锁/订阅/游标
├─ dian115.py     OpenAPI v2 客户端（官方 SDK / 模拟）
├─ scoring.py     分享评分
├─ tmdb.py        片名 → TMDB ID
├─ notify.py      Telegram 推送
├─ scheduler.py   定时签到 / 订阅搜索 / RSS 轮询
├─ service.py     业务编排
├─ templates/     页面
└─ static/        样式与脚本
```

## 免责声明

仅供个人学习与媒体库自动化使用，请遵守影癫站点规则与当地法律法规。
