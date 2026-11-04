import { useState } from "react";
import { App, Flex, Typography } from "antd";
import type { Batch } from "../../types";
import { saveManualAllowance } from "../../inboundExceptionApi";
import HandlingForm, { type HandlingValues } from "./HandlingForm";

export default function ManualAllowanceForm({
  batch,
  supplierCode,
  sku,
  fullSite,
  remaining,
  onSaved
}: {
  batch: Batch;
  supplierCode: string;
  sku: string;
  fullSite: string;
  remaining: number;
  onSaved: () => Promise<void>;
}) {
  const { modal, message } = App.useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const allowance = batch.manual_allowances?.find(
    (item) => item.supplier_code === supplierCode && item.sku === sku && item.full_site === fullSite
  );
  const disabledReason = allowanceDisabledReason(batch);
  const save = async (values: HandlingValues) => {
    setBusy(true);
    setError(null);
    try {
      await saveManualAllowance(batch.id, {
        supplier_code: supplierCode,
        sku,
        full_site: fullSite,
        quantity: values.quantity,
        reason: values.reason
      });
      await onSaved();
      message.success("已排队重算");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "保存追加超收失败");
    } finally {
      setBusy(false);
    }
  };
  const confirm = (values: HandlingValues) =>
    modal.confirm({
      title: values.quantity ? "追加并重算整批？" : "撤销追加并重算整批？",
      content: "将重新计算整批，现有结果需重新生成。",
      okText: "重算整批",
      cancelText: "取消",
      onOk: () => save(values)
    });
  return (
    <Flex vertical gap="small">
      {error && (
        <Typography.Text type="danger" role="alert">
          {error}
        </Typography.Text>
      )}
      <HandlingForm
        key={`${sku}-${fullSite}-${allowance?.quantity}-${allowance?.reason}`}
        title="本批追加超收"
        reasonLabel="原因"
        quantity={allowance?.quantity ?? remaining}
        reason={allowance?.reason ?? ""}
        existing={Boolean(allowance)}
        busy={busy}
        disabledReason={disabledReason}
        button="追加并重算"
        onSubmit={confirm}
        onRevoke={() => confirm({ quantity: 0, reason: "" })}
      />
    </Flex>
  );
}

export function allowanceDisabledReason(batch: Batch) {
  if (batch.manual_allowance_disabled_reason !== undefined) return batch.manual_allowance_disabled_reason;
  return batch.status !== "succeeded" ? "批次尚未计算成功或当前状态不可重算" : null;
}
