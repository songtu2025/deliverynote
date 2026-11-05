import type { DeliveryException } from "../../types";
import { candidateSites } from "./reviewDraft";
import ReceiptRowActions from "./ReceiptRowActions";
import { Button } from "antd";
import type { InboundAdjustments } from "./useInboundAdjustments";

export default function InboundExceptionActions({
  record,
  onOpen,
  adjustments,
  onVersions
}: {
  record: DeliveryException;
  onOpen: (record: DeliveryException) => void;
  adjustments: InboundAdjustments;
  onVersions?: () => void;
}) {
  const disabledReason = adjustments.busy ? "正在保存调整" : adjustments.disabledReason;
  if (["超出允许超收量", "超出应收货"].includes(record.reason))
    return <Button onClick={() => onOpen(record)}>指定超收</Button>;
  return (
    <ReceiptRowActions
      row={{
        ...record,
        file_id: record.batch_file_id,
        issue: record.reason,
        candidates: candidateSites(record.full_site)
      }}
      computed
      siteValue={adjustments.siteValue(record)}
      disabledReason={disabledReason ?? null}
      refreshing={false}
      onChooseSite={(_row, site) => adjustments.setSite(record, site)}
      onVersions={onVersions}
    />
  );
}
