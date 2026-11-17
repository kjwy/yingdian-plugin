# v0.8.3 更新说明

- 订阅频道新增“全部网盘，优先补全集数”
- 全部模式下跨 115、ED2K、磁力统一计算已处理集数，避免重复解锁
- 已获取过链接的 ED2K/磁力资源在手动搜索中显示“再次获取链接”
- 再次获取已有链接时优先复用原链接，不重复扣积分
- ED2K/磁力订阅没有新集数时，明确显示“第 N 集链接已获取，等待 Emby 入库”
- 115 订阅继续按已转存集数防重复

更新：

```bash
cd /vol1/1000/tools/yingdian-plugin
git fetch origin main && git reset --hard origin/main
docker cp app/. yingdian-plugin:/app/app/
docker restart yingdian-plugin
```
