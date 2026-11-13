import { Alert, Button, Card, Descriptions, Empty, Space, Table, Typography, Upload } from "antd";
import { DownloadOutlined, UploadOutlined } from "@ant-design/icons";

import { usePurchaseEntry } from "./purchase-entry/usePurchaseEntry";

const formatQuantity = (value: number | string) => Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 20 });
const batchColumns = [
  { title: "自定义采购单号", dataIndex: "order_number", width: 220 },
  { title: "来源站点", dataIndex: "source_site", width: 120 },
  { title: "合同交期", dataIndex: "delivery_date", width: 140 },
  { title: "明细数", dataIndex: "row_count", align: "right" as const, width: 100, render: formatQuantity },
  { title: "采购量", dataIndex: "total_quantity", align: "right" as const, width: 120, render: formatQuantity }
];

export default function PurchaseEntryPage() {
  const entry = usePurchaseEntry();
  return (
    <div className="page-shell purchase-entry-page">
      <div className="page-header">
        <Typography.Title level={2}>采购单录入</Typography.Title>
      </div>
      <Card>
        <Space className="purchase-entry-toolbar" wrap size="middle">
          <Upload
            accept=".xlsx"
            maxCount={1}
            multiple={false}
            beforeUpload={() => false}
            fileList={entry.files}
            disabled={entry.busy}
            onChange={entry.selectFile}
          >
            <Button icon={<UploadOutlined />} disabled={entry.busy}>
              选择采购单
            </Button>
          </Upload>
          <Button
            type={entry.preview ? "default" : "primary"}
            disabled={entry.busy || entry.files.length === 0}
            loading={entry.action === "preview"}
            aria-label="校验预览"
            aria-busy={entry.action === "preview"}
            onClick={() => void entry.runPreview()}
          >
            校验预览
          </Button>
          <Button
            type={entry.preview ? "primary" : "default"}
            icon={<DownloadOutlined />}
            disabled={entry.busy || !entry.preview}
            loading={entry.action === "merged"}
            aria-label="下载合并 Excel"
            aria-busy={entry.action === "merged"}
            onClick={() => void entry.exportFile("merged")}
          >
            下载合并 Excel
          </Button>
          <Button
            icon={<DownloadOutlined />}
            disabled={entry.busy || !entry.preview}
            loading={entry.action === "split"}
            aria-label="下载分批 ZIP"
            aria-busy={entry.action === "split"}
            onClick={() => void entry.exportFile("split")}
          >
            下载分批 ZIP
          </Button>
        </Space>
        {entry.error && (
          <Alert className="inline-alert" type="error" showIcon title="采购单处理失败" description={entry.error} />
        )}
        {entry.preview ? (
          <>
            <Descriptions
              className="purchase-entry-summary"
              size="small"
              column={{ xs: 1, sm: 2, lg: 4 }}
              items={[
                { key: "supplier", label: "供应商编码", children: entry.preview.supplier_code },
                { key: "batches", label: "批次数", children: formatQuantity(entry.preview.batch_count) },
                { key: "rows", label: "明细数", children: formatQuantity(entry.preview.row_count) },
                { key: "quantity", label: "采购总量", children: formatQuantity(entry.preview.total_quantity) }
              ]}
            />
            <Table
              aria-label="采购批次汇总"
              rowKey="order_number"
              columns={batchColumns}
              dataSource={entry.preview.batches}
              size="middle"
              scroll={{ x: 700 }}
              pagination={entry.preview.batches.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
            />
          </>
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={entry.action === "preview" ? "正在校验采购单" : "暂无采购单预览"}
          />
        )}
      </Card>
    </div>
  );
}
