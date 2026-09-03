import { useMemo, useState } from "react";
import { Alert, Button, Card, Input, Select, Spin, Table, Typography } from "antd";
import type { TableProps } from "antd";

import { formatBeijingDateTime } from "../../dateTime";
import type { AuditLog, User } from "../../types";

const AUDIT_LABELS: Record<string, string> = {
  login: "登录",
  logout: "退出",
  create_user: "创建用户",
  update_user_status: "更新用户状态",
  reset_user_password: "重置密码",
  upload_input_version: "上传输入版本",
  activate_input_version: "启用输入版本",
  start_purchase_sync: "开始同步采购数据",
  update_gerpgo_config: "更新积加接口配置",
  create_input_draft: "创建库位草稿",
  resume_input_draft: "继续库位草稿",
  import_input_draft: "导入库位草稿",
  discard_input_draft: "放弃库位草稿",
  publish_input_draft: "发布库位版本",
  publish_overreceipt_rule: "发布超收规则",
  activate_overreceipt_rule: "启用超收规则",
  rename_overreceipt_rule: "重命名超收规则",
  publish_self_operated_overreceipt_rule: "发布自营仓超收规则",
  activate_self_operated_overreceipt_rule: "启用自营仓超收规则",
  rename_self_operated_overreceipt_rule: "重命名自营仓超收规则",
  create_batch: "创建批次",
  create_batch_with_files: "创建交货批次",
  create_empty_self_operated_batch: "创建自营仓草稿",
  create_self_operated_batch: "创建自营仓入库批次",
  delete_empty_delivery_batches: "删除空交货批次",
  delete_empty_self_operated_batches: "删除空自营仓批次",
  upload_batch_file: "上传交货文件",
  upload_self_operated_inbound_file: "上传待入库文件",
  delete_batch_file: "删除交货文件",
  reorder_batch_files: "调整文件顺序",
  preflight_batch: "执行预检",
  queue_compute: "启动计算",
  queue_export: "生成导出",
  save_split: "保存拆分",
  save_self_operated_site_resolution: "保存自营仓站点",
  worker_compute_succeeded: "计算完成",
  worker_export_succeeded: "导出完成",
  worker_self_operated_compute_succeeded: "自营仓计算完成",
  worker_self_operated_export_succeeded: "自营仓导出完成",
  worker_compute_failed: "计算失败",
  worker_export_failed: "导出失败",
  purchase_sync_blocked: "采购数据同步待处理",
  purchase_sync_succeeded: "采购数据同步完成",
  purchase_sync_failed: "采购数据同步失败",
  start_self_operated_inbound_sync: "开始同步待入库数据",
  activate_self_operated_inbound_sync: "启用待入库数据",
  self_operated_inbound_sync_blocked: "待入库数据同步待处理",
  self_operated_inbound_sync_succeeded: "待入库数据同步完成",
  self_operated_inbound_sync_failed: "待入库数据同步失败"
};

const ENTITY_LABELS: Record<string, string> = {
  batch: "批次",
  user: "用户",
  input_version: "基础资料版本",
  input_draft: "库位草稿",
  overreceipt_rule: "超收规则",
  self_operated_overreceipt_rule: "自营仓超收规则",
  batch_file: "交货文件",
  split: "拆分记录",
  exception: "待处理记录",
  job: "后台任务",
  purchase_sync_job: "采购同步任务",
  self_operated_inbound_sync_job: "待入库同步任务",
  integration_config: "接口配置"
};

const actionLabel = (action: string) => AUDIT_LABELS[action] ?? "其他操作";

const AUDIT_TABLE_COMPONENTS: NonNullable<TableProps<AuditLog>["components"]> = {
  table: (props) => <table {...props} aria-label="操作记录" />
};

interface AuditLogPanelProps {
  auditLogs: AuditLog[];
  users: User[];
  loading: boolean;
  error: string | null;
  onRetry: () => void | Promise<void>;
}

function actionColor(action: string): string {
  if (action.endsWith("_failed")) return "error";
  if (action.endsWith("_succeeded")) return "success";
  if (action === "login" || action === "logout") return "default";
  if (action.startsWith("delete_") || action.startsWith("discard_")) return "warning";
  return "processing";
}

export function AuditLogPanel({ auditLogs, users, loading, error, onRetry }: AuditLogPanelProps) {
  const [search, setSearch] = useState("");
  const [actionFilter, setActionFilter] = useState("all");
  const [actorFilter, setActorFilter] = useState("all");

  const actorLabel = (log: AuditLog) => log.user_id
    ? users.find((user) => user.id === log.user_id)?.username ?? `用户 #${log.user_id}`
    : "系统任务";
  const entityLabel = (log: AuditLog) => `${ENTITY_LABELS[log.entity_type] ?? "其他对象"} #${log.entity_id}`;
  const actionOptions = useMemo(() => [
    { value: "all", label: "全部操作" },
    ...[...new Set(auditLogs.map((log) => log.action))]
      .sort((left, right) => actionLabel(left).localeCompare(actionLabel(right), "zh-CN"))
      .map((action) => ({ value: action, label: actionLabel(action) }))
  ], [auditLogs]);
  const actorOptions = useMemo(() => [
    { value: "all", label: "全部操作人" },
    ...(auditLogs.some((log) => log.user_id === null) ? [{ value: "system", label: "系统任务" }] : []),
    ...users
      .filter((user) => auditLogs.some((log) => log.user_id === user.id))
      .map((user) => ({ value: `user:${user.id}`, label: user.username }))
  ], [auditLogs, users]);
  const filteredLogs = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("zh-CN");
    return auditLogs.filter((log) => {
      const matchesAction = actionFilter === "all" || log.action === actionFilter;
      const matchesActor = actorFilter === "all"
        || (actorFilter === "system" ? log.user_id === null : actorFilter === `user:${log.user_id}`);
      const searchable = [
        actorLabel(log),
        actionLabel(log.action),
        entityLabel(log),
        log.action,
        log.entity_type
      ].join(" ").toLocaleLowerCase("zh-CN");
      return matchesAction && matchesActor && (!query || searchable.includes(query));
    });
  }, [actionFilter, actorFilter, auditLogs, search, users]);

  return (
    <Card className="admin-panel-card audit-log-panel" title="操作记录" extra={<Typography.Text type="secondary">最多显示 200 条</Typography.Text>}>
      {error ? (
        <Alert
          type="error"
          showIcon
          title="无法读取操作记录"
          description={error}
          action={<Button size="small" onClick={() => void onRetry()}>重新加载</Button>}
        />
      ) : loading ? (
        <div className="admin-panel-busy" aria-live="polite">
          <Spin description="正在读取操作记录" />
        </div>
      ) : (
        <>
          <div className="audit-log-toolbar">
            <div className="audit-filter-field audit-search-field">
              <label htmlFor="audit-log-search">搜索</label>
              <Input.Search
                id="audit-log-search"
                aria-label="搜索操作记录"
                allowClear
                value={search}
                placeholder="操作人、操作或对象"
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
            <div className="audit-filter-field">
              <label htmlFor="audit-action-filter">操作类型</label>
              <Select
                id="audit-action-filter"
                aria-label="操作类型筛选"
                value={actionFilter}
                options={actionOptions}
                onChange={setActionFilter}
              />
            </div>
            <div className="audit-filter-field">
              <label htmlFor="audit-actor-filter">操作人</label>
              <Select
                id="audit-actor-filter"
                aria-label="操作人筛选"
                value={actorFilter}
                options={actorOptions}
                onChange={setActorFilter}
              />
            </div>
            <Typography.Text className="audit-result-count" type="secondary">
              显示 {filteredLogs.length} / {auditLogs.length} 条
            </Typography.Text>
          </div>
          <Table<AuditLog>
            rowKey="id"
            dataSource={filteredLogs}
            components={AUDIT_TABLE_COMPONENTS}
            pagination={{ pageSize: 15, showSizeChanger: false }}
            locale={{ emptyText: search || actionFilter !== "all" || actorFilter !== "all" ? "没有匹配的操作记录" : "暂无操作记录" }}
            columns={[
              {
                title: "时间",
                dataIndex: "created_at",
                width: 210,
                render: (value: string) => <span className="audit-date">{formatBeijingDateTime(value)}</span>
              },
              {
                title: "操作人",
                dataIndex: "user_id",
                width: 180,
                render: (_, log) => <span className={log.user_id === null ? "audit-system-actor" : ""}>{actorLabel(log)}</span>
              },
              {
                title: "操作",
                dataIndex: "action",
                width: 230,
                onCell: (log) => ({ className: `audit-action-cell audit-action-${actionColor(log.action)}` }),
                render: (action: string) => actionLabel(action)
              },
              {
                title: "对象",
                width: 260,
                render: (_, log) => <span className="audit-entity">{entityLabel(log)}</span>
              }
            ]}
          />
        </>
      )}
    </Card>
  );
}
