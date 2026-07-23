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
  create_input_draft: "创建库位草稿",
  resume_input_draft: "继续库位草稿",
  import_input_draft: "导入库位草稿",
  discard_input_draft: "放弃库位草稿",
  publish_input_draft: "发布库位版本",
  publish_overreceipt_rule: "发布超收规则",
  activate_overreceipt_rule: "启用超收规则",
  create_batch: "创建批次",
  upload_batch_file: "上传交货文件",
  delete_batch_file: "删除交货文件",
  reorder_batch_files: "调整文件顺序",
  preflight_batch: "执行预检",
  queue_compute: "启动计算",
  queue_export: "生成导出",
  save_split: "保存拆分",
  worker_compute_succeeded: "计算完成",
  worker_export_succeeded: "导出完成",
  worker_compute_failed: "计算失败",
  worker_export_failed: "导出失败"
};

const ENTITY_LABELS: Record<string, string> = {
  batch: "批次",
  user: "用户",
  input_version: "基础资料版本",
  input_draft: "库位草稿",
  overreceipt_rule: "超收规则",
  batch_file: "交货文件",
  split: "拆分记录"
};

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
    : "系统 Worker";
  const entityLabel = (log: AuditLog) => `${ENTITY_LABELS[log.entity_type] ?? log.entity_type} #${log.entity_id}`;
  const actionOptions = useMemo(() => [
    { value: "all", label: "全部操作" },
    ...[...new Set(auditLogs.map((log) => log.action))]
      .sort((left, right) => (AUDIT_LABELS[left] ?? left).localeCompare(AUDIT_LABELS[right] ?? right, "zh-CN"))
      .map((action) => ({ value: action, label: AUDIT_LABELS[action] ?? action }))
  ], [auditLogs]);
  const actorOptions = useMemo(() => [
    { value: "all", label: "全部操作人" },
    ...(auditLogs.some((log) => log.user_id === null) ? [{ value: "system", label: "系统 Worker" }] : []),
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
        AUDIT_LABELS[log.action] ?? log.action,
        entityLabel(log),
        log.action,
        log.entity_type
      ].join(" ").toLocaleLowerCase("zh-CN");
      return matchesAction && matchesActor && (!query || searchable.includes(query));
    });
  }, [actionFilter, actorFilter, auditLogs, search, users]);

  return (
    <Card className="admin-panel-card audit-log-panel" title="最近 200 条操作记录">
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
                render: (action: string) => AUDIT_LABELS[action] ?? action
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
