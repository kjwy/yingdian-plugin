# 影癫插件 for Symedia（YingDian Plugin）

面向 **Symedia 媒体服务器**的影癫（MADREEL / dian115）配套插件服务：
每日自动签到、订阅搜索、自动解锁，并把 115 链接推送给 Symedia 完成转存归档。

<p align="center">
  <img src="app/static/icon-512.png" width="120" alt="YingDian Plugin" />
</p>

> 当前版本：**v0.1.5** ｜ 支持 Docker 部署 / 移动端（iPhone 安全区 + PWA 添加到主屏幕）

## 功能

- **每日签到**：随机时间窗口自动签到（普通 / 幸运），结果推送到 Telegram
- **订阅搜索**
  - 按 TMDB 标识调用 `list-shares` 查询可解锁分享
  - 或启用 `rss` 增量订阅（按分类 / 地区 / DT2 TAG 过滤）
  - 可用 TMDB 片名搜索添加订阅（也支持直接填 TMDB ID）
- **本地评分排序**：清晰度 / 片源 / HDR / 字幕 / 热度 / 体积
- **自动解锁**：解锁积分上限、只订阅免费、解锁速率限制（默认 3 次/分钟）
- **自动转存**：解锁得到的 115 链接推送至 Symedia「115助手」，转存 → 归档 → Emby
- **Web 界面**
  - 仪表盘 / 订阅 / 日志 / 设置
  - **Telegram 诊断**、**TMDB 诊断** 按钮，一键验证配置
  - 支持 HTTP 代理（NAS 在国内直连不了 Telegram / TMDB 时使用）
  - 密钥字段留空即保持不变，避免误清空
- **移动端适配**
  - iPhone 灵动岛 / 刘海 / Home Indicator 安全区（`viewport-fit=cover` + `safe-area-inset`）
  - 手机端底部 Tab 导航，输入框 16px 防 iOS 自动放大
  - **PWA**：可「添加到主屏幕」，独立图标 + 全屏运行（Android 支持 maskable 图标）

## 部署（飞牛 NAS / Docker）

```bash
# 1. 上传项目到 NAS，例如 /vol1/1000/tools/yingdian-plugin
cd /vol1/1000/tools/yingdian-plugin

# 2. 启动（宿主机端口 8909，如冲突改 docker-compose.yml）
docker compose up -d --build

# 3. 访问
#    http://<NAS-IP>:8909
```

首次启动是**模拟模式**（不调用真实接口），可先熟悉界面。
填好 OpenAPI Key 与 Telegram 后，安装官方 SDK 并关闭模拟模式：

```bash
# 把官方 SDK 的 .whl 放到 sdk/ 目录
sed -i 's/YDP_MOCK=1/YDP_MOCK=0/' docker-compose.yml
docker compose up -d --build
```

## 配置项（对标 Symedia 的 HDHive 插件）

| 分类 | 配置 |
| --- | --- |
| OpenAPI | 服务地址、OpenAPI Key、模拟模式 |
| 签到 | 启用定时签到、普通/幸运、随机时间窗口、签到推送 |
| 解锁与筛选 | 解锁积分上限、解锁速率限制、电影/电视剧过滤词、只订阅免费、解锁官组 |
| RSS 订阅 | 启用、轮询间隔、过滤条件（分类/地区/TAG） |
| Telegram | Bot Token、目标群 Chat ID、消息模板、**HTTP 代理**、**诊断/测试按钮** |
| TMDB | API Key、代理、API 域名、图片域名、**诊断按钮** |

## 使用的影癫 OpenAPI 接口

| 接口 | 用途 |
| --- | --- |
| `POST /api/portal/openapi/signin` | 每日签到 |
| `POST /api/portal/openapi/list-shares` | 按 TMDB 查询可解锁分享 |
| `POST /api/portal/openapi/rss` | 增量订阅影视分享 |
| `POST /api/portal/openapi/unlock` | 解锁并获取 115 链接 |
| `POST /api/portal/openapi/me` | 积分 / VIP / 额度 |

> OpenAPI v2 要求「用户 API Key + 已审批开发者应用 SDK」双凭证，
> 需要先在 [影癫门户](https://m.dian115.com/me/openapi-key) 申请开发者并下载官方 SDK。

## 项目结构

```
app/
├─ main.py        FastAPI 路由与页面（含诊断接口、manifest）
├─ config.py      配置读写（data/config.json）
├─ store.py       SQLite：签到/解锁/订阅/游标
├─ dian115.py     OpenAPI v2 客户端（官方 SDK / 模拟）
├─ scoring.py     分享评分
├─ tmdb.py        片名 → TMDB ID（支持代理与域名自定义）
├─ notify.py      Telegram 推送与诊断（支持代理）
├─ scheduler.py   定时签到 / 订阅搜索 / RSS 轮询
├─ service.py     业务编排
├─ templates/     页面（含移动端底部 Tab）
└─ static/        样式、脚本与图标（favicon / apple-touch-icon / PWA）
```

## 免责声明

仅供个人学习与媒体库自动化使用，请遵守影癫站点规则与当地法律法规。
