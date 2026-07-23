# 供应链交货处理工具

这是一个供少量内部人员使用的交货 Excel 处理工具，当前使用规模预计不超过 5 人。

工具接收一个批次中的多份供应商交货单，按用户指定顺序共享采购余额，生成可导入数据和待处理数据。它保留原有单文件 CLI，同时提供 React + FastAPI + PostgreSQL + 单 Worker 的 Web 操作界面。

当前定位是单机内部工具，不计划引入 Redis、Celery、微服务、集群、高可用或移动端适配。

## 业务规则

以下规则是代码修改和业务验收的共同边界：

- 同一批次内，多份交货文件按用户指定顺序共享并连续扣减采购余额。
- 不跨批次延续采购扣减，不向 ERP 回写数据。
- 所有交货数量必须保留；超量、未匹配和歧义部分进入待处理。
- 供应商成品本地仓优先，其他仓库保持确定性顺序。
- 商品锁仓标识继续用于解决 SKU 和站点歧义。
- 人工拆分数量必须为正数，拆分总和必须等于原待处理数量。
- 始终满足：`交货总量 = 可导入总量 + 待处理总量`。
- CLI、模板 A:G 字段、样式、交货备注和导出命名保持兼容。

## 主要功能

- 管理员和操作员登录。
- 采购、商品、供应商、库位和导出模板五类版本化基础资料。
- 库位资料的服务器草稿、逐行维护、Excel 替换预览、校验和发布。
- 创建批次、上传多份交货文件、调整处理顺序和预检。
- 单批次共享采购余额并由后台 Worker 计算。
- 待处理记录筛选、查看和数量安全的人工拆分。
- 多文件合并 Excel、分文件 ZIP 和单个来源结果下载。
- 默认关闭、按批次锁定的版本化超收规则。
- 用户账号维护和最近 200 条操作记录。
- 批次独立 URL、浏览器刷新/返回和北京时间显示。

## 日常操作

1. 登录工具。
2. 管理员在“管理员维护 → 基础资料”确认五类资料均已就绪。
3. 如需超收，由管理员或操作员进入“超收规则”发布规则版本；不发布则保持默认关闭。
4. 创建批次并上传一份或多份交货文件。
5. 调整文件顺序并执行预检。
6. 启动计算，等待 Worker 完成。
7. 审阅待处理记录，必要时进行拆分。
8. 生成导出：
   - 单文件批次下载对应处理结果；
   - 多文件批次可下载合并 Excel；
   - 分文件 ZIP 保留每份交货单的独立结果。

页面流程统一为：

```text
准备文件 → 预检 → 计算结果 → 异常审校 → 导出下载
```

## 超收规则

工具初始状态不使用超收规则。只有主动发布规则后，新建批次才会锁定当时启用的版本。

规则特点：

- 所有现有 `admin` 和 `operator` 用户均可发布规则或重新启用历史版本。
- 已发布版本不可修改；调整配置必须发布新版本。
- 已有批次继续使用创建时锁定的版本。
- 短尾、中尾、长尾分别配置允许超收的绝对数量。
- 允许仓库使用精确白名单；仓库列表为空表示全部禁止。
- 空规模定位、未知定位和多个 MSKU 定位冲突均不自动超收。
- 额度按同一批次的 `供应商 + SKU + 站点` 共享。
- 先扣正常采购余额，再按文件顺序扣超收额度。
- 规则外数量继续完整进入待处理。

“供应商成品本地仓”是当前正式仓库名称。是否允许该仓库超收由规则白名单决定。

## 基础资料与文件约定

五类版本化资料：

| 类型 | 主要内容 |
| --- | --- |
| 采购需求 | `单据状态`、`供应商`、`SKU`、`平台站点`、`目的仓`、`未交量` |
| 商品信息 | `SKU`、`店铺/站点`、`品类A`、`锁仓MKSU` |
| 供应商 | `供应商编号`、`供应商名称`、`状态` |
| 库位/排仓 | 工作表 `MSKU_视图`，包含 `店铺-站点`、`积加SKU`、`MSKU` 和定位字段 |
| 导出模板 | 第二行为正式 A:G 表头，第三行保留样例格式 |

交货文件使用 `汇总` 工作表。供应商根据文件名和当前供应商资料识别，不在代码中按供应商新增写死分支。

正式导入字段固定为：

```text
*目的仓
*供应商编码
*SKU
*本次交货量
*站点
单据备注
交货备注
```

业务 Excel、上传文件和导出结果只保存在部署数据卷中，不进入 Git。

## Linux Docker 部署

### 首次部署

```bash
git clone https://github.com/songtu2025/deliverynote.git
cd deliverynote
cp .env.example .env
```

至少修改：

```env
POSTGRES_PASSWORD=设置强密码
ADMIN_USERNAME=admin
ADMIN_PASSWORD=设置强密码
WEB_PORT=8080
CORS_ORIGINS=https://实际访问域名
MAX_UPLOAD_BYTES=20971520
IMPORT_CANDIDATE_TTL_SECONDS=900
```

检查并启动：

```bash
docker compose config
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8080/health
```

正常响应：

```json
{"status":"ok"}
```

Web 端口只绑定到 `127.0.0.1`。正式访问由宿主机 Nginx 或其他 HTTPS 反向代理转发，不直接把 Compose Web 端口暴露到公网。

### 更新

```bash
git pull --ff-only
docker compose build api worker web
docker compose run --rm api python -m delivery_note.migrations.overreceipt_rules
docker compose up -d
docker compose ps
curl http://127.0.0.1:8080/health
```

超收规则迁移是幂等的，可重复执行。新数据库也会由应用创建当前表结构。

停止服务但保留数据：

```bash
docker compose down
```

不要执行 `docker compose down -v`，该命令会删除 PostgreSQL 和上传文件数据卷。

## 本地开发与测试

建议使用 Python 3.11 和 Node.js 22。

后端：

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

Compose 配置：

```bash
docker compose config
```

当前验证基线：

- Python：131/131 通过。
- 前端：8 个测试文件，71/71 通过。
- `pip check`：通过。
- 前端生产构建：通过。
- Compose 配置：通过。
- 构建存在约 1.2 MB 单包提示，对当前少量内部用户不构成功能问题。

## 脱敏验收数据

生成固定验收场景：

```bash
source .venv/bin/activate
python scripts/generate_acceptance_data.py --output-dir acceptance_data
```

无超收规则时，两份交货文件各交货 80、采购未交量 100，预期：

```text
交货总量：160
可导入总量：100
待处理总量：60
第一个文件可导入：80
第二个文件可导入：20
```

如发布短尾额度 50 且仓库命中白名单，预期变为：

```text
160 = 150 + 10
```

`acceptance_data/` 只用于本机验收，不提交到 Git。

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

CLI 每次处理一份交货文件，默认按北京时间生成输出目录。需要在多份文件之间共享采购余额时使用 Web 批次流程。

## 当前边界

- 仅维护 PC 端，不以手机端为验收范围。
- Compose 固定使用单 API 和单 Worker。
- 库位 Excel 导入预览 Token 保存在单 API 进程内存中。
- 数据库主要通过 SQLAlchemy `create_all()` 建表；超收功能另有专用幂等迁移，尚无通用迁移版本登记。
- 操作记录页面读取最近 200 条，不提供完整审计分页。
- 仓库没有 GitHub Actions CI，发布前验证在开发和部署环境执行。
- 根据当前使用决定，不安装自动备份定时器；仓库中的备份脚本和 systemd 文件只是未启用的可选工具。

## 数据与安全

- 仓库是公开仓库，不提交 `.env`、真实密码、Token、业务 Excel、数据库、日志或导出结果。
- 正式环境必须使用 HTTPS。
- 修改 `.env` 中的管理员密码不会重置数据库里已经存在的账号。
- 停用用户或重置密码会使其已有登录失效。
- 不删除生产 Docker 数据卷。

开发接续和当前部署状态见 [HANDOFF_WEB_UPGRADE.md](HANDOFF_WEB_UPGRADE.md)。PC 界面维护规范见 [UI_UX_OPTIMIZATION_PLAN.md](UI_UX_OPTIMIZATION_PLAN.md)，最近验收摘要见 [design-qa.md](design-qa.md)。
