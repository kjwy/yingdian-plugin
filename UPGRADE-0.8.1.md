# v0.8.1 更新说明

- 修复榜单只能查看第一页的问题
- TMDB 发现、豆瓣发现、豆瓣榜单支持分页
- 榜单滚动到底部自动加载下一页
- 增加“加载更多”按钮作为浏览器兼容兜底
- 筛选条件会继续传递到后续分页

更新：

```bash
cd /vol1/1000/tools/yingdian-plugin
git fetch origin main && git reset --hard origin/main
docker cp app/. yingdian-plugin:/app/app/
docker restart yingdian-plugin
```
