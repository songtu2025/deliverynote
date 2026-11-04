import { useState } from "react";
import { Button, Modal, Space, Tooltip } from "antd";
import type { Batch, DeliveryException } from "../../types";
import { remainingTransferQuantity, transferDisabledReason } from "../../exceptionTransferApi";
import { inboundRowActions } from "./inboundRowActions";
import ManualAllowanceForm, { allowanceDisabledReason } from "./ManualAllowanceForm";
import OfflineHandlingForm, { offlineDisabledReason } from "./OfflineHandlingForm";

export default function InboundExceptionActions({
  batch,
  record,
  supplierCode,
  onOpen,
  onTransfer,
  onSaved
}: {
  batch: Batch;
  record: DeliveryException;
  supplierCode: string;
  onOpen: (record: DeliveryException) => void;
  onTransfer: (record: DeliveryException) => void;
  onSaved: () => Promise<unknown>;
}) {
  const [form, setForm] = useState<"allowance" | "offline" | null>(null);
  const remaining = remainingTransferQuantity(record);
  const actions = inboundRowActions(record.reason, true, { remaining });
  const saved = async () => {
    await onSaved();
    setForm(null);
  };
  const labels = { allowance: "追加超收", offline: "线下处理", transfer: "转交货" };
  const disabled = {
    allowance: allowanceDisabledReason(batch),
    offline: offlineDisabledReason(batch, remaining),
    transfer: transferDisabledReason(batch) || (record.status !== "pending" ? "当前行不可转交货" : null)
  };
  return (
    <>
      <Space wrap size="small">
        {actions.map((action) => {
          if (action !== "allowance" && action !== "offline" && action !== "transfer") return null;
          return (
            <Tooltip key={action} title={disabled[action]} trigger={["hover", "focus"]}>
              <span tabIndex={disabled[action] ? 0 : undefined}>
                <Button
                  type={action === actions[0] ? "default" : "text"}
                  color={action === actions[0] ? "primary" : "default"}
                  variant={action === actions[0] ? "outlined" : "text"}
                  disabled={Boolean(disabled[action])}
                  onClick={() => (action === "transfer" ? onTransfer(record) : setForm(action))}
                >
                  {labels[action]}
                </Button>
              </span>
            </Tooltip>
          );
        })}
        <Button type="text" onClick={() => onOpen(record)}>
          查看并处理
        </Button>
      </Space>
      <Modal
        title={form === "allowance" ? "追加超收" : "线下处理"}
        open={form !== null}
        onCancel={() => setForm(null)}
        footer={null}
        destroyOnHidden
        width={480}
      >
        {form === "allowance" && (
          <ManualAllowanceForm
            batch={batch}
            supplierCode={supplierCode}
            sku={record.sku}
            fullSite={record.full_site}
            remaining={remaining}
            onSaved={saved}
          />
        )}
        {form === "offline" && <OfflineHandlingForm batch={batch} exception={record} onSaved={saved} />}
      </Modal>
    </>
  );
}
