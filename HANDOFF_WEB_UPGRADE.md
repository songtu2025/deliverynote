# 供应链交货处理系统 Linux/Codex CLI 交接

- 更新时间：2026-07-22 19:09（Asia/Shanghai）
- 仓库：`https://github.com/songtu2025/deliverynote.git`
- 默认分支：`master`
- 实现基线提交：`ebde9ea Initial delivery note web application`

## 0. 2026-07-22 19:09 最新接续状态（新会话先看）

### 0.1 唯一正确的继续工作目录

本轮开发必须从以下隔离工作树继续：

```bash
cd /root/deliverynote/.worktrees/admin-maintenance
git status -sb
git diff --check
```

- 分支：`feature/admin-maintenance`
- 当前超收功能提交：`66b44e3 feat: add versioned overreceipt rules`；Worker SIGTERM 修复提交：`e410a7e fix: stop worker gracefully`；仓库正式名称修复提交：`0b4ba6b fix: use canonical local warehouse name`。
- `/root/deliverynote` 主工作区位于 `master`，包含用户尚未整理的未提交改动。除非任务明确要求合并两个工作区，否则不要在那里开发，不要覆盖、还原或删除其中任何文件。
- 原 16 个未提交路径已逐文件审查并在完整验证后提交为 `067fb86 feat: strengthen admin data maintenance`；批次并发上传与草稿恢复审计修复提交为 `455b759`；超收规则实现提交为 `66b44e3`。本交接文档提交后工作树应保持干净。
- 2026-07-22 16:43 已完成正式迁移和全栈重建；18:02 又从提交 `0b4ba6b` 部署仓库正式名称修复，线上资源为 `index-DDAEHKYt.js` / `index-gXYtaLj0.css`。系统初始默认无规则；业务随后由 `admin` 发布了首个正式版本并完成一个规则批次。
- 用户已要求停用 Superpowers 插件；后续会话不要调用 `superpowers:*` 技能。

### 0.2 本轮已完成的代码工作

1. 管理员“基础资料”已按 PC 端重做：左侧资料目录显示就绪状态、版本与更新时间；右侧明确用途、业务影响、必填字段、当前版本、数据摘要、预览、质量与历史版本。
2. “上传替换”改为先选文件，再明确执行“校验并启用新版本”；库位资料存在当前版本时必须走服务端草稿维护流程，保留“自动保存到服务器”。
3. 库位草稿补强了基线与并发安全：草稿响应使用服务端权威当前版本、按固定顺序加锁、发布前再次校验基线；库位已有版本时禁止通过普通上传绕过草稿发布。
4. “待处理审校”已展示 `规模定位`、`备货定位`、`已下单可售天数`，多 MSKU 定位值以可读格式展示，并纳入全文搜索。
5. “待处理审校”已增加 `站点`、`规模定位`、`备货定位` 三个下拉筛选，支持组合筛选、搜索、清空；多 MSKU 定位值会拆成独立筛选项。
6. 导出 Excel 的保护策略已在提交 `37339da` 中调整：用户打开导出表后可以自行修改列宽、行高等格式，同时保持业务单元格保护约束。
7. 批次多文件并发上传的排序竞争已用 API 屏障测试稳定复现：修复前两个请求返回 `[201, 409]`；修复后 SQLite 与临时 PostgreSQL 17 均返回 `[201, 201]`，文件顺序连续为 `[1, 2]`。实现只在文件保存后的短事务内分配顺序，使用当前单 API 进程锁并对 PostgreSQL 批次行执行 `FOR UPDATE`。
8. POST 恢复已有库位草稿现在会记录 `resume_input_draft`，包含操作人、草稿 ID 和基线版本；操作记录页面显示“继续库位草稿”。GET 只读草稿不会产生审计噪音。
9. 系统初始默认不使用超收规则。所有现有 `operator` 与 `admin` 都能按需发布不可变版本和重新启用历史版本；每次发布/启用都有审计记录。只有主动发布规则后，新批次才锁定当时唯一启用的规则，后续发布不会改变旧批次。
10. 规则按短尾/中尾/长尾配置绝对超收数量和目的仓精确白名单。仓库列表可为空，表示全部禁止；通常不勾选“供应商成品本地仓”（早期讨论中的“供应链成品仓”指同一仓库，以当前正式名称为准）。规模定位为空、未知或同一 SKU/站点下多个 MSKU 定位冲突时不自动超收。
11. 同一批次按 `供应商 + SKU + 站点` 共享一次超收额度，继续遵循用户文件顺序。先扣采购余额，再扣超收额度；只使用规则允许且原采购快照中真实存在的仓库，剩余超量进入待处理，保持数量守恒。
12. Worker、批次详情和 A:G 导出已接入锁定规则。脱敏场景在短尾额度 50 时由原 `160 = 100 + 60` 变为 `160 = 150 + 10`，第二个文件导出为 70 可导入、10 待处理，备注为“超出允许超收量：10”。无规则时 CLI 和 Web 原行为不变。
13. 已新增专用幂等迁移 `python -m delivery_note.migrations.overreceipt_rules`，只创建规则版本表和批次绑定表，不修改既有批次表。
14. 独立恢复栈停机时稳定发现 Worker 作为容器 PID 1 不响应默认 SIGTERM，Compose 最终将其强制结束为 137。新增显式 SIGTERM/SIGINT 处理：空闲轮询可立即退出，处理中会在 Docker 宽限期内继续当前 `run_once`，完成后停止；进程级回归测试和空闲恢复栈 Compose 停机均验证退出码为 0。
15. 新增 `scripts/backup_deliverynote.py`，把 PostgreSQL custom dump 与 `delivery_data` 只读归档固化为同一原子完成目录；脚本先关闭入口并排空任务，成功或失败都会恢复服务，同时校验 dump、tar 路径、SHA-256 和完整标记。默认保留数量为 0，不自动删除备份；`ops/systemd/` 只提供未安装示例。

### 0.3 最近一次完整验证证据

```text
Python unittest: 129/129 passed
Python pip check: passed
Frontend Vitest: 7 files, 61/61 passed
Frontend production build: passed
git diff --check: passed
Docker Compose config: passed
Temporary PostgreSQL concurrent upload: passed (`[201, 201]`, orders `[1, 2]`)
Temporary PostgreSQL overreceipt migration/version lock: passed (one active rule; batch remained on V1 after V2 publish)
Isolated overreceipt business QA: passed (no rule `160 = 100 + 60`; short-tail 50 `160 = 150 + 10`; A:G and notes passed)
Production Chrome QA: passed (`index-DDAEHKYt.js` / `index-gXYtaLj0.css`, canonical warehouse name, no failed responses or console errors)
Paired production backup/restore drill: passed (all DB counts matched; 50/50 files and aggregate SHA-256 matched; migration ran twice)
Paired backup script unit tests: 6/6 passed (success, archive failure recovery, timeout, safe tar links/retention, check-only)
Production backup script check-only: passed (4 services running, 0 active jobs, volume/images resolved)
Restored legacy compatibility: passed (10/10 old batches have no rule binding; restored input download passed)
Worker Compose SIGTERM: passed after fix (exit 0; previously reproduced 137)
```

实际命令：

```bash
/root/deliverynote/.venv/bin/python -m unittest discover -s tests -v
/root/deliverynote/.venv/bin/python -m pip check
cd /root/deliverynote/.worktrees/admin-maintenance/frontend && npm run test
cd /root/deliverynote/.worktrees/admin-maintenance/frontend && npm run build
cd /root/deliverynote/.worktrees/admin-maintenance && git diff --check
WEB_PORT=18080 docker compose --env-file /root/deliverynote/.env -p deliverynote config --quiet
```

最近前端构建仍有单包大于 500 kB 的 Vite 提示，不是构建失败，暂不应优先引入复杂拆包。
本地和线上当前构建资源均为 `index-DDAEHKYt.js` / `index-gXYtaLj0.css`。

### 0.4 正式环境状态

- 正式地址：`https://deliverynote.seekwaygroup.com/`
- 最近部署时间：2026-07-22 18:02（Asia/Shanghai）；16:43 完成全栈部署，18:02 部署正式仓库名称修复。
- 部署来源：`/root/deliverynote/.worktrees/admin-maintenance` 提交 `0b4ba6b`。18:02 的 Web 更新因 Compose 依赖同时用缓存镜像重建了 API；Worker 保持 16:43 的实例，数据库保持原实例。
- 当前线上前端资源：`/assets/index-DDAEHKYt.js`、`/assets/index-gXYtaLj0.css`。
- 本机与外部 HTTPS `/health` 均返回 `{"status":"ok"}`；`db`、`api`、`worker`、`web` 均运行，API 健康。部署稳定后的日志没有 traceback、异常或失败请求。
- 真实 HTTPS Chrome 验收已通过：登录、规则页、仓库下拉、本地表单刷新不保存、批次列表、规则批次详情和退出均正常；页面显示正式名称“供应商成品本地仓”，不再显示旧称，测试产生 0 个规则写请求、0 个失败响应和 0 个控制台错误。
- 生产当前为 11 个批次、1 个超收规则版本、1 个批次规则绑定、0 个 queued/running 任务。`admin` 于 16:59:51 发布 `2026-07-22版本`（短尾 50 / 中尾 20 / 长尾 10），白名单 5 个仓库并排除“供应商成品本地仓”。批次 11 锁定该版本并计算成功：`7732 = 7221 + 511`；同一来源文件的无规则批次 10 为 `7732 = 6834 + 898`。
- 18:10 以只读 API 和现有下载结果完成批次 11 技术复核：8 条待处理记录合计 511，其中 7 条共 447 为“超出允许超收量”、1 条 64 为“未找到可交货采购需求”，没有人工拆分。ZIP 只有 1 个 xlsx 成员且与单文件下载逐字节一致；工作簿可打开，`交货导入`/`待处理导入`、正式 A:G、辅助 H:J、`65 行/7221` 可导入、`8 行/511` 待处理均通过。规则超收导入为 13 行共 387，备注数量逐行一致；产生超额待处理的 3 个短尾键和 4 个中尾键都已耗尽对应 50/20 共享额度，无采购需求键未获得超收。
- 本次技术复核只调用登录、读取、下载和退出，没有调用计算、导出、拆分或规则写接口；复核后仍为 1 个规则、1 个绑定、11 个批次和 0 个活动任务。API 请求均为 2xx，Worker 最近 15 分钟无错误日志。
- 数据库容器保持部署前 ID `c85a2cffddd88ee98e2518d880659aa7b26d563f91390212aad3d15805c1459c`，继续挂载 `deliverynote_postgres_data`；部署没有删除或重建数据库卷。不要执行 `docker compose down -v`。
- 成对备份已从临时目录复制到持久受控目录 `/root/backups/deliverynote/20260722-160803`，目录权限为 `0700`、文件权限为 `0600`，`database.dump` 和 `delivery_data.tar.gz` 的 SHA-256 已再次验证。源临时备份和恢复 QA 数据卷也仍保留。

### 0.5 尚未完成与优先级

1. **P1：配置并演练定时异机成对备份。** 成对备份脚本、失败恢复、完整标记、安全保留逻辑和 systemd 示例已经实现，正式 Compose 的只读预检通过；尚未确定异机落点与保留周期，因此未安装 timer、未执行新脚本停服备份，也未做异机恢复抽检。
2. **P1：由业务员决定首个真实规则批次的待处理去向。** 批次 11 的规则、511 明细汇总、单文件/ZIP、A:G、备注和数量守恒已完成只读技术复核；仍需业务员逐条判断 8 条待处理记录应保留还是拆分，技术验收不能代替该业务决定。
3. **P2：把本次专用迁移扩展为通用迁移版本登记机制。** 本次新增表已有可执行幂等迁移，但项目还没有通用 migration history。

### 0.6 新会话可直接粘贴的启动指令

> 请在 `/root/deliverynote/.worktrees/admin-maintenance` 继续任务。先完整阅读 `AGENTS.md`、`README.md`、`HANDOFF_WEB_UPGRADE.md`，运行 `git status -sb` 和 `git diff --check`。不要进入或覆盖 `/root/deliverynote` 主工作区，那里有用户未提交改动。超收功能提交为 `66b44e3`，仓库正式名称修复为 `0b4ba6b`；后端 129/129、前端 61/61、pip check、build、Compose config、并发上传、隔离超收业务/浏览器 QA、成对备份恢复、旧批次兼容和 Worker 停机均已通过。2026-07-22 18:02 已部署最新 Web，线上资源为 `index-DDAEHKYt.js` / `index-gXYtaLj0.css`，页面只使用正式名称“供应商成品本地仓”。生产当前有 11 个批次、1 个规则版本、1 个规则绑定和 0 个活动任务；批次 11 锁定首个正式规则并满足 `7732 = 7221 + 511`。18:10 已只读核对 8 条待处理记录、单文件/ZIP、A:G/H:J、规则额度、备注和数量守恒，技术结果通过且未触发业务写入；业务员仍需决定 511 的实际处置。成对备份脚本及 systemd 示例已实现并通过 6/6 专用测试与正式只读预检，但 timer 未安装、异机目标和保留周期未配置。持久备份位于 `/root/backups/deliverynote/20260722-160803`，但它早于首条规则和批次 11；源临时备份及恢复卷仍保留。下一步配置异机落点后做受控停服备份、同步和恢复抽检。不要调用 Superpowers 插件，不要破坏共享采购余额、数量守恒、锁仓、仓库顺序、CLI 和 A:G 导出兼容规则，不要删除任何部署或恢复数据卷。

## 1. 接手时先做什么

在 Linux 机器上执行：

```bash
git clone https://github.com/songtu2025/deliverynote.git
cd deliverynote
git status -sb
git log -3 --oneline --decorate
```

正常情况下应位于 `master`，工作区干净。接着完整阅读：

1. `AGENTS.md`
2. `README.md`
3. `HANDOFF_WEB_UPGRADE.md`
4. `compose.yaml`
5. `.env.example`

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
- 五步批次工作台、数量守恒摘要、异常筛选和右侧拆分审校。
- 输入资料就绪门槛、上传校验、用户启停/密码重置和操作记录。
- operator/admin 共用的超收规则维护页、不可变规则版本、历史启用和审计记录。
- 批次级超收规则锁定、按规模定位的绝对额度、目的仓白名单和跨文件顺序共享。
- 管理员维护 PC 工作区，按“基础资料、用户账号、操作记录”组织入口。
- 五类资料目录的用途说明、当前版本摘要、预览、下载、替换上传和历史版本。
- 库位资料的服务端持久化单草稿、行级维护、筛选、Excel 差异确认、校验、发布和丢弃。
- 计算/导出任务刷新恢复、计算前删除错传文件和登录过期统一处理。
- Docker Compose、Nginx 和外部 HTTPS 代理接入方式。

最近验证结果：

```text
Python unittest: 129/129 passed
Frontend Vitest: 7 files, 61/61 passed
Frontend production build: passed
pip check: passed
Compose YAML static check: passed
PostgreSQL DDL compile check: passed
Existing batch-workbench Chrome desktop/tablet/mobile visual QA: passed
Administrator-maintenance Chrome PC visual QA: passed after publish-dialog viewport fix
Overreceipt operator Chrome PC and two-file business QA: passed
Paired production backup and isolated restore drill: passed
Worker SIGTERM process and Compose shutdown: passed (exit 0)
Linux Docker Compose build and runtime smoke test: passed
HTTPS health, login, read API and logout smoke test: passed
```

本轮流程与 UI 方案见 `UI_UX_OPTIMIZATION_PLAN.md`。既有批次工作台浏览器验收记录见 `design-qa.md` 和 `design/qa/`；本轮管理员维护只以 1280–1920px PC 端为验收范围。Google Chrome 已完成 1280×800、1440×900 和 1920×1080 PC 验收，脱敏截图与证据保存在 `design/admin-maintenance-qa/`。验收中发现并修复了多条发布警告把弹窗底部操作推离首屏的问题；最终复审又补上了库位草稿基线保护，维护期间不再允许替换当前库位版本，发布时会再次校验基线，创建/恢复草稿也统一按“版本行 → 草稿行”加锁并在等待后重新读取当前版本。不再把平板和移动端作为本轮完成门槛。

2026-07-22 16:43 已从 `feature/admin-maintenance` 工作树完成生产超收表迁移和全栈重建；18:02 从提交 `0b4ba6b` 部署仓库正式名称修复，线上资源为 `index-DDAEHKYt.js` 和 `index-gXYtaLj0.css`。数据库容器与卷、Worker 实例均保持不变，API 因 Web 的 Compose 依赖用缓存镜像重建并恢复健康。真实 HTTPS Chrome 验证页面只显示“供应商成品本地仓”，仓库下拉、本地未提交表单刷新、当前规则、11 个批次及批次 11 详情均正常，0 个规则写请求、失败响应和控制台错误。生产现有 1 个规则版本和 1 个批次绑定；批次 11 锁定首个规则并满足 `7732 = 7221 + 511`。18:10 已进一步完成待处理汇总和下载工作簿的只读技术复核；技术输出通过，但业务员仍需逐条决定 511 的实际处置，定时异机备份也未建立，不能据此宣称整个项目已完整生产可用。

本次自动化验证实际使用：

```bash
/root/deliverynote/.venv/bin/python -m unittest discover -s tests -v
/root/deliverynote/.venv/bin/python -m pip check
cd frontend && npm run test
cd frontend && npm run build
docker compose -p deliverynote --env-file /root/deliverynote/.env config --quiet
```

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
| `delivery_note/web/position_drafts.py` | 库位服务端草稿、乐观并发、校验、差异和原子发布 |
| `delivery_note/migrations/overreceipt_rules.py` | 已有数据库新增超收规则表的幂等迁移 |
| `delivery_note/input_inspection.py` | 五类资料摘要/预览与库位质量检查 |
| `delivery_note/worker.py` | 计算、导出、任务租约和超时恢复 |
| `frontend/src/` | 登录、批次、审阅拆分和管理员页面 |
| `tests/` | Python 单元、API 和 Worker 端到端测试 |
| `scripts/generate_acceptance_data.py` | 生成五类输入和双文件共享余额验收数据 |
| `tests/fixtures/` | 不含业务信息的最小测试 fixture |
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
11. 超收规则发布后内容不可修改；调整配置必须发布新版本，已有批次继续使用创建时锁定的版本。
12. 超收额度按同一批次的 `供应商 + SKU + 站点` 共享，并在正常采购余额之后按文件顺序扣减。
13. 空规模定位、未知定位、多 MSKU 定位冲突、非白名单仓库和超过规则额度的数量都不能自动超收，仍须完整进入待处理。

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

业务 Excel、`.env`、数据库和导出结果都不在 Git 仓库中。需要完整验收数据时运行：

```bash
python scripts/generate_acceptance_data.py --output-dir acceptance_data
```

该命令生成五类输入版本和两份脱敏交货文件，预期共享余额结果为 `160 = 100 + 60`。

## 6. 项目完成标准

`README.md` 的“项目完成标准”是统一验收口径，分为代码、Linux 部署、业务和运维四类门槛。四类全部通过前，不得把项目标记为完成或生产可用。

最低要求：

1. GitHub 全新克隆的 Python、前端测试和生产构建全部通过，不依赖旧机器文件。
2. Linux 上 PostgreSQL、API、单 Worker 和 Web 四个容器运行正常并通过重启持久化。
3. 使用脱敏验收数据完成五类版本上传、共享余额、拆分、数量守恒和导出。
4. HTTPS、数据库与文件卷成对备份、恢复演练和数据库迁移方案可执行。

## 7. Linux 部署验收

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

## 8. 当前已知边界

- Compose 只启动一个 Worker。这是当前确认范围，不要在没有并发测试前直接扩容多个 Worker。
- Web 只绑定 `127.0.0.1`，正式访问需要外部 HTTPS 反向代理。
- 数据库仍主要通过 SQLAlchemy `create_all()` 建表；本次超收新增表已有 `python -m delivery_note.migrations.overreceipt_rules` 专用幂等迁移，但尚无通用 migration history。
- 自动文件过期清理、数据库定时备份和文件卷备份尚未实现。
- 管理员账号只在数据库不存在同名用户时创建。修改 `.env` 不会重置已有管理员密码。
- PostgreSQL 已通过 Linux Compose 真实运行、登录和数据读取冒烟验收；脱敏双文件业务流程和同机成对备份恢复已通过。定时与异机备份仍未建立。
- 前端生产构建存在单包约 1.1 MB 的体积提示，当前不影响功能，不要为了消除提示优先引入复杂拆包。
- 库位 Excel 导入预览 Token 保存在单 API 进程内存中，默认 900 秒过期；当前 Compose 单进程部署成立，扩展多 API 进程前必须改为共享状态并补并发测试。
- 库位资料最多只有一个 `editing` 草稿；行修改会持久化到服务器，但只有发布后才生成不可变的新输入版本并成为新批次可选的当前版本，已有批次继续使用锁定的旧版本。
- 仓库是公开仓库，禁止提交业务数据、真实密码、Token 或客户文件。

## 9. 测试命令

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

## 10. Git 和 Codex CLI 工作规则

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

> 请先完整阅读 AGENTS.md、README.md 和 HANDOFF_WEB_UPGRADE.md，然后检查 git status、当前提交、compose.yaml、.env.example 和现有测试，并运行验收数据生成脚本。当前第一目标是完成 Linux Docker Compose 实机部署验收：启动 PostgreSQL、API、单 Worker 和 Web，验证健康检查、登录、五类版本上传、双文件共享采购余额、拆分审校、单文件与 ZIP 导出，以及容器重启后的数据持久化。不要从头重建，不要改变已有采购匹配、超量保留、锁仓优先、导出格式和 CLI 行为。发现问题时先给出复现证据，再做最小修复；每完成一个阶段运行相应测试并汇报结果。不要提交 .env、Excel、数据库或输出文件。

## 11. Linux 验收后的建议顺序

1. 记录真实 Docker/PostgreSQL 部署中发现的问题并补回归测试。
2. 验证外部 HTTPS 代理、上传大小和长任务日志。
3. 把已验证的 PostgreSQL 与文件卷成对备份流程固化为定时、异机任务。
4. 把本次专用迁移逐步扩展为有版本登记的通用迁移方案。
5. 根据实际操作反馈补前端关键流程测试，不做无业务依据的界面重构。

当前新功能与仓库正式名称修复均已部署并通过上述有限生产验收；首个规则批次的待处理与下载已通过只读技术复核，但 511 的实际处置仍需业务员判断，定时异机成对备份也未完成。不要把“本次版本已上线”扩大表述为“整个项目已完整生产可用”。
