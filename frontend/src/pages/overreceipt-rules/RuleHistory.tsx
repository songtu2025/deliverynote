import { Button, Card, Space, Table, Typography } from "antd";
import { formatBeijingDate, formatBeijingTime } from "../../dateTime";
import type { OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "../../types";
import { RuleLimits } from "./RuleOverview";
import type { RenameRuleTarget } from "./ruleTypes";
import type { RuleScope } from "../../overreceiptRuleApi";

const publicationColumns = [
  {
    title: "发布人",
    dataIndex: "created_by",
    width: 100,
    render: (value: number) => `用户 #${value}`
  },
  {
    title: "发布时间",
    dataIndex: "created_at",
    width: 150,
    render: (value: string) => (
      <span className="overreceipt-published-at">
        {formatBeijingDate(value)}
        <small>{formatBeijingTime(value)}</small>
      </span>
    )
  }
];

export function RuleHistory({
  scope,
  rules,
  selfOperatedRules,
  loading,
  activatingId,
  selfOperatedActivatingId,
  onActivate,
  onActivateSelfOperated,
  onRename
}: {
  scope: RuleScope;
  rules: OverreceiptRuleVersion[];
  selfOperatedRules: SelfOperatedOverreceiptRuleVersion[];
  loading: boolean;
  activatingId?: number;
  selfOperatedActivatingId?: number;
  onActivate: (rule: OverreceiptRuleVersion) => void;
  onActivateSelfOperated: (rule: SelfOperatedOverreceiptRuleVersion) => void;
  onRename: (target: RenameRuleTarget) => void;
}) {
  const isSelfOperated = scope === "self_operated";
  const historicalRules = rules.filter((rule) => !rule.active);
  const historicalSelfOperatedRules = selfOperatedRules.filter((rule) => !rule.active);
  const count = isSelfOperated ? historicalSelfOperatedRules.length : historicalRules.length;
  const emptyText = (
    <div className="overreceipt-history-empty">
      <strong>暂无历史版本</strong>
      <span>发布新版本后，原版本会移到这里。</span>
    </div>
  );

  return (
    <Card
      className="section-card overreceipt-history-card"
      title={
        <div className="overreceipt-history-heading">
          <strong>历史版本</strong>
          <small>可重新启用于新批次。</small>
        </div>
      }
      extra={<Typography.Text type="secondary">{count} 个历史版本</Typography.Text>}
    >
      {isSelfOperated ? (
        loading || historicalSelfOperatedRules.length > 0 ? (
          <Table<SelfOperatedOverreceiptRuleVersion>
            className="overreceipt-history-table"
            rowKey="id"
            loading={loading}
            dataSource={historicalSelfOperatedRules}
            pagination={false}
            locale={{ emptyText }}
            tableLayout="fixed"
            components={{
              table: (props) => <table {...props} aria-label="自营仓超收规则历史版本" />
            }}
            columns={[
              {
                title: "版本",
                dataIndex: "name",
                render: (name: string) => <Typography.Text strong>{name}</Typography.Text>
              },
              {
                title: "允许超收",
                dataIndex: "allowance",
                width: 118,
                render: (value: number) => <strong className="overreceipt-allowance-value">+{value} 件</strong>
              },
              {
                title: "共享范围",
                width: 250,
                render: () => (
                  <span className="overreceipt-table-stack">
                    供应商 + SKU + 完整站点
                    <small>批次内共享</small>
                  </span>
                )
              },
              ...publicationColumns,
              {
                title: "操作",
                width: 174,
                render: (_, rule) => (
                  <Space size={0}>
                    <Button
                      type="link"
                      aria-label={`重命名 ${rule.name}`}
                      onClick={() => onRename({ scope: "self_operated", rule })}
                    >
                      重命名
                    </Button>
                    <Button
                      type="link"
                      aria-label={`重新启用 ${rule.name}`}
                      loading={selfOperatedActivatingId === rule.id}
                      onClick={() => onActivateSelfOperated(rule)}
                    >
                      重新启用
                    </Button>
                  </Space>
                )
              }
            ]}
          />
        ) : (
          emptyText
        )
      ) : loading || historicalRules.length > 0 ? (
        <Table<OverreceiptRuleVersion>
          className="overreceipt-history-table"
          rowKey="id"
          loading={loading}
          dataSource={historicalRules}
          pagination={false}
          locale={{ emptyText }}
          tableLayout="fixed"
          components={{
            table: (props) => <table {...props} aria-label="超收规则不可变版本" />
          }}
          columns={[
            {
              title: "版本",
              dataIndex: "name",
              width: 190,
              render: (name: string) => <Typography.Text strong>{name}</Typography.Text>
            },
            {
              title: "额度",
              width: 200,
              render: (_, rule) => <RuleLimits rule={rule} />
            },
            {
              title: "允许仓库",
              render: (_, rule) =>
                rule.allowed_warehouses.length ? (
                  rule.allowed_warehouses.join("、")
                ) : (
                  <Typography.Text type="secondary">未开放任何仓库</Typography.Text>
                )
            },
            ...publicationColumns,
            {
              title: "操作",
              width: 174,
              render: (_, rule) => (
                <Space size={0}>
                  <Button
                    type="link"
                    aria-label={`重命名 ${rule.name}`}
                    onClick={() => onRename({ scope: "delivery", rule })}
                  >
                    重命名
                  </Button>
                  <Button
                    type="link"
                    aria-label={`重新启用 ${rule.name}`}
                    loading={activatingId === rule.id}
                    onClick={() => onActivate(rule)}
                  >
                    重新启用
                  </Button>
                </Space>
              )
            }
          ]}
        />
      ) : (
        emptyText
      )}
    </Card>
  );
}
