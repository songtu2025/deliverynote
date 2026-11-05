import type { Batch } from "../../types";
import HandlingForm from "./HandlingForm";
import { allowanceDisabledReason, allowanceFor } from "./inboundHandling";
import { useInboundHandling } from "./useInboundHandling";

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
  const handling = useInboundHandling(batch.id, onSaved);
  const allowance = allowanceFor(batch, supplierCode, sku, fullSite);
  const save = (quantity: number, reason: string) =>
    handling.saveAllowance({
      supplier_code: supplierCode,
      sku,
      full_site: fullSite,
      quantity,
      reason
    });
  return (
    <HandlingForm
      key={JSON.stringify(allowance)}
      title="本批追加超收"
      reasonLabel="原因（选填）"
      quantity={allowance?.quantity ?? remaining}
      reason={allowance?.reason ?? ""}
      existing={Boolean(allowance)}
      busy={handling.busy}
      disabledReason={allowanceDisabledReason(batch)}
      button="保存并重算"
      onSubmit={({ quantity, reason }) => void save(quantity, reason)}
      onRevoke={() => void save(0, "")}
    />
  );
}
