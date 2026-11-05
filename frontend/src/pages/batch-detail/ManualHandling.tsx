import { Card, Flex, Select, Typography } from "antd";
import { useState } from "react";
import type { Batch, DeliveryException } from "../../types";
import { remainingTransferQuantity } from "../../exceptionTransferApi";
import HandlingForm from "./HandlingForm";
import { allowanceFor, handlingFormState, type HandlingKind } from "./inboundHandling";
import { inboundRowActions } from "./inboundRowActions";
import { useInboundHandling } from "./useInboundHandling";

export default function ManualHandling({
  batch,
  exception,
  supplierCode,
  onSaved
}: {
  batch: Batch;
  exception: DeliveryException;
  supplierCode: string;
  onSaved: (updated?: DeliveryException) => Promise<void>;
}) {
  const remaining = remainingTransferQuantity(exception);
  const offline = exception.offline_quantity ?? 0;
  const allowance = allowanceFor(batch, supplierCode, exception.sku, exception.full_site);
  const canAllow = Boolean(allowance) || inboundRowActions(exception.reason, true, { remaining }).includes("allowance");
  const [selected, setSelected] = useState<HandlingKind>(allowance ? "allowance" : "offline");
  const kind = canAllow ? selected : "offline";
  const isAllowance = kind === "allowance";
  const handling = useInboundHandling(batch.id, onSaved);
  const save = (quantity: number, reason: string) =>
    isAllowance
      ? handling.saveAllowance({
          supplier_code: supplierCode,
          sku: exception.sku,
          full_site: exception.full_site,
          quantity,
          reason
        })
      : handling.saveOffline(exception, quantity, reason);
  return (
    <Card size="small" title="人工处理">
      <Flex vertical gap="small">
        <Typography.Text>
          待处理 {exception.manual_quantity} = 已转交货 {exception.transferred_quantity ?? 0} + 线下处理 {offline} +
          剩余 {remaining}
        </Typography.Text>
        <Select<HandlingKind>
          aria-label="处理方式"
          value={kind}
          onChange={setSelected}
          options={[
            ...(canAllow ? [{ value: "allowance" as const, label: "追加超收" }] : []),
            { value: "offline", label: "线下处理" }
          ]}
        />
        <HandlingForm
          key={JSON.stringify([exception.id, kind, allowance, offline])}
          {...handlingFormState(batch, exception, supplierCode, kind)}
          busy={handling.busy}
          onSubmit={({ quantity, reason }) => void save(quantity, reason)}
          onRevoke={() => void save(0, "")}
        />
      </Flex>
    </Card>
  );
}
