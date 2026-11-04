import { Collapse } from "antd";
import type { Batch } from "../../types";
import ManualAllowanceForm from "./ManualAllowanceForm";

export default function BatchManualAllowances({ batch, onSaved }: { batch: Batch; onSaved: () => Promise<void> }) {
  if (!batch.manual_allowances?.length) return null;
  return (
    <Collapse
      size="small"
      items={batch.manual_allowances.map((entry) => ({
        key: JSON.stringify([entry.supplier_code, entry.sku, entry.full_site]),
        label: `${entry.supplier_name} / ${entry.sku} / ${entry.full_site}：本批追加 ${entry.quantity} 件`,
        children: (
          <ManualAllowanceForm
            batch={batch}
            supplierCode={entry.supplier_code}
            sku={entry.sku}
            fullSite={entry.full_site}
            remaining={0}
            onSaved={onSaved}
          />
        )
      }))}
    />
  );
}
