# 供应链交货处理系统

这是一个用于处理供应商交货 Excel 的内部 Web 系统。系统按批次接收多个交货文件，共享同一份采购余额，完成采购匹配、异常审阅、人工拆分和模板化导出。

后端保留原有 Python CLI，并与 Web 共用 pandas/openpyxl 业务逻辑。部署形态是 React + FastAPI + PostgreSQL + 单 Worker + Docker Compose，不依赖 Celery 或 Redis。

## 已实现功能

- 管理员和操作员登录，权限分离。
- 采购、商品、供应商、库位和导出模板五类资料目录，支持当前版本摘要、数据预览、原文件下载、替换上传和历史版本。
- 库位资料支持服务端持久化编辑草稿、逐行新增/修改/删除、筛选、Excel 差异预览、校验和发布新版本。
- 管理员维护按“基础资料、用户账号、操作记录”分区，当前资料、维护入口和已维护内容集中展示。
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
UI_UX_OPTIMIZATION_PLAN.md 操作流程与 UI 优化方案及实施状态
AGENTS.md                Codex CLI 自动读取的项目规则
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
MAX_UPLOAD_BYTES=20971520
IMPORT_CANDIDATE_TTL_SECONDS=900
```

`MAX_UPLOAD_BYTES` 是单个上传文件的字节上限，默认 20 MiB；`IMPORT_CANDIDATE_TTL_SECONDS` 是库位草稿 Excel 导入预览的有效期，默认 900 秒。

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
2. 在“管理员维护 → 基础资料”中确认五类资料的当前版本、摘要和预览；缺失时上传并启用对应版本。
3. 库位资料需要人工维护时进入“库位维护工作区”，系统会在服务器创建或继续唯一编辑草稿；逐行修改会自动保存，校验通过后再发布为新的当前版本。
4. 创建批次，上传一个或多个供应商交货文件。
5. 调整文件顺序并执行预检。
6. 启动计算，等待 Worker 完成任务。
7. 审阅待处理记录，按需拆分。
8. 生成单文件结果和批次 ZIP。

新版界面把上述操作组织为“准备文件 → 预检 → 计算结果 → 异常审校 → 导出下载”五步工作台。完整方案和实施状态见 [UI_UX_OPTIMIZATION_PLAN.md](UI_UX_OPTIMIZATION_PLAN.md)。

输入文件不会保存在 Git 仓库中，需要在部署后通过管理页面上传。

## 脱敏验收数据

仓库提供一个固定场景生成器，可在任意新环境生成七份脱敏 Excel：

```bash
source .venv/bin/activate
python scripts/generate_acceptance_data.py --output-dir acceptance_data
```

生成内容包括五类输入版本和两份 `KuangBiao` 交货文件。采购未交量为 100，两份交货文件各交货 80。按 A、B 顺序计算时，预期结果是：

```text
交货总量：160
可导入总量：100
待处理总量：60
第一个文件可导入：80
第二个文件可导入：20
```

`acceptance_data/` 仅用于本机验收，不应提交到 Git。

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

2026-07-22 在 `feature/admin-maintenance` 工作树完成的当前基线是 Python 113/113 通过、前端 6 个测试文件共 59/59 通过、`pip check` 无冲突，生产构建成功。构建仍有约 1.2 MB 单包体积提示，不影响当前功能。管理员维护已用 Google Chrome 完成 1280×800、1440×900 和 1920×1080 PC 端验收，证据在 `design/admin-maintenance-qa/`。

## 项目完成标准

只有以下四类门槛全部通过，才能把项目标记为完成或生产可用。

### 代码门槛

- 从 GitHub 全新克隆，不复制旧机器的 `src_data`、虚拟环境或缓存。
- Python 依赖安装成功，全部测试通过且 `pip check` 无冲突。
- 前端 `npm ci`、测试和生产构建通过。
- 测试不依赖未提交的业务文件或绝对路径。

### Linux 部署门槛

- PostgreSQL、API、单 Worker 和 Web 四个容器正常运行。
- `/health` 返回成功，容器日志没有 traceback。
- 容器重启后用户、输入版本、批次和上传文件仍存在。
- 外部 HTTPS 代理能够安全访问 Web，HTTP 不直接暴露到公网。

### 业务验收门槛

- 管理员可以上传并启用五类输入版本。
- 两份交货文件按界面顺序共享采购余额，预期数量与验收场景一致。
- 预检、计算、异常拆分、数量守恒、单文件导出和批次 ZIP 全部通过。
- 原有 CLI、仓库优先级、锁仓匹配和模板 A:G 格式保持兼容。

### 运维门槛

- PostgreSQL 和文件卷有成对备份，并至少完成一次恢复演练。
- 管理员密码、`.env`、业务 Excel 和导出文件未进入 Git。
- 数据库改表有可执行的迁移方案。
- README、交接文档和实际部署命令保持一致。

当前代码门槛已通过自动化验证；Linux 目标机已从 `feature/admin-maintenance` 工作树完成 Compose 重建，数据库和 API 健康，Worker 与 Web 正常运行，本机和外部 HTTPS 健康接口均返回 `{"status":"ok"}`，登录后的版本列表只读接口成功。管理员维护 PC 端 Chrome 验收已通过，过程中发现的发布警告弹窗首屏操作不可达问题和库位草稿基线漂移风险均已修复并复验。现网没有编辑中的库位草稿，因此完整写流程使用隔离 PostgreSQL QA 和临时 SQLite 数据库验收；PostgreSQL 另完成 12 轮草稿打开/版本启用竞争和 12 轮草稿打开/发布竞争验收，没有向生产库写入测试草稿。批次并发上传排序和草稿恢复审计的最新修复已通过 SQLite 与临时 PostgreSQL 验证，但尚未部署到正式环境。完整脱敏业务场景以及数据库/文件卷成对备份恢复等运维门槛仍需完成，完成前不要宣称生产可用。

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
