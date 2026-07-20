# 供应链交货处理系统 Linux/Codex CLI 交接

- 更新时间：2026-07-20
- 仓库：`https://github.com/songtu2025/deliverynote.git`
- 默认分支：`master`
- 实现基线提交：`ebde9ea Initial delivery note web application`

## 1. 接手时先做什么

在 Linux 机器上执行：

```bash
git clone https://github.com/songtu2025/deliverynote.git
cd deliverynote
git status -sb
git log -3 --oneline --decorate
```

正常情况下应位于 `master`，工作区干净。接着完整阅读：

1. `README.md`
2. `HANDOFF_WEB_UPGRADE.md`
3. `compose.yaml`
4. `.env.example`

不要从旧方案重新搭项目。前后端、Worker 和部署配置已经实现，应从当前代码和测试结果继续。

## 2. 当前完成状态

已经完成：

- 原有单文件 CLI 及 Excel 模板导出。
- 多文件批次共享采购余额，并严格按用户调整后的顺序扣减。
- 批次级数量守恒检查。
- 异常记录拆分，可区分可导入部分和仍待处理部分。
- FastAPI 登录、用户、输入版本、批次、任务、异常、拆分和下载接口。
- PostgreSQL/SQLite SQLAlchemy 模型。
- 独立 Worker、任务租约、心跳、超时回收和失败重试。
- 每个来源文件单独导出及批次 ZIP。
- React + TypeScript + Ant Design 操作界面。
- Docker Compose、Nginx 和外部 HTTPS 代理接入方式。

最近验证结果：

```text
Python unittest: 39/39 passed
Frontend Vitest: 1/1 passed
Frontend production build: passed
pip check: passed
Compose YAML static check: passed
PostgreSQL DDL compile check: passed
```

Windows 开发机没有安装 Docker，因此尚未完成 Linux 上的真实容器启动和 PostgreSQL 运行时验收。这是接手后的第一项任务。

## 3. 代码结构

| 路径 | 作用 |
| --- | --- |
| `delivery_note/pipeline.py` | SKU/站点匹配、采购过滤、仓库分配、异常保留和数量守恒 |
| `delivery_note/application.py` | 多文件共享余额、批次顺序、备注生成和拆分投影 |
| `delivery_note/excel_io.py` | Excel 读取、模板校验和结果写出 |
| `delivery_note/config.py` | 供应商识别、仓库优先级和交货备注 |
| `delivery_note/cli.py` | 原有单文件 CLI |
| `delivery_note/web/models.py` | 用户、版本、批次、文件、异常、拆分、任务和审计表 |
| `delivery_note/web/api.py` | FastAPI 应用和全部接口 |
| `delivery_note/worker.py` | 计算、导出、任务租约和超时恢复 |
| `frontend/src/` | 登录、批次、审阅拆分和管理员页面 |
| `tests/` | Python 单元、API 和 Worker 端到端测试 |
| `compose.yaml` | PostgreSQL、API、Worker 和 Web 服务 |

Web 和 CLI 必须继续调用同一套核心业务函数，不要复制一套仅供 API 使用的采购匹配逻辑。

## 4. 不能破坏的业务规则

1. 同一批次只加载一份采购数据，多个交货文件按界面顺序连续消耗采购余额。
2. 调换文件顺序可以改变余额归属，但不能改变批次交货总量。
3. 超出采购余额、无法匹配或存在歧义的数量必须进入待处理，不可丢弃。
4. 供应商本地仓优先，其他仓库使用确定性顺序。
5. 商品锁仓标识用于解决同一 SKU/站点的匹配歧义。
6. 拆分数量必须全部大于零，拆分总和必须等于原待处理数量。
7. 始终满足：`交货总量 = 可导入总量 + 待处理总量`。
8. 任一文件计算失败时，不得持久化该批次的部分计算结果。
9. 导出保持现有 A:G 字段、模板样式、交货备注和 CLI 命名兼容。
10. 不在不同批次间延续采购扣减，不做 ERP 回写。

如果测试样例的中文字段损坏，应修正测试数据，不要修改正式业务逻辑去兼容错误列名。

## 5. 输入文件约定

五类版本化输入：

- 采购：包含 `单据状态`、`供应商`、`SKU`、`平台站点`、`目的仓`、`未交量`。
- 商品：包含 `SKU`、`店铺/站点`、`品类A`、`锁仓MKSU`。
- 供应商：包含 `供应商编号`、`供应商名称`、`状态`。
- 库位：工作表 `MSKU_视图`，包含 `店铺-站点`、`积加SKU`、`MSKU` 等定位字段。
- 模板：第二行是正式 A:G 导入表头，第三行保留样例格式。

交货文件使用 `汇总` 工作表。解析器会识别以 `SKU` 结尾的 SKU 表头和以 `站` 结尾的站点列。供应商根据文件名和启用的供应商资料识别，不要在代码中新增按文件名写死的供应商分支。

正式导入字段：

```text
*目的仓
*供应商编码
*SKU
*本次交货量
*站点
单据备注
交货备注
```

业务 Excel、`.env`、数据库和导出结果都不在 Git 仓库中。

## 6. Linux 部署验收

先按 `README.md` 创建 `.env` 并启动：

```bash
docker compose config
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8080/health
```

验收顺序：

1. `db`、`api`、`worker`、`web` 四个服务都处于运行状态，API 健康检查通过。
2. 使用管理员账号登录。
3. 上传并启用五类输入版本。
4. 创建含两个交货文件的批次，调整顺序并通过预检。
5. 执行计算，确认任务从 `queued`、`running` 到 `succeeded`。
6. 用采购余额不足的样例确认第一个文件先消耗余额，第二个文件只获得剩余量。
7. 对一条待处理记录进行拆分，确认拆分前后数量守恒。
8. 导出两个来源结果和批次 ZIP，打开 Excel 检查表头、样式和数量。
9. 查看 `api`、`worker` 日志，确认没有 traceback 或重复领取。
10. 重启服务后再次登录，确认 PostgreSQL 数据和上传文件仍存在。

常用命令：

```bash
docker compose logs -f api worker web
docker compose restart worker
docker compose down
docker compose up -d
```

不要执行 `docker compose down -v`。该命令会删除数据库和文件卷。

## 7. 当前已知边界

- Compose 只启动一个 Worker。这是当前确认范围，不要在没有并发测试前直接扩容多个 Worker。
- Web 只绑定 `127.0.0.1`，正式访问需要外部 HTTPS 反向代理。
- 数据库目前通过 SQLAlchemy `create_all()` 建表，没有正式迁移工具。首次部署可以使用；后续改表前应先引入最小迁移流程。
- 自动文件过期清理、数据库定时备份和文件卷备份尚未实现。
- 管理员账号只在数据库不存在同名用户时创建。修改 `.env` 不会重置已有管理员密码。
- PostgreSQL DDL 已做离线编译检查，但真实 PostgreSQL 端到端运行需要在 Linux 部署中验证。
- 前端生产构建存在单包约 1.1 MB 的体积提示，当前不影响功能，不要为了消除提示优先引入复杂拆包。
- 仓库是公开仓库，禁止提交业务数据、真实密码、Token 或客户文件。

## 8. 测试命令

Python：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m pip check
```

前端：

```bash
cd frontend
npm ci
npm run test
npm run build
```

业务逻辑、API、Worker 或模型发生变化后，必须运行全部 Python 测试。前端变更至少运行 `npm run test` 和 `npm run build`。

## 9. Git 和 Codex CLI 工作规则

- 开始前运行 `git status -sb`，确认没有他人的未提交改动。
- 不要使用 `git reset --hard`、`git clean` 或批量删除来处理不熟悉的文件。
- 只提交源码、测试和部署文档；`.env`、Excel、数据库、日志和输出文件必须保持忽略。
- 修改采购匹配、仓库优先级、拆分或导出前，先阅读现有测试和调用链。
- 先复现问题，再做最小修改；每个阶段都运行对应测试。
- 遵循 KISS，不引入 Redis、Celery、微服务拆分或当前范围外的平台组件。

在已经安装并登录 Codex CLI 的 Linux 机器上：

```bash
cd deliverynote
codex
```

建议给 Codex 的首条指令：

> 请先完整阅读 README.md 和 HANDOFF_WEB_UPGRADE.md，然后检查 git status、当前提交、compose.yaml、.env.example 和现有测试。当前第一目标是完成 Linux Docker Compose 实机部署验收：启动 PostgreSQL、API、单 Worker 和 Web，验证健康检查、登录、五类版本上传、双文件共享采购余额、拆分审校、单文件与 ZIP 导出，以及容器重启后的数据持久化。不要从头重建，不要改变已有采购匹配、超量保留、锁仓优先、导出格式和 CLI 行为。发现问题时先给出复现证据，再做最小修复；每完成一个阶段运行相应测试并汇报结果。不要提交 .env、Excel、数据库或输出文件。

## 10. Linux 验收后的建议顺序

1. 记录真实 Docker/PostgreSQL 部署中发现的问题并补回归测试。
2. 验证外部 HTTPS 代理、上传大小和长任务日志。
3. 建立 PostgreSQL 与文件卷的成对备份流程。
4. 在确实需要改表时引入简单的数据库迁移方案。
5. 根据实际操作反馈补前端关键流程测试，不做无业务依据的界面重构。

完成 Linux 实测前，不要把项目状态标记为生产可用。
