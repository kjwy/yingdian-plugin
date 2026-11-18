# v0.8.5 更新说明

- 订阅卡片支持点击编辑
- 可编辑标题、TMDB ID、季、开始集数、总集数、频道类型和手动 115 链接
- 手动 115 分享链接会在订阅执行时读取实际文件集数
- 只转存 Emby 尚未入库且没有处理过的集数
- 分享后续增加新集时，下一次订阅检查会自动发现并转存
- 已入库集数会自动从“等待 Emby 入库”记录中移除
- 搜索页每次进入保持空白，不再恢复上一次搜索内容

更新：

```bash
cd /vol1/1000/tools/yingdian-plugin
git fetch origin main && git reset --hard origin/main
docker cp app/. yingdian-plugin:/app/app/
docker restart yingdian-plugin
```
