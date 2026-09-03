# DeliveryNote

DeliveryNote 是一个面向内部供应链团队的单据处理系统，用于把供应商交货单或自营仓质检交货单转换为可导入积加的 Excel，并保留所有需要人工确认的数据。

系统提供两条独立流程：

| 流程 | 输入 | 输出 |
| --- | --- | --- |
| 交货批次 | 一份或多份供应商交货单，以及采购、商品、供应商、库位资料 | 标准 A:G 交货导入表、待处理明细、合并 Excel 或分文件 ZIP |
| 自营仓入库 | 一份质检交货单，以及积加待入库数据 | 积加批量入库表和待处理明细 |

Web 端适合日常批次操作，CLI 保留单文件交货处理能力。当前系统面向少量 PC 用户，不做 ERP 回写，也不跨批次延续采购余额。

## 核心能力

- 在同一交货批次内按用户确认的文件顺序连续扣减采购余额；
- 从积加 OpenAPI 同步采购数据和自营仓待入库数据；
- 对同步结果进行问题检查、差异预览和版本启用；
- 自动匹配供应商、SKU、站点、采购需求和目标仓库；
- 完整保留超量、未匹配和歧义数量，供人工审校；
- 支持待处理数量拆分、站点歧义选择和重新计算；
- 版本化管理基础资料、交货超收规则和自营仓超收规则；
- 保留用户管理、操作记录和批次结果追溯。

## 业务规则

以下规则是实现和维护时必须保持的产品契约。

### 交货批次

1. 同一批次按文件顺序共享采购余额，前序文件优先扣减。
2. 调整文件顺序可以改变余额归属，但不能改变批次交货总量。
3. 供应商成品本地仓优先，其他仓库按确定性顺序分配。
4. 商品资料中的 `锁仓MKSU` 用于解决 SKU 和站点歧义，不得擅自改名。
5. 超收规则先于新批次锁定；旧批次不追溯规则或基础资料变化。
6. 始终满足：

   ```text
   交货总量 = 可导入总量 + 待处理总量
   ```

### 自营仓入库

1. 每个批次使用一份质检交货单和一个已启用的待入库数据版本。
2. 可收数量按关联采购单顺序分配，规则内超收和规则外数量分别记录。
3. 站点不唯一时必须由用户选择后重新计算。
4. 始终满足：

   ```text
   质检合格总量 = 可入库总量 + 待处理总量
   ```

### 通用约束

- 待处理拆分数量必须为正，拆分总和必须等于原待处理数量；
- 任一文件计算失败时，不保存该批次的部分计算结果；
- 所有无法自动处理的数量必须进入待处理，不能静默丢弃；
- 不跨批次保存采购扣减状态，不向积加或其他 ERP 回写数据；
- 测试数据列名损坏时修正测试数据，不放宽正式业务校验。

## 快速启动

### 环境要求

- Docker Engine
- Docker Compose 插件
- 推荐使用 Linux 部署；正式环境应由 HTTPS 反向代理提供访问

### 1. 准备配置

```bash
git clone https://github.com/songtu2025/deliverynote.git
cd deliverynote
cp .env.example .env
```

至少修改 `.env` 中的两个密码：

```dotenv
POSTGRES_PASSWORD=replace-with-a-strong-password
ADMIN_PASSWORD=replace-with-a-strong-password
```

常用配置如下：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | 无 | PostgreSQL 业务账号密码，必填 |
| `ADMIN_USERNAME` | `admin` | 首次建库时创建的管理员账号 |
| `ADMIN_PASSWORD` | 无 | 首次建库时创建的管理员密码，必填 |
| `WEB_PORT` | `8080` | Web 在宿主机回环地址上的端口 |
| `CORS_ORIGINS` | `http://localhost:8080` | 允许访问 API 的 Web 来源 |
| `MAX_UPLOAD_BYTES` | `20971520` | 单次上传大小上限，单位为字节 |
| `IMPORT_CANDIDATE_TTL_SECONDS` | `900` | 库位导入预览有效时间 |
| `POSITION_FRAME_CACHE_SIZE` | `8` | API 进程缓存的库位版本数量 |
| `GERPGO_API_BASE_URL` | `https://open.gerpgo.com` | 积加 OpenAPI 地址 |
| `GERPGO_APP_ID` | 空 | 积加应用 ID，不使用同步时可留空 |
| `GERPGO_APP_KEY` | 空 | 积加应用密钥，不使用同步时可留空 |

积加凭据也可以由管理员登录后在“管理员维护 → 接口配置”中测试并保存。应用内保存的配置位于业务数据卷，不写回 `.env`。

> 修改 `.env` 中的初始管理员密码不会重置数据库里已经存在的账号，请在系统内执行密码重置。

### 2. 启动服务

```bash
docker compose config
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8080/health
```

健康检查成功时返回：

```json
{"status":"ok"}
```

如修改了 `WEB_PORT`，请同步替换健康检查端口。

Compose 会启动六个服务：PostgreSQL、API、Web、批次 Worker、采购同步 Worker 和待入库同步 Worker。上传文件、同步结果和导出文件保存在 `delivery_data` 数据卷，数据库保存在 `postgres_data` 数据卷。

停止服务但保留数据：

```bash
docker compose down
```

不要执行 `docker compose down -v`，该命令会删除数据库和业务文件数据卷。

## Web 使用流程

### 首次准备

管理员先登录系统，在“管理员维护”中确认基础资料版本：

| 流程 | 新建批次前必须启用的资料 |
| --- | --- |
| 交货批次 | 采购需求、商品信息、供应商资料、MSKU 定位、导出模板 |
| 自营仓入库 | 商品信息、供应商资料、待入库 API 数据、积加入库模板 |

两个导出模板在首次启动时由系统内置文件初始化。采购需求可以上传或通过积加接口同步；自营仓待入库数据通过积加接口同步。基础资料和规则都在创建批次时锁定，之后启用新版本不会改变已有批次。

### 交货批次

```text
同步或维护基础资料
  → 创建批次并上传交货文件
  → 调整文件顺序
  → 预检
  → 后台计算
  → 审校并拆分待处理数量
  → 导出 Excel 或 ZIP
```

交货文件必须包含 `汇总` 工作表。供应商根据文件名和已启用的供应商资料识别；无法唯一识别时，预检会失败。

正式导入区域固定为 A:G：

| 列 | 字段 |
| --- | --- |
| A | `*目的仓` |
| B | `*供应商编码` |
| C | `*SKU` |
| D | `*本次交货量` |
| E | `*站点` |
| F | `单据备注` |
| G | `交货备注` |

模板第 3 行示例和样式会被保留，正式数据从第 4 行开始。

### 自营仓入库

```text
同步并启用积加待入库数据
  → 创建自营仓批次并上传质检交货单
  → 预检
  → 后台计算
  → 处理站点歧义或超量
  → 导出积加批量入库表
```

质检交货单必须包含 `明细` 工作表，并提供 `积加SKU`、`实收数量`、`站点` 和 `交货单号`。系统只读取积加数据，不会自动提交入库结果。

### 权限

| 能力 | 操作员 | 管理员 |
| --- | :---: | :---: |
| 创建、计算、审校和导出批次 | ✓ | ✓ |
| 查看和发布超收规则 | ✓ | ✓ |
| 发起数据同步并查看结果 | ✓ | ✓ |
| 启用自营仓待入库候选版本 | ✓ | ✓ |
| 启用普通基础资料和采购候选版本 | — | ✓ |
| 维护基础资料、接口配置和用户 | — | ✓ |
| 删除批次、查看最近 200 条操作记录 | — | ✓ |

停用账号后，已有登录状态立即失效。

## 系统结构

```mermaid
flowchart LR
    U[PC 浏览器] --> W[React / Nginx]
    W --> A[FastAPI]
    A --> D[(PostgreSQL)]
    A --> F[(共享文件卷)]
    B[批次 Worker] --> D
    B --> F
    P[采购同步 Worker] --> D
    P --> F
    P --> G[积加 OpenAPI]
    I[待入库同步 Worker] --> D
    I --> F
    I --> G
    C[单文件 CLI] --> K[delivery_note 核心逻辑]
    A --> K
    B --> K
```

主要目录：

| 路径 | 职责 |
| --- | --- |
| `delivery_note/pipeline.py` | 交货匹配、采购余额和仓库分配 |
| `delivery_note/application.py` | 多文件批次、共享余额和拆分投影 |
| `delivery_note/self_operated_inbound.py` | 自营仓入库分配和数量守恒 |
| `delivery_note/excel_io.py` | Excel 读取、校验和导出 |
| `delivery_note/gerpgo.py` | 积加 OpenAPI 客户端 |
| `delivery_note/worker.py` | 批次计算、导出和数据同步任务 |
| `delivery_note/web/` | FastAPI、鉴权、模型和后台维护 |
| `frontend/src/` | React PC 操作界面 |
| `tests/` | 后端和核心业务测试 |

Web、Worker 和 CLI 共用 `delivery_note` 核心逻辑，不应复制采购匹配或数量分配代码。

## 单文件 CLI

CLI 只处理一份供应商交货单：

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

需要让多份交货文件共享采购余额时，必须使用 Web 批次流程。

## 开发与验证

推荐使用 Python 3.11 和 Node.js 22。

后端与核心逻辑：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m ruff check delivery_note tests scripts
python -m unittest discover -s tests -v
python -m pip check
```

Windows PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活虚拟环境。

前端：

```bash
cd frontend
npm ci
npm run test
npm run build
```

部署配置：

```bash
docker compose config
git diff --check
```

CI 会在 Pull Request 和 `master` 分支推送时执行 Ruff、后端测试、前端测试与构建、依赖检查和 Compose 配置校验。

## 数据与安全

- 不提交 `.env`、密码、Token、业务 Excel、数据库、日志或导出结果；
- 正式环境通过 HTTPS 暴露 Web，Compose 默认只绑定宿主机回环地址；
- 不直接修改数据库来修正批次数量或结果；
- 不删除或重建生产数据卷；
- 数据库和后台任务时间使用 UTC，Web 统一显示北京时间。

## 相关文档

| 文档 | 用途 |
| --- | --- |
| [代理工作规则](AGENTS.md) | 自动化开发代理在本仓库中的强制规则 |
