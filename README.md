# EverOS for AstrBot

**为 AstrBot 集成 EverOS 自进化记忆引擎，让 Agent 拥有长期记忆与自我学习能力。**

---

## ✨ 功能

| 功能 | 说明 |
|------|------|
| 🔌 **服务桥接** | 连接独立部署的 EverOS 容器（REST API） |
| 🔧 **LLM 工具** | `everos_memorize` 写入记忆 / `everos_recall` 检索记忆 |
| 📊 **WebUI 管理面板** | 状态监控 + 记忆统计 + 快速测试 + 语义检索 |
| 🌐 **独立 WebUI 服务器** | 下载即用，无需手动启动，访问 `http://IP:18766` 即可 |
| ⚙️ **配置管理** | 在 AstrBot 后台直接配置连接参数 |
| 🌏 **中文原生支持** | 内置中文提示词，EverOS 提取的记忆为中文输出（需启用，见后文） |

---

## 📦 安装

### 1. 部署 EverOS 后端

本插件需要先有 EverOS 服务端在运行。[EverOS](https://github.com/EverMind-AI/EverOS) 是 EverMind 团队开发的自进化记忆系统，以下是三种部署方式：

#### 方式一：本机/服务器直接部署（推荐单机场景）

```bash
# 1. 安装 EverOS
pip install everos

# 2. 初始化，生成 .env 配置文件
everos init

# 3. 编辑 .env，填入大模型 API Key（支持 OpenAI / DeepSeek / 硅基流动等）
#    例如使用 DeepSeek：
#    在 .env 中设置：
#   LLM__MODEL=deepseek-chat
#   LLM__BASE_URL=https://api.deepseek.com/v1
#   LLM__API_KEY=sk-your-key-here

# 4. 启动 EverOS 服务（默认监听 127.0.0.1:8765）
everos server start

# 验证服务是否正常
curl http://127.0.0.1:8765/health
# 预期返回: {"status":"ok"}
```

> 如需修改监听地址为 `0.0.0.0`，编辑 `.env` 中的 `HOST=0.0.0.0`

#### 方式二：Docker 部署（推荐生产环境）

```bash
# 1. 创建 EverOS 数据目录
mkdir -p ~/everos-data && cd ~/everos-data

# 2. 创建 docker-compose.yml
cat > docker-compose.yml << 'EOF'
version: '3.8'
services:
  everos:
    image: evermind/everos:latest
    container_name: everos
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - ./data:/app/data
      - ./.env:/app/.env
    environment:
      - TZ=Asia/Shanghai
EOF

# 3. 创建 .env 配置文件
cat > .env << 'EOF'
LLM__MODEL=deepseek-chat
LLM__BASE_URL=https://api.deepseek.com/v1
LLM__API_KEY=sk-your-key-here
HOST=0.0.0.0
PORT=8765
EOF

# 4. 启动
docker-compose up -d

# 验证
curl http://127.0.0.1:8765/health
```

> 如果使用其他兼容 OpenAI 的 API（如硅基流动），只需改 `LLM__BASE_URL` 和 `LLM__API_KEY` 即可。

#### 方式三：Docker 与 AstrBot 同机部署（本项目典型架构）

若 AstrBot 已运行在 Docker 容器中，将 EverOS 部署在宿主机上（或另一个容器），
通过 `host.docker.internal` 或内网 IP 互通：

```bash
# 宿主机上直接部署 EverOS
pip install everos
everos init
# 编辑 .env，将 HOST 设为 0.0.0.0
everos server start

# 验证 AstrBot 容器内能否访问
docker exec astrbot curl -s http://host.docker.internal:8765/health
```

### 2. 安装本插件

EverOS 部署完成后，安装本插件将其接入 AstrBot。

#### 通过 AstrBot 插件市场安装
AstrBot 后台 → 插件市场 → 搜索 `everos` → 一键安装

#### 手动安装
```bash
# 方式一：克隆仓库
cd /AstrBot/data/plugins/
git clone https://github.com/Masumeiki/astrbot_plugin_everos_integration.git

# 方式二：从 GitHub Releases 下载最新压缩包（覆盖更新）
# 前往 https://github.com/Masumeiki/astrbot_plugin_everos_integration/releases
# 下载 Source code (zip) 后解压到插件目录
wget https://github.com/Masumeiki/astrbot_plugin_everos_integration/archive/refs/heads/main.zip
unzip -o main.zip
# 如果目录已存在，先删除旧版再覆盖
rm -rf astrbot_plugin_everos_integration
mv astrbot_plugin_everos_integration-main astrbot_plugin_everos_integration
rm main.zip
```

#### 安装依赖
```bash
pip install httpx
# 可选：如需手动启动 server.py 独立版
pip install fastapi uvicorn
```

#### 配置连接
在 AstrBot 后台 → 插件配置 → 设置 `everos_base_url` 指向你的 EverOS 服务地址。
- 同机部署：`http://127.0.0.1:8765`
- Docker 互通：`http://host.docker.internal:8765`（Linux 下可能需要配置 `--add-host` 或使用宿主机内网 IP）
- 远程服务器：`http://<服务器IP>:8765`

> 默认配置下，插件启动后会自动监听 `0.0.0.0:18766`，浏览器访问 `http://<服务器IP>:18766/` 即可打开独立 Dashboard。

---

## ⚙️ 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `everos_base_url` | `http://127.0.0.1:8765` | EverOS 服务地址 |
| `enable_tools` | `true` | 启用 LLM 工具 |
| `enable_webui` | `true` | 启用 AstrBot 内嵌管理面板 |
| `standalone_webui_enabled` | `true` | 启用独立 WebUI 服务器 |
| `standalone_webui_host` | `0.0.0.0` | 独立 WebUI 监听地址 |
| `standalone_webui_port` | `18766` | 独立 WebUI 访问端口 |
| `app_id` | `astrbot` | 应用标识 |
| `project_id` | `default` | 项目标识 |
| `isolation_personas` | `""` | 记忆隔离白名单（逗号分隔）。在此列表里的人格使用独立记忆空间，列表外的人格共享全部记忆。例如 `白芷,欣雨` |

---

## 🎮 使用

### 命令

- `/everos` — 查看连接状态

### LLM 工具

Agent 可调用：
- `everos_memorize` — 将重要信息写入 EverOS 长期记忆
- `everos_recall` — 从 EverOS 检索相关记忆

### WebUI（两种方式）

**方式一：AstrBot 内嵌**
安装后在 AstrBot 后台侧边栏可见 **EverOS Bridge**，点击打开管理面板。

**方式二：独立端口（推荐）**
插件安装后自动启动独立 WebUI 服务器，浏览器直接访问：
```
http://<服务器IP>:18766/
```
即可使用功能完整的 Dashboard。

---

## 🏗 架构

```
AstrBot 容器
  └── everos 插件
        ├── main.py                    # 插件入口
        ├── core/
        │   ├── everos_client.py       # HTTP 客户端
        │   ├── config_manager.py      # 配置管理
        │   └── standalone_server.py   # 独立 WebUI 服务器
        ├── tools/
        │   └── everos_tools.py        # LLM 工具
        └── pages/everos-dashboard/
            ├── index.html             # 管理面板（v2）
            ├── style.css              # 翡色主调设计系统
            ├── app.js                 # 双端统一前端
            └── server.py              # [可选] 手动启动独立版
```

### 通信流程

```
浏览器 ──→ :18766 ──→ standalone_server.py ──→ everos 后端(:8765)
                            │
AstrBot 后台 ──→ 插件内嵌页面 ──→ register_web_api ──→ everos 后端
```

---

## 🌏 中文支持

EverOS 默认使用英文提示词来提炼记忆，提取结果为英文。本插件已配置中文提示词，需在 EverOS 容器内启用：

```bash
# 进入 EverOS 容器
docker exec -it everos sh

# 编辑提示词配置文件
vi /usr/local/lib/python3.12/site-packages/everos/config/prompt_slots/episode_extract.yaml

# 将 enabled 改为 true，template 填入以下内容：
```

```yaml
enabled: true
template: |
  你是一位情节记忆生成专家。

  关键语言规则：你必须使用与输入对话内容相同语言输出。输入为中文则输出中文，输入为英文则输出英文。

  请将以下对话内容转换为情节记忆。

  对话开始时间：{conversation_start_time}
  对话内容：
  {conversation}

  额外指令：{custom_instructions}

  输出格式：{"title": str, "content": str}
```

```bash
# 修改后重启 EverOS 使其生效
docker restart everos
```

此后新写入的对话会产生中文记忆摘要，已存在的英文记忆不会自动重写。

---

## 📄 License

Apache 2.0
