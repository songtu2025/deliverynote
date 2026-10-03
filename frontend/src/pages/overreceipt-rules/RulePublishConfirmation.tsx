import { Space, Tag, Typography } from "antd";
import type { RuleForm, SelfOperatedRuleForm } from "./ruleTypes";

export function DeliveryPublishSummary({ values }: { values: RuleForm }) {
  return (
    <div className="overreceipt-confirm-summary">
      <Typography.Text strong>{values.name}</Typography.Text>
      <Space wrap>
        <Tag color="green">短尾 +{values.short_tail_limit} 件</Tag>
        <Tag color="blue">中尾 +{values.medium_tail_limit} 件</Tag>
        <Tag>长尾 +{values.long_tail_limit} 件</Tag>
      </Space>
      <div className="overreceipt-confirm-warehouses">
        <Typography.Text type="secondary">允许超收仓库（精确匹配）</Typography.Text>
        {values.allowed_warehouses.length ? (
          <Space wrap>
            {values.allowed_warehouses.map((warehouse) => (
              <Tag key={warehouse}>{warehouse}</Tag>
            ))}
          </Space>
        ) : (
          <Typography.Text type="warning">未开放任何仓库（不会自动超收）</Typography.Text>
        )}
      </div>
      <Typography.Text type="secondary">参数发布后不可修改；新版本仅用于新批次。</Typography.Text>
    </div>
  );
}

export function SelfOperatedPublishSummary({ values }: { values: SelfOperatedRuleForm }) {
  return (
    <div className="overreceipt-confirm-summary">
      <Typography.Text strong>{values.name}</Typography.Text>
      <Typography.Text>每个“供应商 + SKU + 完整站点”在新批次内共享 {values.allowance} 件超收额度。</Typography.Text>
      <Typography.Text type="secondary">
        规则内超收数量挂到最后一个 PO 单，且不会改变上游交货量或采购量。
      </Typography.Text>
    </div>
  );
}
