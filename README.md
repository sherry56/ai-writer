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
- OpenAI Python SDK（写作模型默认 `gpt-5.5`，也可切换 Anthropic provider）
- 原生 HTML + Tailwind(CDN) + 原生 JS（无构建步骤）
- Docker / docker-compose

## 本地运行

```bash
pip install -r requirements.txt
cp .env.example .env       # 填入 OPENAI_API_KEY
uvicorn web.main:app --reload --port 8000
```

打开 http://localhost:8000

首次启动自动建库到 `data/db.sqlite`。

## Docker 部署

```bash
cp .env.example .env       # 填入 OPENAI_API_KEY
docker compose up -d --build
```

容器对外暴露 8000 端口。数据持久化在宿主机 `./data`（SQLite + 落盘文章 + 风格样本）, 配置在 `./config`。

如需放到反代后面（Nginx / Caddy）, 直接代理到 `http://127.0.0.1:8000` 即可,无 WebSocket 依赖。

### 数据迁移与上传图片

镜像只包含代码,不会包含本地运行数据。`data/db.sqlite`、`data/articles/`、`data/uploads/`、`data/style_lib/` 都需要通过服务器宿主机目录持久化或单独迁移。

本机已有数据迁到服务器示例:

```bash
# 本机项目目录
tar -czf ai-writer-data.tgz data
scp ai-writer-data.tgz user@server:/home/project/ai-writer/

# 服务器
cd /home/project/ai-writer
docker compose down
mkdir -p data/articles data/uploads data/style_lib config
tar -xzf ai-writer-data.tgz
docker compose pull
docker compose up -d --force-recreate
```

上传图片会写入容器内 `/app/data/uploads`,也就是宿主机挂载目录的 `data/uploads`。前端 markdown 使用 `/uploads/<文件名>` 显示图片。

如果图片上传成功但页面不显示:

```bash
# 服务器上确认文件确实落到宿主机 volume
ls -lah /home/project/ai-writer/data/uploads

# 如果 compose 映射为 "8001:8000",这里就测 8001
curl -I http://127.0.0.1:8001/uploads/<文件名>
```

如果前面 `curl` 是 200,但公网页面不显示,检查反向代理是否把 `/uploads/` 也代理到应用。最简单配置是把整个站点代理到容器端口,而不是只代理 `/api` 或 `/static`。

### 服务器端拉取镜像部署

每次 push 到 `main` 都会通过 GitHub Actions 构建并推送镜像到 `ghcr.io/sherry56/ai-writer:latest`。
服务器上不需要源码,只需要 `.env` + `docker-compose.prod.yml`:

```bash
# 首次：拷贝 .env.example 为 .env 并填 OPENAI_API_KEY
# 然后：
docker login ghcr.io -u sherry56            # 私有仓库才需要登录
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
