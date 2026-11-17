# v0.7.0 更新说明

## 更新内容

- 新增 Emby 入库检测
- 搜索结果显示已入库集数、缺失集数和可补齐集数
- 剧集订阅优先补齐缺失集数，再比较完整度和画质
- 已入库和正在转存的集数不再重复解锁
- 新增豆瓣高分、热门电影、热门剧集、国产剧、韩剧榜单
- 豆瓣海报增加本地代理，手机端不再出现空白海报
- 搜索结果增加影片标题、海报、年份、评分和简介

## NAS 更新步骤

```bash
cd /vol1/1000/tools/yingdian-plugin
unzip -o yingdian-plugin-update-0.7.0.zip
docker compose up -d --build yingdian-plugin
docker logs --tail 100 yingdian-plugin
```

不要删除或覆盖现有的 `data/` 和 `browser-profile/`。

## 更新后设置

打开：

```text
http://192.168.1.6:8909/settings
```

在「Emby 入库检测」中填写：

```text
Emby 地址：http://192.168.1.6:8096
Emby API Key：填写 Symedia 中现有的 Emby API Key
启用入库检测：勾选
自动跳过已入库和正在转存的集数：勾选
防重复转存时间：24
```

保存后点击「测试 Emby」，看到连接正常即可。
