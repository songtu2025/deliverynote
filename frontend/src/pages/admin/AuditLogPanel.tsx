import { Alert, Button, Card, Spin, Table } from "antd";

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

interface AuditLogPanelProps {
  auditLogs: AuditLog[];
  users: User[];
  loading: boolean;
  error: string | null;
  onRetry: () => void | Promise<void>;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN");
}

export function AuditLogPanel({ auditLogs, users, loading, error, onRetry }: AuditLogPanelProps) {
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
        <Table<AuditLog>
          rowKey="id"
          dataSource={auditLogs}
          scroll={{ x: 820 }}
          pagination={{ pageSize: 15, showSizeChanger: false }}
          locale={{ emptyText: "暂无操作记录" }}
          columns={[
            { title: "时间", dataIndex: "created_at", width: 200, render: formatDate },
            {
              title: "操作人",
              dataIndex: "user_id",
              width: 160,
              render: (id: number | null) => id
                ? users.find((user) => user.id === id)?.username ?? `用户 #${id}`
                : "系统 Worker"
            },
            {
              title: "操作",
              dataIndex: "action",
              width: 200,
              render: (action: string) => AUDIT_LABELS[action] ?? action
            },
            {
              title: "对象",
              width: 220,
              render: (_, log) => `${log.entity_type} #${log.entity_id}`
            }
          ]}
        />
      )}
    </Card>
  );
}
