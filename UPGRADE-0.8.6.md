# v0.8.6 更新说明

- 手动 115 订阅链接改为按文件 ID 选择性转存
- 分享后续新增第 11-12 集时，只提交新增文件，不重复转存已有集数
- 保留整分享转存作为无法识别分集文件时的兜底

更新：

```bash
cd /vol1/1000/tools/yingdian-plugin
git fetch origin main && git reset --hard origin/main
docker cp app/. yingdian-plugin:/app/app/
docker restart yingdian-plugin
```
