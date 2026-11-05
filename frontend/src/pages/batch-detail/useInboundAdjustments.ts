import { useRef, useState } from "react";
import { App } from "antd";
import type { Batch, DeliveryException } from "../../types";
import { saveInboundAdjustments, type ManualAllowanceInput, type SiteAdjustmentInput } from "../../inboundExceptionApi";
import { allowanceDisabledReason, allowanceFor, allowanceKey, type AllowanceRecord } from "./inboundHandling";

function siteKey(record: DeliveryException) {
  return JSON.stringify([record.batch_file_id, record.sku, record.original_site]);
}

export function useInboundAdjustments(batch: Batch | undefined, onSaved?: () => Promise<unknown>) {
  const { message } = App.useApp();
  const [allowances, setAllowances] = useState<Record<string, ManualAllowanceInput>>({});
  const [sites, setSites] = useState<Record<string, SiteAdjustmentInput>>({});
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);
  const discard = () => {
    setAllowances({});
    setSites({});
  };
  const disabledReason = batch ? allowanceDisabledReason(batch) : "批次尚未计算成功";

  const setAllowance = (record: AllowanceRecord, supplier: string, quantity: number | null) => {
    if (!batch) return;
    const existing = allowanceFor(batch, supplier, record.sku, record.full_site);
    setAllowances((current) => {
      const next = { ...current };
      const key = allowanceKey(supplier, record);
      if (quantity === null || quantity === (existing?.quantity ?? 0)) delete next[key];
      else
        next[key] = {
          supplier_code: supplier,
          sku: record.sku,
          full_site: record.full_site,
          quantity,
          reason: existing?.reason ?? ""
        };
      return next;
    });
  };

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
    if (!batch || saving.current || disabledReason) return;
    saving.current = true;
    setBusy(true);
    try {
      await saveInboundAdjustments(batch.id, { allowances: Object.values(allowances), sites: Object.values(sites) });
      discard();
      await onSaved?.();
      message.success("已保存调整，正在重算整批");
    } catch (failure) {
      message.error(failure instanceof Error ? failure.message : "保存调整失败");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };

  return {
    count: Object.keys(allowances).length + Object.keys(sites).length,
    busy,
    disabledReason,
    discard,
    submit,
    setAllowance,
    setSite,
    allowanceValue: (record: AllowanceRecord, supplier: string) =>
      allowances[allowanceKey(supplier, record)]?.quantity ??
      (batch && allowanceFor(batch, supplier, record.sku, record.full_site)?.quantity) ??
      null,
    siteValue: (record: DeliveryException) => sites[siteKey(record)]?.full_site
  };
}

export type InboundAdjustments = ReturnType<typeof useInboundAdjustments>;
