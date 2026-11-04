import { Table, Typography } from "antd";
import type { PurchaseOption } from "../../inboundExceptionApi";
import type { TransferOptions } from "../../exceptionTransferApi";

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

export default function TransferPurchaseDetails({
  data,
  site,
  quantity
}: {
  data: TransferOptions | undefined;
  site: string;
  quantity: number;
}) {
  if (!data) return null;
  const purchases = data.purchases.filter((item) => item.site === site);
  const remaining = purchases.reduce((total, item) => total + item.remaining_quantity, 0);
  return (
    <div>
      {data.purchase_error ? (
        <Typography.Text type="secondary">{data.purchase_error}</Typography.Text>
      ) : (
        <>
          {quantity > remaining && (
            <div>
              <Typography.Text type="warning">超出未交 {quantity - remaining} 件，将进入新批次待处理</Typography.Text>
            </div>
          )}
          <Table<PurchaseOption>
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={purchases}
            locale={{ emptyText: "当前站点无未交采购" }}
            columns={[
              { title: "PO 单号", dataIndex: "po_code" },
              { title: "目的仓", dataIndex: "warehouse" },
              { title: "未交数量", dataIndex: "remaining_quantity", align: "right", width: 120 }
            ]}
          />
        </>
      )}
    </div>
  );
}
