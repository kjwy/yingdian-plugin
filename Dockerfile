FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# 国内加速：PyPI 清华镜像（如不需要可删掉 -i 参数）
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt .
RUN pip install -i ${PIP_INDEX} -r requirements.txt

# 影癫官方 OpenAPI v2 SDK（可选）：把 .whl 放进 sdk/ 目录即可自动安装
COPY sdk/ /app/sdk/
RUN if ls /app/sdk/*.whl >/dev/null 2>&1; then pip install -i ${PIP_INDEX} --no-cache-dir /app/sdk/*.whl; else echo "未提供官方 SDK，使用模拟模式"; fi

COPY app ./app

VOLUME ["/app/data"]

EXPOSE 8899

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8899"]
