# 伙食评价 · 网页版 Docker 镜像
# 用途：部署到 1Panel / 任意 Docker 环境
# 构建：docker build -t hqhs-eval:2.9 .
# 运行：见 docker-compose.yml

# 基础镜像可替换：国内拉不动官方镜像时，用
#   docker compose build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
# 或者在 docker-compose.yml 的 build.args 里改
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    TZ=Asia/Shanghai

# 时区（日志时间戳要和你的本地时间一致）
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
 && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖先装，利用镜像层缓存：改代码不会重装依赖
# 国内服务器默认走清华源；海外可 --build-arg PIP_INDEX=https://pypi.org/simple
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
COPY web/requirements.txt /app/web/requirements.txt
RUN pip install --no-cache-dir -i "$PIP_INDEX" -r /app/web/requirements.txt

# 只复制运行需要的东西（apk / tools / 文档都不进镜像）
COPY web/server.py      /app/web/server.py
COPY web/index.html     /app/web/index.html
COPY scripts/hqhs_eval.py       /app/scripts/hqhs_eval.py
COPY scripts/aes_pure.py        /app/scripts/aes_pure.py
COPY scripts/import_accounts.py /app/scripts/import_accounts.py
COPY eval_config.json   /app/eval_config.json

# 非 root 运行
RUN useradd -m -u 1000 hqhs \
 && mkdir -p /app/out \
 && chown -R hqhs:hqhs /app
USER hqhs

EXPOSE 8080

# 容器自检：/api/state 是公开接口，不需要密码
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8080/api/state', timeout=3).status==200 else sys.exit(1)"

# 密码由 compose 的 HQHS_PASSWORD 环境变量传入，不写在命令行里
CMD ["python", "/app/web/server.py", "--host", "0.0.0.0", "--port", "8080"]
