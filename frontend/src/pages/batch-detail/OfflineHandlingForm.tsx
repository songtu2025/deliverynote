import { useState } from "react";
import { App, Flex, Typography } from "antd";
import type { Batch, DeliveryException } from "../../types";
import { remainingTransferQuantity } from "../../exceptionTransferApi";
import { saveOfflineHandling } from "../../inboundExceptionApi";
import HandlingForm, { type HandlingValues } from "./HandlingForm";

export default function OfflineHandlingForm({
  batch,
  exception,
  onSaved
}: {
  batch: Batch;
  exception: DeliveryException;
  onSaved: (updated?: DeliveryException) => Promise<void>;
}) {
  const { message } = App.useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const remaining = remainingTransferQuantity(exception);
  const offline = exception.offline_quantity ?? 0;
  const offlineReason = offlineDisabledReason(batch, remaining + offline);
  const save = async (values: HandlingValues) => {
    setBusy("offline");
    setError(null);
    try {
      const updated = await saveOfflineHandling(exception.id, { quantity: values.quantity, note: values.reason });
      await onSaved(updated);
      message.success(values.quantity ? "已保存线下处理" : "已撤销线下处理");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "保存线下处理失败");
    } finally {
      setBusy(null);
    }
  };
  return (
    <Flex vertical gap="small">
      {error && (
        <Typography.Text type="danger" role="alert">
          {error}
        </Typography.Text>
      )}
      <HandlingForm
        key={`offline-${exception.id}-${offline}`}
        title="线下处理"
        reasonLabel="备注"
        quantity={offline || remaining}
        reason={exception.offline_note ?? ""}
        max={remaining + offline}
        existing={offline > 0}
        busy={busy !== null}
        disabledReason={offlineReason}
        button={offline ? "修改线下处理" : "标记已处理"}
        onSubmit={save}
        onRevoke={() => save({ quantity: 0, reason: "" })}
      />
    </Flex>
  );
}

export function offlineDisabledReason(batch: Batch, capacity: number) {
  if (["queued", "running"].includes(batch.jobs?.export?.status ?? "")) return "导出任务运行期间不可修改线下处理";
  if (batch.status !== "succeeded") return "批次尚未计算成功";
  return capacity === 0 ? "没有剩余可处理量" : null;
}
