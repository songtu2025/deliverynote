import { useState } from "react";
import type { Batch, DeliveryException } from "../../types";
import type { SiteAdjustmentInput } from "../../inboundExceptionApi";
import { allowanceDisabledReason } from "./inboundHandling";
import { useSaveInboundAdjustments } from "./useSaveInboundAdjustments";

function siteKey(record: DeliveryException) {
  return JSON.stringify([record.batch_file_id, record.sku, record.original_site]);
}

export function useInboundAdjustments(batch: Batch | undefined, onSaved?: () => Promise<unknown>) {
  const [sites, setSites] = useState<Record<string, SiteAdjustmentInput>>({});
  const { busy, save } = useSaveInboundAdjustments(batch?.id, onSaved);
  const discard = () => setSites({});
  const disabledReason = batch ? allowanceDisabledReason(batch) : "批次尚未计算成功";
  const setSite = (record: DeliveryException, fullSite: string) => {
    setSites((current) => ({
      ...current,
      [siteKey(record)]: {
        file_id: record.batch_file_id,
        sku: record.sku,
        original_site: record.original_site,
        full_site: fullSite
      }
    }));
  };
  const submit = async () => {
    if (disabledReason || !Object.keys(sites).length) return;
    if (await save({ allowances: [], sites: Object.values(sites) })) discard();
  };
  return {
    count: Object.keys(sites).length,
    busy,
    disabledReason,
    discard,
    submit,
    setSite,
    siteValue: (record: DeliveryException) => sites[siteKey(record)]?.full_site
  };
}

export type InboundAdjustments = ReturnType<typeof useInboundAdjustments>;
