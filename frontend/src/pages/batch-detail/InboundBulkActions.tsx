import { useRef, useState } from "react";
import { App, Button, Input, Space, Tooltip } from "antd";
import type { Batch, DeliveryException } from "../../types";
import { saveOfflineHandlingBatch } from "../../inboundExceptionApi";
import { remainingTransferQuantity } from "../../exceptionTransferApi";
import { offlineSelectionDisabledReason } from "./inboundHandling";

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
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const saving = useRef(false);
  const reason = offlineSelectionDisabledReason(batch, records);
  const save = async () => {
    if (saving.current || reason) return;
    saving.current = true;
    setBusy(true);
    try {
      const { succeeded, failures } = await saveOfflineHandlingBatch(
        records.map((record) => ({
          id: record.id,
          quantity: remainingTransferQuantity(record) + (record.offline_quantity ?? 0),
          note
        }))
      );
      await onSaved();
      const summary = `已线下处理 ${succeeded} 条`;
      if (failures.length) message.warning(`${summary}，失败 ${failures.length} 条：${failures[0]}`);
      else {
        setNote("");
        message.success(summary);
      }
    } catch (failure) {
      message.error(failure instanceof Error ? failure.message : "批量处理失败");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  return (
    <Space wrap>
      <label htmlFor="inbound-offline-note">线下备注（选填）</label>
      <Input
        id="inbound-offline-note"
        aria-label="线下备注（选填）"
        value={note}
        disabled={busy}
        style={{ width: 180 }}
        onChange={(event) => setNote(event.target.value)}
      />
      <Tooltip title={reason} trigger={["hover", "focus"]}>
        <span tabIndex={reason ? 0 : undefined}>
          <Button disabled={Boolean(reason) || busy} loading={busy} onClick={() => void save()}>
            线下处理
          </Button>
        </span>
      </Tooltip>
    </Space>
  );
}
