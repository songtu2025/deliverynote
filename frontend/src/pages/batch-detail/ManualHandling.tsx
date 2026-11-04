import { Card, Flex, Typography } from "antd";
import type { Batch, DeliveryException } from "../../types";
import { remainingTransferQuantity } from "../../exceptionTransferApi";

import OfflineHandlingForm from "./OfflineHandlingForm";
import ManualAllowanceForm from "./ManualAllowanceForm";

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
  return (
    <section aria-label="人工处理">
      <Card size="small" title="人工处理">
        <Flex vertical gap="small">
          <Typography.Text>
            待处理 {exception.manual_quantity} = 已转交货 {exception.transferred_quantity ?? 0} + 线下处理 {offline} +
            剩余 {remaining}
          </Typography.Text>
          <ManualAllowanceForm
            batch={batch}
            supplierCode={supplierCode}
            sku={exception.sku}
            fullSite={exception.full_site}
            remaining={remaining}
            onSaved={() => onSaved()}
          />
          <OfflineHandlingForm batch={batch} exception={exception} onSaved={onSaved} />
        </Flex>
      </Card>
    </section>
  );
}
