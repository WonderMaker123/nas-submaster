# NAS SubMaster (NAS 字幕管家)

> 专为 NAS / 家庭影音服务器（Jellyfin、Emby、Plex）打造的全自动影视字幕提取与 AI 翻译神器。  
> 基于 **Faster-Whisper**（内置轻量模型） + **大语言模型（LLM）**，一键搞定听写、翻译、双语字幕合成与原位入库。

---

## 🚀 小白一分钟极速安装（Docker Compose）

你不需要复杂的命令行操作，只要你的 NAS 支持 Docker（群晖、威联通、极空间、绿联、飞牛 fnOS、自建 Unraid/Linux 等），复制下方配置即可一键运行！

### 步骤 1：准备一个目录
在你的 NAS 上新建一个文件夹（例如 `docker/nas-submaster`），并在里面新建一个名为 `docker-compose.yml` 的文本文件。

### 步骤 2：直接复制下方配置到 `docker-compose.yml`

> 💡 **小白注意**：只需要修改第 **11** 行的 `/volume1/video` 为你自己 NAS 上存电影/电视剧的真实路径！

```yaml
services:
  nas-submaster:
    image: wndfl/nas-submaster:latest
    container_name: nas-submaster
    restart: unless-stopped
    ports:
      - "8501:8501"
    volumes:
      # 1. 软件数据与配置目录（不需要改，默认保存在当前文件夹的 data 下）
      - ./data:/data
      # 2. 你的媒体库目录（【重要】：把前面的 /volume1/video 改成你 NAS 的真实影视路径）
      - /volume1/video:/media/movies
      # 3. Docker 通信（用于网页端检测与自更新）
      - /var/run/docker.sock:/var/run/docker.sock

    # 💡【可选】Intel 核显硬件加速（N100 / J4125 / J6412 / 8-12代Intel CPU 用户建议开启，去掉下面两行前面的 # 注释）
    # devices:
    #   - /dev/dri:/dev/dri

    environment:
      - TZ=Asia/Shanghai
      - PYTHONUNBUFFERED=1
      # 镜像已出厂内置 tiny 极速模型（免下载、秒开），如需首次下载 base 可改此项
      - WHISPER_PRELOAD_MODELS=tiny
      # auto 表示有显卡用显卡，没有显卡自动回退到 CPU，无需担心报错
      - WHISPER_DEVICE=auto

      # 🔒【可选】Web 访问安全密码（留空或注释则免密进入；设置后公网访问必须输入此密码）
      # - WEB_PASSWORD=your_password

      # 🌐【可选】网络代理配置（大陆 NAS 用户如果需要下载 base/small/large 等大模型或访问国外 LLM API，去掉下面注释并修改为你局域网的代理地址）
      # - HTTP_PROXY=http://192.168.1.100:7890
      # - HTTPS_PROXY=http://192.168.1.100:7890
      # - NO_PROXY=localhost,127.0.0.1
    shm_size: 4gb
```

### 步骤 3：一键启动
- **命令行用户**：在 `docker-compose.yml` 所在目录执行：
  ```bash
  docker compose up -d
  ```
- **NAS 界面用户**（群晖 Container Manager / 威联通 ContainerStation / 飞牛 Docker / 绿联 Docker 等）：  
  打开“项目 / Compose” -> “新增项目” -> 粘贴上面的内容 -> 点击“立即部署”。

### 步骤 4：打开管理后台
在浏览器中打开：
```text
http://你的NAS_IP:8501
```
*(例如 `http://192.168.1.100:8501`)*

---

## 🎯 第一次使用配置（30秒完成）

1. **配置 AI 翻译**：
   - 打开网页后，点击右上角（或侧边栏）的 **「⚙️ 设置」**。
   - 在【翻译设置】中填入你常用的 AI 大模型 API：
     - **极力推荐**：DeepSeek（便宜且翻译质量媲美人工）。
     - 也完美支持：Google Gemini、Kimi/Moonshot、通义千问、OpenAI、本地 Ollama 等。
2. **选择影视目录并提取**：
   - 切换到 **「媒体库」** 页面，选择要处理的影视目录，点击“扫描目录”。
   - 勾选你需要生成字幕的视频，点击 **「添加任务到队列」**。
   - 系统将在后台全自动处理：**智能提取音频 -> Whisper 语音识别 -> AI 批量并发翻译 -> 导出并关联中文字幕**！

---

## ✨ 核心特性亮点

- **⚡ 开箱即用**：镜像出厂内置 Whisper `tiny` 极速模型（仅约 75MB），无网/内网弱网环境无需漫长等待模型下载，秒开启动。
- **🎬 媒体服务器友好（中英双语字幕）**：
  - 支持自动合成**中英双语字幕**（中文在上，外文在下），看剧学习两不误。
  - 符合 Jellyfin / Emby / Plex 国际命名标准（支持 `.zh-CN.srt`、`.chi.default.srt` 等），播放器 100% 自动点亮中文字幕轨。
- **🚀 异步并发翻译加速**：
  - 采用多批次并发请求架构，整部 2 小时电影翻译时间直接缩短 **60%~75%**，拒绝漫长等待。
- **🛡️ 翻译断点续传（防浪费 Token）**：
  - 遇到断网或大模型 API 欠费中断？没关系！系统自动记录批次草稿，网络恢复后点击重试，**自动从上次断开的批次继续**，前期花费的 Token 零浪费。
- **🧠 深度思考模型兼容**：
  - 完美适配 DeepSeek-R1 等推理思考模型，自动清洗 `<think>` 标签，杜绝 JSON 格式损坏。
- **🔇 智能静音跳过（VAD 提速 40%）**：
  - 自动跳过长片段无对白背景音，时间戳严丝合缝对齐原画，大幅减轻 CPU 推理负载。
- **💾 NAS 内存守卫（自动休眠卸载）**：
  - 识别结束后，模型闲置 5 分钟自动从内存中彻底卸载，把几百兆甚至数 G 内存完整让还给 NAS 其它容器。
- **🔍 4K 蓝光防卡盘优化**：
  - 转写前通过 ffmpeg 秒级提取 16kHz 轻量音频流，Whisper 不再直接啃几十 GB 的大 MKV 文件，保护机械硬盘，告别 I/O 读盘卡顿。
- **🔄 内置字幕智能健康检测**：
  - 优先尝试视频内嵌软字幕，若检测到字幕残缺截断（如仅前几行广告），系统**自动无缝回退**到 Whisper 完整音频语音识别。

---

## ❓ 常见问题（FAQ）

### Q1：我需要下载很大很大的 Whisper 模型吗？
不需要！镜像内部已经直接打包好了 `tiny` 模型。如果你的 NAS CPU 性能不错或配备了 Intel 核显，想追求更高准确率，也可以在 Web 设置里一键下载 `small` 或 `base` 模型。

### Q2：中国大陆 NAS 用户下载更多模型或连接国外 API 超时怎么办？
只需在 `docker-compose.yml` 的 `environment` 下打开代理配置：
```yaml
environment:
  - HTTP_PROXY=http://192.168.1.100:7890
  - HTTPS_PROXY=http://192.168.1.100:7890
```
把其中的 `192.168.1.100:7890` 换成你局域网中运行的代理端口即可。

### Q3：如何开启群晖/绿联/N100等 NAS 的核显硬件加速？
如果你的 NAS 是 Intel 处理器（如 N100, J4125, N5105 等），只需在 `docker-compose.yml` 中把这两行前面的 `#` 删掉：
```yaml
devices:
  - /dev/dri:/dev/dri
```
保存后重新启动容器，系统将自动调用核显加速音频转码与模型计算，CPU 占用直线下降！

### Q4：如何更新到最新版本？
在 `docker-compose.yml` 所在目录执行：
```bash
docker compose pull && docker compose up -d
```

---

## 📄 授权协议
本项目遵循 [AGPL-3.0](LICENSE) 开源协议。
