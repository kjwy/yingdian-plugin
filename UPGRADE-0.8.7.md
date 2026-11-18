# v0.8.7 更新说明

- 搜索结果切页后保留 60 秒，返回时恢复输入和结果
- 超过 60 秒自动失效，下次进入搜索页恢复为空白
- 搜索框支持按 Enter 直接确认搜索
- 订阅日历新增前后各 3 天的日期条
- 日历条目区分已入库、待补、今天、将更
- 点击日期可查看当天剧集、集数范围和入库状态
- 月历日期也可点击切换查看

更新：

```bash
cd /vol1/1000/tools/yingdian-plugin
git fetch origin main && git reset --hard origin/main
docker cp app/. yingdian-plugin:/app/app/
docker restart yingdian-plugin
```
