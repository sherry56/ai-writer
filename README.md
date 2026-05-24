# ai-writer

公众号 AI 写作 Agent。账号定位：大模型 / AI 领域中文公众号。
**v0.2 重构**：放弃热点抓取，专注自定义选题；前端从 Streamlit 切到 FastAPI + 原生 JS；支持 Docker 部署。

## 工作流

```
新建自定义选题（标题 + 备注 + 素材） → 生成大纲 → 人工微调 → 生成初稿 → 落盘 .md
```

所有 AI 调用都基于「标题 + 备注」。资料卡概念被取消,需要的背景材料请直接贴进备注栏。

## 技术栈

- Python 3.11+
- FastAPI + Uvicorn（后端 + 静态前端托管）
- SQLite + SQLAlchemy 2.0
- Anthropic Python SDK（写作模型默认 `claude-opus-4-7`）
- 原生 HTML + Tailwind(CDN) + 原生 JS（无构建步骤）
- Docker / docker-compose

## 本地运行

```bash
pip install -r requirements.txt
cp .env.example .env       # 填入 ANTHROPIC_API_KEY
uvicorn web.main:app --reload --port 8000
```

打开 http://localhost:8000

首次启动自动建库到 `data/db.sqlite`。

## Docker 部署

```bash
cp .env.example .env       # 填入 ANTHROPIC_API_KEY
docker compose up -d --build
```

容器对外暴露 8000 端口。数据持久化在宿主机 `./data`（SQLite + 落盘文章 + 风格样本）, 配置在 `./config`。

如需放到反代后面（Nginx / Caddy）, 直接代理到 `http://127.0.0.1:8000` 即可,无 WebSocket 依赖。

### 服务器端拉取镜像部署

每次 push 到 `main` 都会通过 GitHub Actions 构建并推送镜像到 `ghcr.io/<owner>/ai-writer:latest`。
服务器上不需要源码,只需要 `.env` + `docker-compose.prod.yml`:

```bash
# 首次：拷贝 .env.example 为 .env 并填 ANTHROPIC_API_KEY
# 然后：
docker login ghcr.io -u <github-user>       # 私有仓库才需要登录
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

镜像通过 `pull_policy: always` 每次启动都拉最新。
如需更新:`docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d`

## 项目结构

```
ai-writer/
├── web/
│   ├── main.py              # FastAPI 入口 + REST API
│   └── static/              # 前端静态资源（HTML / JS / CSS）
├── topic_pool/              # 选题增删改查
├── writer/
│   ├── prompts/             # 大纲 / 初稿 prompt
│   ├── templates/           # 内容类型模板（tutorial / product_review）
│   └── style_lib_loader.py  # 风格库加载（config/style.yaml + data/style_lib/*.md）
├── db/                      # SQLAlchemy 模型与会话
├── data/                    # SQLite + 落盘文章 + 风格样本（gitignore）
├── config/                  # style.yaml
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## API

| 方法   | 路径                              | 说明                       |
| ------ | --------------------------------- | -------------------------- |
| GET    | `/api/templates`                  | 列出内容类型               |
| GET    | `/api/topics?status=draft`        | 列出选题（可按状态过滤）   |
| POST   | `/api/topics`                     | 新建选题                   |
| GET    | `/api/topics/{id}`                | 查选题                     |
| PATCH  | `/api/topics/{id}`                | 改选题（含状态）           |
| DELETE | `/api/topics/{id}`                | 删选题                     |
| GET    | `/api/topics/{id}/article`        | 查文章（大纲 + 初稿）      |
| PATCH  | `/api/topics/{id}/article`        | 手动改大纲 / 初稿          |
| POST   | `/api/topics/{id}/outline`        | 生成大纲                   |
| POST   | `/api/topics/{id}/draft`          | 生成初稿（自动落盘 .md）   |

OpenAPI 文档:`http://localhost:8000/docs`

## 不做的 (v1 再说)

- 审校(事实核查、AI 味检测)
- 排版器集成
- 定时调度、多账号
- 用户系统(当前默认单用户,如需公网暴露请在反代层加 BasicAuth)
