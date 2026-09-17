# 选用精简版 Python 基础镜像（仅约 50MB，大幅缩减镜像体积）
FROM python:3.10-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 设置工作目录
WORKDIR /app

# 安装必要的系统依赖（ffmpeg 用于音视频处理，curl 用于健康检查，tzdata 设置时区）
# 保持极简依赖，并彻底清理 apt 缓存
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tzdata \
    curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖，强制不拉取任何额外的 NVIDIA CUDA 庞大轮子
RUN pip3 install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建数据与内置模型目录，并在构建期烘焙 tiny 模型到 /app/builtin_models（仅约 75MB，开箱即用）
RUN mkdir -p /data/models /app/builtin_models \
    && python3 scripts/download_whisper_model.py tiny /app/builtin_models || \
       echo "[Build] WARN: 构建期下载 tiny 模型失败，将在首次运行时通过网络下载"

# 暴露 Streamlit 端口
EXPOSE 8501

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# 启动命令
CMD ["sh", "-c", "\
    if [ -n \"$WHISPER_PRELOAD_MODELS\" ]; then \
        echo \"[Entrypoint] Pre-downloading Whisper models: $WHISPER_PRELOAD_MODELS\"; \
        python3 scripts/download_whisper_model.py \"$WHISPER_PRELOAD_MODELS\" || \
            echo \"[Entrypoint] WARN: 模型预下载失败，将在运行时重试\"; \
    fi && \
    exec streamlit run app.py \
        --server.port=8501 \
        --server.address=0.0.0.0 \
        --server.headless=true \
        --server.runOnSave=false \
"]
