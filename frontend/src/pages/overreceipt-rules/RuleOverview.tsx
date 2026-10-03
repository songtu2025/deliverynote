import { Button, Card, Empty, Space, Tag, Typography } from "antd";
import { CheckCircleFilled, EditOutlined, PlusOutlined } from "@ant-design/icons";
import type { OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "../../types";
import type { RuleScope } from "../../overreceiptRuleApi";

export function RuleLimits({ rule }: { rule: OverreceiptRuleVersion }) {
  return (
    <Space className="rule-limit-list" wrap>
      <Tag color="green">短尾 +{rule.short_tail_limit}</Tag>
      <Tag color="blue">中尾 +{rule.medium_tail_limit}</Tag>
      <Tag>长尾 +{rule.long_tail_limit}</Tag>
    </Space>
  );
}

export function RuleScopeSwitcher({
  scope,
  activeDeliveryRuleName,
  activeSelfOperatedAllowance,
  onChange
}: {
  scope: RuleScope;
  activeDeliveryRuleName?: string;
  activeSelfOperatedAllowance?: number;
  onChange: (scope: RuleScope) => void;
}) {
  return (
    <div className="overreceipt-scope-switcher" aria-label="超收规则范围">
      <button
        type="button"
        className={scope === "delivery" ? "is-active" : ""}
        aria-pressed={scope === "delivery"}
        onClick={() => onChange("delivery")}
      >
        <span className="overreceipt-scope-copy">
          <strong>交货超收</strong>
        </span>
        <span className={`overreceipt-scope-badge ${activeDeliveryRuleName ? "" : "is-disabled"}`}>
          {activeDeliveryRuleName ? `当前版本 ${activeDeliveryRuleName}` : "未启用"}
        </span>
      </button>
      <button
        type="button"
        className={scope === "self_operated" ? "is-active" : ""}
        aria-pressed={scope === "self_operated"}
        onClick={() => onChange("self_operated")}
      >
        <span className="overreceipt-scope-copy">
          <strong>自营仓入库</strong>
        </span>
        <span className={`overreceipt-scope-badge ${activeSelfOperatedAllowance !== undefined ? "" : "is-disabled"}`}>
          {activeSelfOperatedAllowance !== undefined ? `每键 +${activeSelfOperatedAllowance} 件` : "未启用"}
        </span>
      </button>
    </div>
  );
}

export function CurrentSelfOperatedRule({
  rule,
  loading,
  onPublish,
  onRename
}: {
  rule?: SelfOperatedOverreceiptRuleVersion;
  loading: boolean;
  onPublish: () => void;
  onRename: (rule: SelfOperatedOverreceiptRuleVersion) => void;
}) {
  return (
    <Card className="section-card overreceipt-current-card" loading={loading}>
      <div className="overreceipt-current-heading">
        <div>
          <Typography.Text className="overreceipt-eyebrow">当前启用规则</Typography.Text>
          {rule ? (
            <div className="overreceipt-current-title">
              <Typography.Title level={4}>{rule.name}</Typography.Title>
              <Tag color="success" icon={<CheckCircleFilled />}>
                用于新批次
              </Tag>
            </div>
          ) : (
            <Typography.Title level={4}>尚未启用自营仓超收规则</Typography.Title>
          )}
        </div>
        <Space>
          {rule ? (
            <Button icon={<EditOutlined />} aria-label={`重命名 ${rule.name}`} onClick={() => onRename(rule)}>
              重命名
            </Button>
          ) : null}
          <Button type="primary" icon={<PlusOutlined />} onClick={onPublish}>
            发布新版本
          </Button>
        </Space>
      </div>
      {rule ? (
        <div className="overreceipt-metric-grid">
          <div className="overreceipt-metric is-accent">
            <span>超收额度</span>
            <strong>+{rule.allowance} 件</strong>
            <small>每个匹配键</small>
          </div>
          <div className="overreceipt-metric">
            <span>额度共享范围</span>
            <strong>供应商 + SKU + 完整站点</strong>
            <small>同一批次共用额度</small>
          </div>
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="新建批次允许超收数量为 0" />
      )}
    </Card>
  );
}

export function CurrentDeliveryRule({
  rule,
  loading,
  onPublish,
  onRename
}: {
  rule?: OverreceiptRuleVersion;
  loading: boolean;
  onPublish: () => void;
  onRename: (rule: OverreceiptRuleVersion) => void;
}) {
  return (
    <Card className="section-card overreceipt-current-card" loading={loading}>
      <div className="overreceipt-current-heading">
        <div>
          <Typography.Text className="overreceipt-eyebrow">当前启用规则</Typography.Text>
          {rule ? (
            <div className="overreceipt-current-title">
              <Typography.Title level={4}>{rule.name}</Typography.Title>
              <Tag color="success" icon={<CheckCircleFilled />}>
                用于新批次
              </Tag>
            </div>
          ) : (
            <Typography.Title level={4}>尚未启用普通交货超收规则</Typography.Title>
          )}
        </div>
        <Space>
          {rule ? (
            <Button icon={<EditOutlined />} aria-label={`重命名 ${rule.name}`} onClick={() => onRename(rule)}>
              重命名
            </Button>
          ) : null}
          <Button type="primary" icon={<PlusOutlined />} onClick={onPublish}>
            发布新版本
          </Button>
        </Space>
      </div>
      {rule ? (
        <div className="overreceipt-metric-grid">
          <div className="overreceipt-metric is-accent">
            <span>规模定位额度</span>
            <RuleLimits rule={rule} />
            <small>分别控制短尾、中尾和长尾</small>
          </div>
          <div className="overreceipt-metric">
            <span>允许超收仓库</span>
            <strong>{rule.allowed_warehouses.length ? rule.allowed_warehouses.join("、") : "未开放任何仓库"}</strong>
            <small>目的仓名称必须精确匹配</small>
          </div>
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="新批次不会自动超收" />
      )}
    </Card>
  );
}
