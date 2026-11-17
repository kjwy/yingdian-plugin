#!/bin/bash
# 影癫插件 · 浏览器容器启动脚本
set -u

log() { echo "[$(date '+%H:%M:%S')] $*"; }

CHROME_BIN="${CHROME_BIN:-/opt/chromium/chrome-linux/chrome}"
PROFILE_ROOT="${PROFILE:-/profile}"
# 固定 profile 目录：这样重启后登录态还在
PROFILE_DIR="$PROFILE_ROOT/data"
mkdir -p "$PROFILE_DIR"

clean_locks() {
  # 清理上次异常退出留下的锁，否则 Chromium 报 "profile appears to be in use" 直接退出
  rm -f "$PROFILE_DIR/SingletonLock" "$PROFILE_DIR/SingletonCookie" "$PROFILE_DIR/SingletonSocket" 2>/dev/null
  rm -f "$PROFILE_ROOT"/Singleton* 2>/dev/null
  rm -rf "$PROFILE_ROOT"/run* 2>/dev/null
  log "已清理残留 profile 锁"
}
clean_locks

log "=== 影癫浏览器容器启动 ==="
log "chromium: $CHROME_BIN"
if [ -x "$CHROME_BIN" ]; then
  log "版本: $("$CHROME_BIN" --version 2>&1)"
  MISSING="$(ldd "$CHROME_BIN" 2>/dev/null | grep 'not found' || true)"
  [ -n "$MISSING" ] && log "!! 缺少系统库: $MISSING"
else
  log "!! 找不到 chromium"
fi

# 0) 诊断日志服务
(cd /tmp && python3 -m http.server 6081 >/dev/null 2>&1) &
log "日志服务: http://<IP>:6081/chromium.log"

# 1) Xvfb
log "启动 Xvfb :0"
Xvfb :0 -screen 0 1440x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
for i in $(seq 1 30); do [ -S /tmp/.X11-unix/X0 ] && break; sleep 0.5; done
[ -S /tmp/.X11-unix/X0 ] && log "Xvfb 就绪" || log "!! Xvfb 未就绪"

# 2) Chromium（前 3 次有头，仍失败自动 headless）
log "启动 Chromium（CDP 127.0.0.1:9222）"
(
  attempt=0
  while true; do
    attempt=$((attempt+1))
    rm -f "$PROFILE_DIR/SingletonLock" "$PROFILE_DIR/SingletonCookie" "$PROFILE_DIR/SingletonSocket" 2>/dev/null
    HEADLESS=""
    if [ $attempt -gt 3 ]; then HEADLESS="--headless=new"; log "第 $attempt 次：改用 headless"; fi
    "$CHROME_BIN" \
      --no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage \
      --disable-gpu --disable-software-rasterizer \
      --remote-debugging-port=9222 --remote-allow-origins=* \
      --user-data-dir="$PROFILE_DIR" \
      --no-first-run --no-default-browser-check --noerrdialogs \
      --window-size=1440,900 $HEADLESS \
      "https://m.dian115.com/" >>/tmp/chromium.log 2>&1
    code=$?
    log "Chromium 退出（code=$code），5 秒后重启"
    tail -6 /tmp/chromium.log 2>/dev/null
    sleep 5
  done
) &

# 2.5) CDP 转发：Chromium 只监听 127.0.0.1，socat 暴露到 0.0.0.0:9223
log "启动 CDP 转发 0.0.0.0:9223 -> 127.0.0.1:9222"
socat TCP-LISTEN:9223,fork,reuseaddr TCP:127.0.0.1:9222 >/tmp/socat.log 2>&1 &

# 3) x11vnc
x11vnc -display :0 -forever -shared -nopw -quiet -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
log "x11vnc 启动（5900）"

# 4) noVNC
websockify --web=/usr/share/novnc 6080 localhost:5900 >/tmp/websockify.log 2>&1 &
log "noVNC 启动（6080）"

sleep 10
CDP="$(curl -s -m 3 http://127.0.0.1:9223/json/version 2>/dev/null | head -c 150)"
log "CDP 自检(9223): ${CDP:-（空）}"
log "noVNC 自检: $(curl -s -o /dev/null -w '%{http_code}' -m 3 http://127.0.0.1:6080/vnc.html 2>/dev/null)"
log "=== 就绪 noVNC=http://<IP>:6080/vnc.html  CDP=9223 ==="

wait $XVFB_PID

