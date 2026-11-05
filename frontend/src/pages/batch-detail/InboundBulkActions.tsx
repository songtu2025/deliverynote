import { useRef, useState } from "react";
import { App, Button, Tooltip } from "antd";
import type { Batch, DeliveryException } from "../../types";
import { saveManualAllowance, saveOfflineHandlingBatch } from "../../inboundExceptionApi";
import { remainingTransferQuantity } from "../../exceptionTransferApi";
import { allowanceItems, handlingDisabledReason, type HandlingKind } from "./inboundHandling";

export default function InboundBulkActions({
  batch,
  records,
  onSaved
}: {
  batch: Batch;
  records: DeliveryException[];
  onSaved: () => Promise<unknown>;
}) {
  const { message } = App.useApp();
  const [busy, setBusy] = useState<HandlingKind | null>(null);
  const saving = useRef(false);
  const save = async (kind: HandlingKind) => {
    if (saving.current) return;
    saving.current = true;
    setBusy(kind);
    let succeeded = 0;
    let failures: string[] = [];
    try {
      if (kind === "allowance") {
        const files = Object.fromEntries((batch.files ?? []).map((file) => [file.id, file]));
        await saveManualAllowance(batch.id, { items: allowanceItems(batch, records, files) });
        succeeded = records.length;
      } else {
        ({ succeeded, failures } = await saveOfflineHandlingBatch(
          records.map((record) => ({
            id: record.id,
            quantity: remainingTransferQuantity(record) + (record.offline_quantity ?? 0),
            note: record.offline_note ?? ""
          }))
        ));
      }
      await onSaved();
      const summary = `已${kind === "allowance" ? "追加超收" : "线下处理"} ${succeeded} 条`;
      if (failures.length) message.warning(`${summary}，失败 ${failures.length} 条：${failures[0]}`);
      else message.success(summary);
    } catch (failure) {
      message.error(failure instanceof Error ? failure.message : "批量处理失败");
    } finally {
      saving.current = false;
      setBusy(null);
    }
  };
  return (["allowance", "offline"] as const).map((kind) => {
    const reason = handlingDisabledReason(batch, records, kind);
    return (
      <Tooltip key={kind} title={reason} trigger={["hover", "focus"]}>
        <span tabIndex={reason ? 0 : undefined}>
          <Button disabled={Boolean(reason) || busy !== null} loading={busy === kind} onClick={() => void save(kind)}>
            {kind === "allowance" ? "追加超收" : "线下处理"}
          </Button>
        </span>
      </Tooltip>
    );
  });
}
