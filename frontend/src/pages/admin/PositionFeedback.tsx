import { Alert, Button, Space, Tag, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

import { formatBeijingDateTime } from "../../dateTime";
import type { PositionDiff, PositionDraft, PositionIssue } from "../../types";

function issueRows(issue: PositionIssue): string {
  return issue.row_numbers.length > 0 ? `第 ${issue.row_numbers.join("、")} 行` : "全表";
}

interface PositionDraftStatusProps {
  draft: PositionDraft;
  baseVersionChanged: boolean;
  conflictMessage: string | null;
  refreshing: boolean;
  actionError: string | null;
  importError: string | null;
  onRefresh: () => Promise<void>;
  onClearActionError: () => void;
  onClearImportError: () => void;
}

export function PositionDraftStatus({
  draft,
  baseVersionChanged,
  conflictMessage,
  refreshing,
  actionError,
  importError,
  onRefresh,
  onClearActionError,
  onClearImportError
}: PositionDraftStatusProps) {
  return (
    <>
      <Alert
        className="inline-alert position-save-status"
        type="success"
        showIcon
        title="草稿已自动保存"
        description={
          <Space wrap separator={<span aria-hidden="true">·</span>}>
            <span>修订号 {draft.revision}</span>
            <span>最后更新 {formatBeijingDateTime(draft.updated_at)}</span>
            <span>最后编辑人：用户 #{draft.updated_by}</span>
          </Space>
        }
      />
      {baseVersionChanged && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          title="草稿基线已过期"
          description={`正式版本已变为 ${draft.active_version_name ?? "无启用版本"}。请放弃当前草稿后重新维护。`}
        />
      )}
      {conflictMessage && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          title="草稿已在其他位置更新"
          description={conflictMessage}
          action={
            <Button
              aria-label="刷新草稿"
              icon={<ReloadOutlined />}
              loading={refreshing}
              onClick={() => void onRefresh()}
            >
              刷新草稿
            </Button>
          }
        />
      )}
      {actionError && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          closable
          title="操作失败"
          description={actionError}
          onClose={onClearActionError}
        />
      )}
      {importError && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          closable
          title="Excel 替换未完成"
          description={importError}
          onClose={onClearImportError}
        />
      )}
    </>
  );
}

export function DiffTags({ diff }: { diff: PositionDiff }) {
  return (
    <Space wrap size={[6, 6]}>
      <Tag color="green">新增 {diff.added}</Tag>
      <Tag color="blue">修改 {diff.modified}</Tag>
      <Tag color="red">删除 {diff.deleted}</Tag>
      <Tag>未变化 {diff.unchanged}</Tag>
    </Space>
  );
}

export function DraftSummary({
  draft,
  diff
}: {
  draft: Pick<PositionDraft, "row_count" | "modified_count" | "error_count" | "warning_count">;
  diff: PositionDiff;
}) {
  return (
    <section className="position-summary-strip" aria-label="草稿摘要">
      <div className="position-summary-metric">
        <span>草稿记录</span>
        <strong>{draft.row_count}</strong>
        <small>服务器草稿</small>
      </div>
      <div className="position-summary-metric">
        <span>已变更</span>
        <strong>{draft.modified_count}</strong>
        <small>待发布记录</small>
      </div>
      <div className={`position-summary-metric${draft.error_count > 0 ? " is-error" : ""}`}>
        <span>错误</span>
        <strong>{draft.error_count}</strong>
        <small>{draft.error_count > 0 ? "发布前必须修正" : "无阻断项"}</small>
      </div>
      <div className={`position-summary-metric${draft.warning_count > 0 ? " is-warning" : ""}`}>
        <span>警告</span>
        <strong>{draft.warning_count}</strong>
        <small>{draft.warning_count > 0 ? "发布前需要确认" : "无需确认"}</small>
      </div>
      <div className="position-summary-diff">
        <span>相对正式版</span>
        <DiffTags diff={diff} />
      </div>
    </section>
  );
}

export function IssueList({ issues }: { issues: PositionIssue[] }) {
  if (issues.length === 0) return <Typography.Text type="secondary">没有发现问题</Typography.Text>;
  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      {issues.map((issue, index) => (
        <Alert
          key={`${issue.code}-${index}-${issue.row_numbers.join("-")}`}
          type={issue.severity}
          showIcon
          title={issue.message}
          description={issueRows(issue)}
        />
      ))}
    </Space>
  );
}
