import { Alert, Drawer, Select, Table, Typography } from "antd";

export interface ReceiptRow {
  file_id: number;
  filename: string;
  supplier: string;
  sku: string;
  original_site: string;
  full_site: string;
  cumulative: number;
  history: number | null;
  requested: number | null;
  issue: string;
  reason?: string;
  notice?: string;
  candidates: string[];
  delivery_numbers: string[];
  order_numbers: string[];
  purchase_numbers: string[];
  item_ids: string[];
  entries?: {
    item_id: string;
    order_no: string;
    purchase_no: string;
    status: string;
    history: number | null;
    shelf_numbers: string;
  }[];
}

export default function ReceiptReviewDetails({
  target,
  busy,
  onClose,
  onChooseSite
}: {
  target: ReceiptRow | null;
  busy: boolean;
  onClose: () => void;
  onChooseSite: (row: ReceiptRow, site: string) => Promise<void>;
}) {
  return (
    <Drawer title="累计数量与历史依据" open={Boolean(target)} onClose={() => onClose()} size={520}>
      {target && (
        <div className="receipt-review-details">
          <header className="receipt-review-heading">
            <h3>
              {target.sku} · {target.original_site}
            </h3>
            <div className="receipt-review-secondary">
              {target.filename} · {target.supplier}
            </div>
            <div className="receipt-review-secondary">{target.full_site}</div>
          </header>
          <ReceiptQuantities target={target} />
          {target.issue && <Alert type="warning" title={target.issue} />}
          {(target.reason || target.issue) && target.candidates.length > 1 && (
            <Select<string>
              aria-label="选择该文件的完整站点"
              value={null}
              style={{ width: "100%" }}
              placeholder="选择完整站点后重新核对"
              disabled={busy}
              options={target.candidates.map((value) => ({ value, label: value }))}
              onChange={(value) => void onChooseSite(target, value)}
            />
          )}
          {target.notice && <Alert type="warning" title={target.notice} />}
          <section aria-label="历史入库明细">
            <h4 className="receipt-review-section-title">历史入库明细</h4>
            {target.entries?.length ? (
              <ReceiptHistory entries={target.entries} />
            ) : (
              <div className="receipt-review-references">
                <div>入库单：{referenceText(target.order_numbers, target.notice)}</div>
                <div>采购单：{referenceText(target.purchase_numbers, target.notice)}</div>
                <div>积加商品明细 ID：{referenceText(target.item_ids, target.notice)}</div>
              </div>
            )}
          </section>
          {target.delivery_numbers.length > 0 && (
            <section aria-label="交货单号">
              <h4 className="receipt-review-section-title">交货单号（{target.delivery_numbers.length}）</h4>
              <Typography.Paragraph
                className="receipt-review-delivery-numbers"
                ellipsis={{ rows: 2, expandable: true, symbol: "展开全部" }}
                copyable={{ text: target.delivery_numbers.join("、") }}
              >
                {target.delivery_numbers.join("、")}
              </Typography.Paragraph>
            </section>
          )}
        </div>
      )}
    </Drawer>
  );
}

function ReceiptQuantities({ target }: { target: ReceiptRow }) {
  return (
    <dl className="receipt-review-quantities" aria-label="入库数量算式">
      {[
        { label: "累计实收", value: target.cumulative },
        { label: "历史已入库", value: target.history },
        { label: "本次申请", value: target.requested }
      ].map(({ label, value }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{quantityText(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

const historyStatusLabels: Record<string, string> = {
  COMPLETED: "已完结",
  PART_INBOUND: "部分入库",
  WAIT_INBOUND: "待入库"
};

function ReceiptHistory({ entries }: { entries: NonNullable<ReceiptRow["entries"]> }) {
  const total = entries.reduce<number | null>(
    (sum, entry) => (sum === null || entry.history === null ? null : sum + entry.history),
    0
  );
  return (
    <Table
      className="receipt-review-history"
      rowKey="item_id"
      size="small"
      tableLayout="fixed"
      dataSource={entries}
      pagination={false}
      columns={[
        {
          title: "入库单",
          dataIndex: "order_no",
          width: "36%",
          render: (value: string, entry) => (
            <div>
              <div>{value}</div>
              <div className="receipt-review-secondary">
                ID {entry.item_id}
                {entry.shelf_numbers && ` · 分批 ${entry.shelf_numbers}`}
              </div>
            </div>
          )
        },
        { title: "采购单", dataIndex: "purchase_no", width: "26%" },
        {
          title: "状态",
          dataIndex: "status",
          width: "20%",
          render: (value: string) => historyStatusLabels[value] ?? value
        },
        {
          title: "已入库",
          dataIndex: "history",
          align: "right",
          render: (value: number | null) => quantityText(value)
        }
      ]}
      summary={() => (
        <Table.Summary.Row>
          <Table.Summary.Cell index={0} colSpan={3}>
            合计
          </Table.Summary.Cell>
          <Table.Summary.Cell index={3} align="right">
            {quantityText(total)}
          </Table.Summary.Cell>
        </Table.Summary.Row>
      )}
    />
  );
}

function quantityText(value: number | null) {
  return value === null ? <span className="receipt-review-unconfirmed">待核对</span> : value;
}

function referenceText(values: string[], notice?: string) {
  return values.join("、") || (notice ? "未匹配" : "尚未确认");
}
