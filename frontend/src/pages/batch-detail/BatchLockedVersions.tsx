import { useState } from "react";
import { Button, Card, Descriptions, Space, Tooltip } from "antd";
import { LockOutlined } from "@ant-design/icons";
import type { Batch, InputVersion } from "../../types";

const VERSION_LABELS: Record<string, string> = {
  purchase: "采购需求",
  product: "商品信息",
  supplier: "供应商资料",
  position: "MSKU定位",
  template: "导出模板",
  inbound_template: "积加入库模板"
};

export default function BatchLockedVersions({
  batch,
  activeSupplierVersion,
  canRefreshSupplierVersion,
  action,
  refreshSupplierVersion
}: {
  batch: Batch;
  activeSupplierVersion: InputVersion | null;
  canRefreshSupplierVersion: boolean;
  action: string | null;
  refreshSupplierVersion: () => Promise<void>;
}) {
  const [lockedDataOpen, setLockedDataOpen] = useState(true);
  const canAdoptCurrentSupplier = Boolean(
    canRefreshSupplierVersion &&
    batch.status === "draft" &&
    activeSupplierVersion &&
    activeSupplierVersion.id !== batch.version_ids.supplier
  );
  return (
    <Card
      title={
        <span className="locked-data-title">
          <LockOutlined /> 批次锁定版本
        </span>
      }
      className={`section-card compact-card locked-data-card ${lockedDataOpen ? "" : "is-collapsed"}`}
      extra={
        <Space size="small">
          {canAdoptCurrentSupplier && (
            <Button
              size="small"
              loading={action === "refresh-supplier-version"}
              onClick={() => void refreshSupplierVersion()}
            >
              采用当前供应商资料
            </Button>
          )}
          <Button
            type="link"
            size="small"
            aria-expanded={lockedDataOpen}
            onClick={() => setLockedDataOpen((open) => !open)}
          >
            {lockedDataOpen ? "收起锁定版本" : "查看锁定版本"}
          </Button>
        </Space>
      }
    >
      {lockedDataOpen && (
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 6 }}>
          {Object.entries(batch.versions ?? {}).map(([kind, version]) => (
            <Descriptions.Item key={kind} label={VERSION_LABELS[kind] ?? kind}>
              <Tooltip title={version.original_name}>{version.name}</Tooltip>
            </Descriptions.Item>
          ))}
          <Descriptions.Item label="超收规则">
            <LockedOverreceiptRule batch={batch} />
          </Descriptions.Item>
        </Descriptions>
      )}
    </Card>
  );
}

function LockedOverreceiptRule({ batch }: { batch: Batch }) {
  const selfOperated = batch.workflow === "self_operated_inbound";
  return (
    <>
      {selfOperated ? (
        batch.self_operated_overreceipt_rule ? (
          <span className="locked-overreceipt-rule">
            <strong>{batch.self_operated_overreceipt_rule.name}</strong>
            <small>每个供应商 + SKU + 站点共享 +{batch.self_operated_overreceipt_rule.allowance}</small>
          </span>
        ) : (
          "未启用（不自动超收）"
        )
      ) : batch.overreceipt_rule ? (
        <span className="locked-overreceipt-rule">
          <strong>{batch.overreceipt_rule.name}</strong>
          <small>
            短尾 +{batch.overreceipt_rule.short_tail_limit} / 中尾 +{batch.overreceipt_rule.medium_tail_limit} / 长尾 +
            {batch.overreceipt_rule.long_tail_limit}
          </small>
        </span>
      ) : (
        "未启用（不自动超收）"
      )}
    </>
  );
}
