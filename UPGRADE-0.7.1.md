# v0.7.1 修复说明

- 修复 ED2K / 磁力资源详情页实际积分高于列表显示积分时被错误拦截的问题
- 修复豆瓣榜单和 TMDB 榜单跳转后电影、剧集类型未传递的问题
- 签到流程增加页面重载重试和积分变化兜底判断
- 手动解锁按「解锁积分上限」判断，不再使用资源列表中的错误积分值
- ED2K / 磁力按钮文案改为「解锁并获取链接」

更新：

```bash
cd /vol1/1000/tools/yingdian-plugin
git pull --ff-only origin main
docker compose up -d --build yingdian-plugin
```
