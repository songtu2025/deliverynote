import { Alert, Space, Tag, Typography } from "antd";

import type { PositionDiff, PositionIssue } from "../../types";

function issueRows(issue: PositionIssue): string {
  return issue.row_numbers.length > 0 ? `第 ${issue.row_numbers.join("、")} 行` : "全表";
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
