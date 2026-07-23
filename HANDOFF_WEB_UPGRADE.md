# DeliveryNote 当前维护交接

- 更新时间：2026-07-23（Asia/Shanghai）
- 仓库：`https://github.com/songtu2025/deliverynote.git`
- 默认分支：`master`
- 功能合并基线：`71d51d8 feat: upgrade internal delivery workflow`
- 生产功能分支最终提交：`072b316 feat: polish internal delivery workflow`

`71d51d8` 是 PR #1 的 Squash merge 结果，其 Git tree 与 `072b316` 完全一致。远端 `feature/admin-maintenance` 分支保留了 44 个详细开发提交。

## 1. 工具定位

这是供不超过 5 人使用的内部交货 Excel 处理工具，不按大型业务平台建设。

当前部署保持：

```text
HTTPS 反向代理
    ↓
React / Nginx
    ↓
FastAPI
    ↓
PostgreSQL + delivery_data 文件卷
    ↓
单 Worker
```

不要为当前规模引入 Redis、Celery、微服务、多 API、多 Worker、Kubernetes、移动端或复杂权限平台。

## 2. 继续工作的位置

服务器上的 `/root/deliverynote` 主工作区有用户自己的未提交改动，不要进入、覆盖、还原或清理。

继续开发应新建或使用独立 worktree，例如：

```bash
cd /root/deliverynote
git fetch origin
git worktree add .worktrees/<task-name> -b <task-branch> origin/master
cd .worktrees/<task-name>
```

开始前必须：

```bash
cat AGENTS.md
cat README.md
cat HANDOFF_WEB_UPGRADE.md
git status -sb
git diff --check
```

不要执行：

```bash
git reset --hard
git clean
docker compose down -v
```

用户已要求不调用 Superpowers 插件。

## 3. 当前功能

- 五类版本化基础资料及摘要、预览、下载和历史版本。
- 库位资料服务器草稿、逐行维护、Excel 替换预览、校验和原子发布。
- 多文件批次、用户排序、预检和共享采购余额。
- 后台计算、任务租约、心跳、超时恢复和失败重试。
- 待处理记录筛选和数量安全的人工拆分。
- 单来源结果、多文件合并 Excel 和分文件 ZIP。
- 默认关闭、不可变版本化、按批次锁定的超收规则。
- admin/operator 发布和启用规则，管理员维护基础资料与用户。
- 批次独立 URL、刷新/返回、北京时间显示和 PC 操作界面。
- 原有单文件 CLI。

## 4. 不可破坏的业务规则

1. 同一批次只加载一份采购数据。
2. 多份交货文件严格按用户顺序连续消耗采购余额。
3. 调换顺序可改变余额归属，但不能改变交货总量。
4. 超量、未匹配或歧义数量必须完整进入待处理。
5. 供应商成品本地仓优先，其他仓库保持确定性顺序。
6. 商品锁仓标识用于解决 SKU 和站点歧义。
7. 拆分数量全部为正，拆分总和等于原待处理数量。
8. 始终满足 `交货总量 = 可导入总量 + 待处理总量`。
9. 任一文件计算失败时不得持久化该批次的部分结果。
10. 保持 CLI、A:G、模板样式、备注和导出命名兼容。
11. 不跨批次延续采购扣减，不做 ERP 回写。
12. 超收规则发布后不可修改，已有批次继续使用锁定版本。
13. 超收额度按批次内 `供应商 + SKU + 站点` 共享，先扣采购余额，再按文件顺序扣额度。
14. 空定位、未知定位、定位冲突、非白名单仓库和额度外数量不得自动超收。

测试数据字段损坏时修正测试数据，不修改正式逻辑去兼容错误列名。

## 5. 关键代码

| 路径 | 作用 |
| --- | --- |
| `delivery_note/pipeline.py` | SKU/站点匹配、采购过滤、仓库分配、超量保留 |
| `delivery_note/application.py` | 多文件共享余额、批次顺序、拆分投影 |
| `delivery_note/excel_io.py` | Excel 读取、模板校验和写出 |
| `delivery_note/config.py` | 供应商识别、仓库顺序和备注 |
| `delivery_note/cli.py` | 单文件 CLI |
| `delivery_note/web/models.py` | 数据库模型 |
| `delivery_note/web/api.py` | FastAPI 接口 |
| `delivery_note/web/position_drafts.py` | 库位草稿和原子发布 |
| `delivery_note/worker.py` | 计算、导出和任务租约 |
| `delivery_note/migrations/overreceipt_rules.py` | 超收规则幂等迁移 |
| `frontend/src/` | React 页面和组件 |
| `tests/` | Python 测试 |
| `compose.yaml` | 正式单机编排 |

Web、CLI 和 Worker 必须继续共用 `delivery_note` 核心业务逻辑，不复制一套 Web 专用采购匹配代码。

## 6. 超收规则口径

- 初始默认不启用。
- 所有 admin/operator 可发布新版本或重新启用历史版本。
- 发布后不可修改。
- 新批次锁定创建时唯一启用的版本。
- 短尾、中尾、长尾配置绝对数量。
- 仓库使用精确白名单，空列表表示全部不允许。
- 正式仓库名称为“供应商成品本地仓”。
- 额度按供应商、SKU、站点在批次内共享。
- 只使用采购快照中真实存在且命中白名单的仓库。
- 任何规则外数量仍进入待处理并保持数量守恒。

## 7. 当前验证基线

2026-07-23 合并前重新执行：

```text
Python unittest: 131/131 passed
Frontend Vitest: 8 files, 71/71 passed
pip check: passed
Frontend production build: passed
Docker Compose config: passed
git diff --check: passed
HTTPS /health: passed
```

前端产物：

```text
index-DzkyLbfg.js
index-BJrakn5L.css
```

前端仍有约 1.2 MB 单包提示，对当前少量 PC 用户不构成功能问题。

## 8. 正式环境

- 地址：`https://deliverynote.seekwaygroup.com/`
- 最近部署：2026-07-23 12:46（Asia/Shanghai）
- 部署源码树：与 `master@71d51d8` 完全一致
- 容器：`db`、`api`、`worker`、`web`
- Web 绑定：`127.0.0.1:18080`
- 数据卷：`deliverynote_postgres_data`、`deliverynote_delivery_data`
- 最近核对：4 个容器运行，API 和数据库健康，HTTPS `/health` 返回成功

合并 PR #1 没有触发重新部署；生产在合并前已经运行相同文件树。

不要删除或重建生产数据卷。

## 9. 生产数据现状

截至 2026-07-23：

- 13 个批次，均为 `succeeded`。
- 0 个 queued/running 任务。
- 历史异常记录包含测试、重复处理和真实业务记录，不能把总量直接视为真实未结业务。
- 批次 8–11 的同名来源文件 SHA-256 完全一致，是同一原文件的多次处理。
- 批次 12 虽与批次 11 同名，但文件 SHA-256 不同，不能当成重复文件。
- 批次 11 满足 `7732 = 7221 + 511`；其 511 件处置仍需业务人员决定。
- 批次 13 的原待处理为 107，已通过拆分解决 80，当前有效待处理为 27。

不要根据技术判断删除或批量修改这些批次。业务人员应先确认哪些批次是验收、重复或正式处理。

## 10. 更新与验证

代码更新：

```bash
git pull --ff-only
docker compose build api worker web
docker compose run --rm api python -m delivery_note.migrations.overreceipt_rules
docker compose up -d
docker compose ps
curl http://127.0.0.1:8080/health
```

Python：

```bash
source .venv/bin/activate
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

部署前：

```bash
docker compose config
git diff --check
```

涉及业务逻辑时还应使用脱敏双文件场景复核：

```text
无规则：160 = 100 + 60
短尾 50：160 = 150 + 10
```

同时检查 A:G、备注、来源顺序、合并 Excel、分文件 ZIP 和单文件下载。

## 11. 已知边界

- 仅维护 PC 端，不做手机端。
- 仅支持单 API、单 Worker。
- 库位导入预览 Token 是进程内状态。
- 没有通用 migration history，只有超收专用幂等迁移。
- 操作记录接口只返回最近 200 条。
- 没有 GitHub Actions CI。
- 当前不安装自动备份 timer；这是用户确认的运维取舍，不是待开发功能。
- 仓库保留备份脚本和 systemd 示例，但不会自动运行。
- 不进行 ERP 回写，也不跨批次保存采购扣减。

## 12. 后续优先级

当前没有必须立即开发的新功能。

合理顺序：

1. 根据真实操作反馈修复明确问题。
2. 由业务人员确认历史批次的实际状态。
3. 修改业务逻辑时先补复现测试，再做最小修复。
4. 只有数据量或使用人数真实增长后，才考虑分页、拆包或架构调整。

不要为了“架构完整”主动拆微服务或重写现有核心流程。

## 13. 新会话启动提示

> 请先完整阅读 `AGENTS.md`、`README.md` 和 `HANDOFF_WEB_UPGRADE.md`，运行 `git status -sb` 与 `git diff --check`。这是供不超过 5 人使用的内部交货处理工具，保持单机、单 API、单 Worker，不做手机端、微服务或 ERP 回写。不要进入或覆盖 `/root/deliverynote` 主工作区，不要删除 Docker 数据卷。修改业务逻辑前先阅读相关测试和调用链，保持共享采购余额、数量守恒、供应商成品本地仓优先、锁仓、拆分、CLI 和 A:G 导出兼容。
