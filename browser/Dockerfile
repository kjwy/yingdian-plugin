# 影癫插件 · 浏览器容器（Chromium + CDP + noVNC）
# 不依赖 npm：直接下载 Chromium 压缩包，构建更稳更快
FROM debian:bookworm-slim

WORKDIR /app

# apt 换清华源
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources; \
    fi && \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list; \
    fi

# VNC/noVNC + Chromium 运行所需的全部系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11vnc \
    websockify \
    novnc \
    fonts-noto-cjk \
    ca-certificates \
    curl \
    socat \
    unzip \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 libxfixes3 libxrender1 \
    libxtst6 libxi6 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 直接下载 Chromium（Playwright 1.48 对应的 revision 1148，npmmirror 镜像）
ARG CHROMIUM_URL=https://cdn.npmmirror.com/binaries/playwright/builds/chromium/1148/chromium-linux.zip
RUN curl -fL --retry 3 --retry-delay 2 -o /tmp/chromium.zip "$CHROMIUM_URL" \
    && mkdir -p /opt/chromium \
    && unzip -q /tmp/chromium.zip -d /opt/chromium \
    && rm -f /tmp/chromium.zip \
    && chmod +x /opt/chromium/chrome-linux/chrome \
    && /opt/chromium/chrome-linux/chrome --version

ENV CHROME_BIN=/opt/chromium/chrome-linux/chrome \
    DISPLAY=:0

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/profile"]
EXPOSE 9222 6080
CMD ["/entrypoint.sh"]
