# 供应链交货处理系统

这是一个用于处理供应商交货 Excel 的内部 Web 系统。系统按批次接收多个交货文件，共享同一份采购余额，完成采购匹配、异常审阅、人工拆分和模板化导出。

后端保留原有 Python CLI，并与 Web 共用 pandas/openpyxl 业务逻辑。部署形态是 React + FastAPI + PostgreSQL + 单 Worker + Docker Compose，不依赖 Celery 或 Redis。

## 已实现功能

- 管理员和操作员登录，权限分离。
- 采购、商品、供应商、库位和导出模板五类版本管理。
- 创建批次、上传多个交货文件和调整处理顺序。
- 按界面顺序共享并连续扣减采购余额。
- 预检 Excel 内容、供应商识别和模板结构。
- 查看异常，将一条待处理记录拆成可导入和仍待处理部分。
- 后台计算、任务心跳、超时恢复和失败重试。
- 每个来源文件单独导出，同时生成批次 ZIP。
- 保留原有单文件 CLI 和 Excel 模板格式。

系统始终要求：

```text
交货总量 = 可导入总量 + 待处理总量
```

## 目录

```text
delivery_note/          Python 核心逻辑、FastAPI 和 Worker
delivery_note/web/      数据库模型、认证和 API
frontend/               React + TypeScript + Ant Design 前端
tests/                  Python 单元与端到端测试
compose.yaml            PostgreSQL、API、Worker、Web 编排
Dockerfile              API 和 Worker 镜像
.env.example            部署环境变量示例
HANDOFF_WEB_UPGRADE.md   当前状态和 Codex CLI 续开发交接
```

## Linux Docker 部署

机器需要安装 Git、Docker Engine 和 Docker Compose 插件。

```bash
git clone https://github.com/songtu2025/deliverynote.git
cd deliverynote
cp .env.example .env
```

编辑 `.env`，至少替换数据库密码和管理员密码：

```env
POSTGRES_PASSWORD=设置一个强数据库密码
ADMIN_USERNAME=admin
ADMIN_PASSWORD=设置一个强管理员密码
WEB_PORT=8080
CORS_ORIGINS=http://localhost:8080
```

先检查 Compose 配置，再构建并启动：

```bash
docker compose config
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8080/health
```

健康检查应返回：

```json
{"status":"ok"}
```

查看日志：

```bash
docker compose logs -f api worker web
```

当前 Web 端口只绑定到服务器的 `127.0.0.1`，不会直接暴露到公网。临时测试可从自己的电脑建立 SSH 隧道：

```bash
ssh -L 8080:127.0.0.1:8080 用户名@服务器地址
```

然后访问 `http://localhost:8080`。正式环境应由宿主机 Nginx、Caddy 或云负载均衡器提供 HTTPS，再反向代理到 `127.0.0.1:8080`，同时把 `CORS_ORIGINS` 改为实际的 HTTPS 域名。

## 首次使用

1. 使用 `.env` 中的管理员账号登录。
2. 在“管理员维护”中分别上传并启用采购、商品、供应商、库位和导出模板。
3. 创建批次，上传一个或多个供应商交货文件。
4. 调整文件顺序并执行预检。
5. 启动计算，等待 Worker 完成任务。
6. 审阅待处理记录，按需拆分。
7. 生成单文件结果和批次 ZIP。

输入文件不会保存在 Git 仓库中，需要在部署后通过管理页面上传。

## 本地开发

建议使用 Python 3.11 和 Node.js 22，与 Docker 镜像保持一致。

### 后端和 Worker

Linux 下创建虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

本地开发可以使用 SQLite：

```bash
export DATABASE_URL='sqlite+pysqlite:///delivery_note.db'
export STORAGE_ROOT='storage'
export ADMIN_USERNAME='admin'
export ADMIN_PASSWORD='change-this-password'

uvicorn delivery_note.web.api:create_app --factory --reload --host 127.0.0.1 --port 8000
```

另开一个终端启动 Worker：

```bash
source .venv/bin/activate
export DATABASE_URL='sqlite+pysqlite:///delivery_note.db'
export STORAGE_ROOT='storage'
python -m delivery_note.worker
```

SQLite 只用于本地开发和测试，Docker 部署使用 PostgreSQL。

### 前端

```bash
cd frontend
npm ci
npm run dev
```

Vite 默认监听 `5173`，并将 `/api` 和 `/health` 代理到 `127.0.0.1:8000`。

## 测试

后端测试必须使用项目虚拟环境：

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
python -m pip check
```

前端测试和生产构建：

```bash
cd frontend
npm ci
npm run test
npm run build
```

当前基线是 Python 39/39 通过、前端 1/1 通过，生产构建成功。

## 原有单文件 CLI

```bash
python -m delivery_note.cli \
  --delivery /path/to/delivery.xlsx \
  --purchase /path/to/purchase.xlsx \
  --product-info /path/to/product.xlsx \
  --supplier-info /path/to/supplier.xlsx \
  --position-data /path/to/position.xlsx \
  --template /path/to/template.xlsx \
  --output-dir outputs
```

CLI 每次只处理一个交货文件。需要在多个文件之间共享采购余额时，应使用 Web 批次流程。

## 更新、停止和备份

更新代码：

```bash
git pull --ff-only
docker compose up -d --build
```

停止服务但保留数据：

```bash
docker compose down
```

不要执行 `docker compose down -v`，该命令会删除 PostgreSQL 和上传文件的数据卷。

数据库备份示例：

```bash
docker compose exec -T db pg_dump -U delivery_note delivery_note > delivery_note.sql
```

还需要为 Docker 的 `delivery_data` 卷配置定期快照或文件备份。数据库和文件卷必须一起备份，单独恢复其中一项可能造成记录与文件不一致。

## 安全提醒

- 仓库是公开仓库，不要提交 `.env`、业务 Excel、数据库、导出结果或真实账号密码。
- 正式环境必须使用 HTTPS。
- 管理员密码只在首次创建管理员时使用。数据库中已经存在同名管理员后，修改 `.env` 不会重置密码。
- 上传文件和数据库位于 Docker 数据卷中，清理容器前先确认备份。

继续开发前请阅读 [HANDOFF_WEB_UPGRADE.md](HANDOFF_WEB_UPGRADE.md)。
