import { Button, Popover, Typography } from "antd";
import type { PurchaseOption } from "../../inboundExceptionApi";
import { remainingTransferQuantity, type TransferItem, type TransferOptions } from "../../exceptionTransferApi";
import type { DeliveryException } from "../../types";

export function estimateTransfers(
  records: DeliveryException[],
  items: TransferItem[] | undefined,
  options: (TransferOptions | undefined)[]
) {
  const balances = new Map<string, number>();
  let total = 0;
  let deductible = 0;
  let pending = 0;
  const rows = records.map((record, index) => {
    const item = items?.[index];
    const quantity = item ? Math.max(0, Number(item.quantity) || 0) : remainingTransferQuantity(record);
    total += quantity;
    const data = options[index];
    if (!data || data.purchase_error) return null;
    const site = item?.full_site ?? record.full_site;
    const key = JSON.stringify([record.sku, site]);
    const remaining =
      balances.get(key) ??
      data.purchases
        .filter((purchase) => purchase.site === site)
        .reduce((sum, purchase) => sum + purchase.remaining_quantity, 0);
    const available = Math.min(quantity, remaining);
    balances.set(key, remaining - available);
    deductible += available;
    pending += quantity - available;
    return { deductible: available, pending: quantity - available };
  });
  return { rows, total, deductible, pending, available: rows.every((row) => row !== null) };
}

export function transferSiteOptions(data: TransferOptions) {
  return data.sites
    .map((site) => ({
      value: site,
      remaining: data.purchases
        .filter((item) => item.site === site)
        .reduce((total, item) => total + item.remaining_quantity, 0)
    }))
    .sort((left, right) => right.remaining - left.remaining)
    .map(({ value, remaining }) => ({
      value,
      label: `${value.replace(/^AMAZON:/, "")} · 未交 ${data.purchase_error ? "—" : remaining}`,
      style: remaining === 0 ? { color: "var(--dn-muted)" } : undefined
    }));
}

export default function TransferPurchaseDetails({ data, site }: { data: TransferOptions | undefined; site: string }) {
  if (!data) return <Typography.Text type="secondary">—</Typography.Text>;
  if (data.purchase_error) return <Typography.Text type="secondary">{data.purchase_error}</Typography.Text>;
  const purchases = data.purchases.filter((item) => item.site === site);
  if (!purchases.length) return <Typography.Text type="secondary">无未交采购</Typography.Text>;
  return (
    <div>
      <PurchaseRows purchases={purchases.slice(0, 2)} />
      {purchases.length > 2 && (
        <Popover
          key={site}
          trigger={["hover", "focus"]}
          content={
            <div style={{ width: "min(520px, calc(100vw - 80px))" }}>
              <PurchaseRows purchases={purchases} />
            </div>
          }
        >
          <Button type="link" size="small" style={{ paddingInline: 0 }}>
            +{purchases.length - 2}
          </Button>
        </Popover>
      )}
    </div>
  );
}

function PurchaseRows({ purchases }: { purchases: PurchaseOption[] }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "max-content minmax(0, 1fr) auto", columnGap: 8 }}>
      {purchases.map((purchase) => (
        <div key={purchase.id} style={{ display: "contents" }}>
          <Typography.Text ellipsis title={purchase.po_code}>
            {purchase.po_code}
          </Typography.Text>
          <Typography.Text ellipsis type="secondary" title={purchase.warehouse}>
            {purchase.warehouse}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
            {purchase.remaining_quantity}
          </Typography.Text>
        </div>
      ))}
    </div>
  );
}
