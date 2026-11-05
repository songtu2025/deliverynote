import { Button, Space, Tooltip } from "antd";
import type { Batch, DeliveryException } from "../../types";
import { remainingTransferQuantity, transferDisabledReason } from "../../exceptionTransferApi";
import { inboundRowActions } from "./inboundRowActions";
import { allowanceFor, allowanceDisabledReason, offlineDisabledReason } from "./inboundHandling";
import { useInboundHandling } from "./useInboundHandling";
import ReceiptRowActions from "./ReceiptRowActions";
import { useReceiptSite } from "./useReceiptSite";
import { useBatchAction } from "./useBatchAction";
import { receiptSiteDisabledReason } from "../../receipt";
import { candidateSites } from "./reviewDraft";

export default function InboundExceptionActions({
  batch,
  record,
  supplierCode,
  onOpen,
  onTransfer,
  onVersions,
  onSaved
}: {
  batch: Batch;
  record: DeliveryException;
  supplierCode: string;
  onOpen: (record: DeliveryException) => void;
  onTransfer: (record: DeliveryException) => void;
  onVersions?: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const { action, runAction } = useBatchAction();
  const handling = useInboundHandling(batch.id, onSaved);
  const chooseSite = useReceiptSite(batch.id, runAction, onSaved, () => undefined, batch.status === "succeeded");
  const remaining = remainingTransferQuantity(record);
  const candidates = candidateSites(record.full_site);
  const actions = inboundRowActions(record.reason, true, { remaining, candidates });
  const labels = { allowance: "追加超收", offline: "线下处理", transfer: "转交货" };
  const disabled = {
    allowance: allowanceDisabledReason(batch),
    offline: offlineDisabledReason(batch, remaining),
    transfer: transferDisabledReason(batch) || (record.status !== "pending" ? "当前行不可转交货" : null)
  };
  const handle = (kind: keyof typeof labels) => {
    if (kind === "transfer") return onTransfer(record);
    if (kind === "offline") return quickOffline(handling, record, remaining);
    return quickAllowance(handling, batch, record, supplierCode, remaining);
  };
  return (
    <Space wrap size="small">
      {(actions.includes("site") || actions.includes("versions")) && (
        <ReceiptRowActions
          row={{ ...record, file_id: record.batch_file_id, issue: record.reason, candidates }}
          computed
          remaining={remaining}
          disabledReason={action ? "正在保存站点选择" : receiptSiteDisabledReason(batch)}
          refreshing={false}
          onChooseSite={chooseSite}
          onVersions={onVersions}
        />
      )}
      {actions.map((kind) => {
        if (kind !== "allowance" && kind !== "offline" && kind !== "transfer") return null;
        return (
          <Tooltip key={kind} title={disabled[kind]} trigger={["hover", "focus"]}>
            <span tabIndex={disabled[kind] ? 0 : undefined}>
              <Button
                type={kind === actions[0] ? "default" : "text"}
                color={kind === actions[0] ? "primary" : "default"}
                variant={kind === actions[0] ? "outlined" : "text"}
                disabled={handling.busy || Boolean(disabled[kind]) || Boolean(action)}
                onClick={() => void handle(kind)}
              >
                {labels[kind]}
              </Button>
            </span>
          </Tooltip>
        );
      })}
      <Button type="text" onClick={() => onOpen(record)}>
        查看并处理
      </Button>
    </Space>
  );
}

type Handling = ReturnType<typeof useInboundHandling>;

// 一键线下处理剩余全部数量，撤销时恢复原线下数量与备注。
function quickOffline(handling: Handling, record: DeliveryException, remaining: number) {
  const previous = { quantity: record.offline_quantity ?? 0, reason: record.offline_note ?? "" };
  return handling.saveOffline(record, remaining + previous.quantity, previous.reason, previous);
}

// 一键在原追加额度上加上剩余数量，撤销时恢复原额度与原因。
function quickAllowance(
  handling: Handling,
  batch: Batch,
  record: DeliveryException,
  supplierCode: string,
  remaining: number
) {
  const existing = allowanceFor(batch, supplierCode, record.sku, record.full_site);
  const previous = { quantity: existing?.quantity ?? 0, reason: existing?.reason ?? "" };
  return handling.saveAllowance(
    {
      supplier_code: supplierCode,
      sku: record.sku,
      full_site: record.full_site,
      quantity: previous.quantity + remaining,
      reason: previous.reason
    },
    previous
  );
}
