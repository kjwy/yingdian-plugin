# v0.8.2 更新说明

- 已处理集数按 115、ED2K、磁力分别记录，不再互相禁用
- 修复选择 ED2K 订阅却回退解锁 115 的问题
- 订阅只使用指定的网盘类型；没有匹配资源时保持等待
- 剧集候选排序改为：缺集覆盖、资源集数、积分、画质
- 同网盘类型已处理的集数继续防止重复解锁
- 旧的解锁记录会自动识别并迁移为对应网盘类型

更新：

```bash
cd /vol1/1000/tools/yingdian-plugin
git fetch origin main && git reset --hard origin/main
docker cp app/. yingdian-plugin:/app/app/
docker restart yingdian-plugin
```
