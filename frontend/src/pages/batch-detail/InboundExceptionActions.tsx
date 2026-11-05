import type { DeliveryException } from "../../types";
import { candidateSites } from "./reviewDraft";
import ReceiptRowActions from "./ReceiptRowActions";
import InboundAllowanceInput from "./InboundAllowanceInput";
import type { InboundAdjustments } from "./useInboundAdjustments";

export default function InboundExceptionActions({
  record,
  supplierCode,
  adjustments,
  onVersions
}: {
  record: DeliveryException;
  supplierCode: string;
  adjustments: InboundAdjustments;
  onVersions?: () => void;
}) {
  const disabledReason = adjustments.busy ? "正在保存调整" : adjustments.disabledReason;
  if (["超出允许超收量", "超出应收货"].includes(record.reason))
    return <InboundAllowanceInput record={record} supplierCode={supplierCode} adjustments={adjustments} />;
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
