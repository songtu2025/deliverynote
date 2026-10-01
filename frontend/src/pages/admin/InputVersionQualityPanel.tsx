import { Alert, Space, Tag, Typography } from "antd";

import type { InputVersionInspection, PositionIssue } from "../../types";
import type { InputKind } from "./adminConstants";
import { IssueList } from "./PositionFeedback";

interface InputVersionQualityPanelProps {
  kind: InputKind;
  hasActiveVersion: boolean;
  summary: InputVersionInspection["summary"] | null;
  errors: number;
  warnings: number;
}

function describeExcelRows(issue: PositionIssue): string | undefined {
  return issue.row_numbers.length > 0 ? `涉及 Excel 行：${issue.row_numbers.join("、")}` : undefined;
}

export function InputVersionQualityPanel({
  kind,
  hasActiveVersion,
  summary,
  errors,
  warnings
}: InputVersionQualityPanelProps) {
  if (!hasActiveVersion) {
    return <Typography.Text type="secondary">启用资料后显示检查结果。</Typography.Text>;
  }
  if (!summary) {
    return <Typography.Text type="secondary">等待检查结果。</Typography.Text>;
  }
  if (kind !== "position" && kind !== "supplier") {
    return <Alert type="info" showIcon title="文件结构已通过校验，当前未执行内容质量诊断" />;
  }
  if (summary.issues.length === 0) {
    return <Alert type="success" showIcon title="未发现资料质量问题" />;
  }
  return (
    <IssueList issues={summary.issues} className="input-data-quality-list" describeRows={describeExcelRows}>
      <Space wrap size={[6, 6]}>
        <Tag color={errors > 0 ? "error" : "default"}>{errors} 个错误</Tag>
        <Tag color={warnings > 0 ? "warning" : "default"}>{warnings} 个警告</Tag>
      </Space>
    </IssueList>
  );
}
