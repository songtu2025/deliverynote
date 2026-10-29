import { Alert, Drawer, Select, Space, Table } from "antd";

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
        <Space orientation="vertical" style={{ width: "100%" }}>
          <div>
            {target.filename} · {target.supplier}
          </div>
          <strong>
            {target.sku} / {target.original_site}
          </strong>
          <div>{target.full_site}</div>
          <div>
            累计实收 {target.cumulative} − 历史已入库 {target.history ?? "待核对"} = 本次申请{" "}
            {target.requested ?? "待核对"}
          </div>
          <div>交货单号：{target.delivery_numbers.join("、")}</div>
          <div>入库单：{referenceText(target.order_numbers, target.notice)}</div>
          <div>采购单：{referenceText(target.purchase_numbers, target.notice)}</div>
          <div>积加商品明细 ID：{referenceText(target.item_ids, target.notice)}</div>
          <Table
            rowKey="item_id"
            size="small"
            dataSource={target.entries}
            pagination={false}
            scroll={{ x: 650 }}
            columns={[
              { title: "入库单", dataIndex: "order_no" },
              { title: "采购单", dataIndex: "purchase_no" },
              { title: "状态", dataIndex: "status" },
              { title: "已入库", dataIndex: "history", render: (value) => value ?? "待核对" },
              { title: "分批入库单", dataIndex: "shelf_numbers" }
            ]}
          />
          {target.issue && <Alert type="warning" title={target.issue} />}
          {target.notice && <Alert type="info" title={target.notice} />}
          {target.issue && target.candidates.length > 1 && (
            <Select
              aria-label="选择该文件的完整站点"
              style={{ width: "100%" }}
              placeholder="选择完整站点后重新核对"
              disabled={busy}
              options={target.candidates.map((value) => ({ value, label: value }))}
              onChange={(value) => void onChooseSite(target, value)}
            />
          )}
        </Space>
      )}
    </Drawer>
  );
}

function referenceText(values: string[], notice?: string) {
  return values.join("、") || (notice ? "未匹配" : "尚未确认");
}
