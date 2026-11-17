# v0.8.4 更新说明

- 已有订阅可直接切换频道类型，不需要删除重建
- 支持切换为全部网盘、115、ED2K、磁力

更新：

```bash
cd /vol1/1000/tools/yingdian-plugin
git fetch origin main && git reset --hard origin/main
docker cp app/. yingdian-plugin:/app/app/
docker restart yingdian-plugin
```
