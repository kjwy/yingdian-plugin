# v0.8.0 更新说明

- 榜单页改为 TMDB、豆瓣、豆瓣榜单、豆瓣片单四个来源
- 新增类型、排序、年代、地区、风格、入库状态筛选
- 订阅页新增电影订阅、电视剧订阅、订阅日历、规则、配置五个页签
- 新增订阅状态、网盘类型、更新时间筛选和订阅搜索
- 新增添加订阅弹窗，可通过片名搜索 TMDB 并自动读取总集数
- 新增月度订阅日历，展示剧集更新时间
- 订阅记录新增起始集数、总集数、网盘类型、订阅链接、检查状态和完成状态
- 自动订阅执行后记录检查时间、结果和完成状态

更新：

```bash
cd /vol1/1000/tools/yingdian-plugin
git fetch origin main && git reset --hard origin/main
docker cp app/. yingdian-plugin:/app/app/
docker restart yingdian-plugin
```
