#!/bin/bash
# 影癫插件 · 一键诊断：把输出整段发给我就能定位问题
cd "$(dirname "$0")" || exit 1
echo "================ 1. 容器状态 ================"
docker compose ps
echo
echo "================ 2. browser 日志（最后 60 行）================"
docker logs yingdian-browser --tail 60 2>&1 || echo "（拿不到 yingdian-browser 日志，容器可能没创建）"
echo
echo "================ 3. 端口检查 ================"
echo -n "CDP 9222: "; curl -s -m 3 http://127.0.0.1:9222/json/version | head -c 200; echo
echo -n "noVNC 6080: "; curl -s -o /dev/null -w "HTTP %{http_code}\n" -m 3 http://127.0.0.1:6080/vnc.html
echo -n "插件 8909: "; curl -s -o /dev/null -w "HTTP %{http_code}\n" -m 3 http://127.0.0.1:8909/
echo
echo "================ 4. 容器内自检 ================"
docker exec yingdian-browser sh -c '/opt/chromium/chrome-linux/chrome --version; echo "--- chromium.log ---"; tail -20 /tmp/chromium.log; echo "--- xvfb.log ---"; tail -10 /tmp/xvfb.log; echo "--- websockify.log ---"; tail -10 /tmp/websockify.log' 2>&1 || echo "（进不去容器）"
echo
echo "================ 5. 镜像信息 ================"
docker images | grep -i yingdian
echo "================ 完成 ================"

