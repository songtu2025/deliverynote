# DeliveryNote Codex 工作规则

## 开始前

1. 完整阅读 `README.md` 和 `HANDOFF_WEB_UPGRADE.md`。
2. 运行 `git status -sb`，确认当前分支和未提交改动。
3. 先阅读相关测试和调用链，再修改业务代码。
4. Linux/Docker 问题优先检查 `compose.yaml`、`.env.example` 和服务日志。

## 业务规则

- 同一批次按用户指定顺序共享并连续扣减采购余额。
- 所有交货数量必须保留；超量、未匹配和歧义部分进入待处理。
- 供应商成品本地仓优先，其他仓库保持确定性顺序。
- 商品锁仓标识继续用于解决 SKU/站点歧义。
- 拆分数量必须为正数，拆分总和必须等于原待处理数量。
- 始终保持 `交货总量 = 可导入总量 + 待处理总量`。
- 保持 CLI、模板 A:G 字段、样式、交货备注和导出命名兼容。
- 不跨批次延续采购扣减，不做 ERP 回写。

测试数据字段损坏时修正测试数据，不要修改正式逻辑去兼容错误列名。

## 实现方式

- 遵循 KISS，只做当前任务需要的最小修改。
- Python 代码遵循 PEP8；新增或修改的注释与 docstring 使用中文。
- 不为清理历史格式而全仓重写，只约束当前新增或修改的代码。
- Web、CLI 和 Worker 共用 `delivery_note` 核心逻辑，不复制采购匹配代码。
- 修复缺陷时先写或定位能够复现问题的测试，再实现修复。
- 不引入 Redis、Celery、微服务拆分或没有明确需求的平台组件。
- 不擅自修改真实业务字段含义、仓库优先级或导出格式。

## 验证

Python 变更：

```bash
source .venv/bin/activate
python -m ruff check delivery_note tests scripts
python -m unittest discover -s tests -v
python -m pip check
```

前端变更：

```bash
cd frontend
npm run test
npm run build
```

部署变更还要运行 `docker compose config`，并在有 Docker 的 Linux 环境执行健康检查和业务验收。

## Git 和数据安全

- 不执行 `git reset --hard`、`git clean` 或批量删除不熟悉的文件。
- 不提交 `.env`、业务 Excel、数据库、日志、上传文件或导出结果。
- 不执行 `docker compose down -v`，除非用户明确要求删除全部数据卷。
- 暂存前使用明确路径，检查 `git diff --cached --name-only`。
- 每完成一个阶段报告实际执行的测试及结果，不把未验证项目写成已完成。
