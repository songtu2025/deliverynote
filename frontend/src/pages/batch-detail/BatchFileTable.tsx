import { Alert, Button, Card, Empty, Popconfirm, Space, Table, Tooltip } from "antd";
import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, DownloadOutlined } from "@ant-design/icons";
import type { Batch, BatchFile } from "../../types";
import type { BatchFiles } from "./useBatchFiles";

export default function BatchFileTable({
  batch,
  files,
  loading,
  computed,
  canEditFiles,
  actions,
  downloadResult
}: {
  batch: Batch;
  files: BatchFile[];
  loading: boolean;
  computed: boolean;
  canEditFiles: boolean;
  actions: BatchFiles;
  downloadResult: (path: string, filename: string) => Promise<void>;
}) {
  const selfOperated = batch.workflow === "self_operated_inbound";
  return (
    <Card
      title={selfOperated ? "本批次业务文件" : "来源文件与处理顺序"}
      className="section-card file-order-card"
      extra={
        <span className="order-hint">
          {selfOperated ? "序号越小，越先扣减待入库余额和超收额度" : "序号越小，越先扣减采购余额"}
        </span>
      }
    >
      {selfOperated && <InboundFileStatus inboundFile={batch.inbound_file} />}
      {canEditFiles && files.length > 1 && (
        <Alert
          className="inline-alert"
          type="info"
          showIcon
          title={
            selfOperated
              ? "调整顺序会改变各质检单获得的待入库余额和超收额度；修改后必须重新预检。"
              : "调整顺序会改变各来源文件获得的采购余额；修改后必须重新预检。"
          }
        />
      )}
      <Table<BatchFile>
        rowKey="id"
        loading={loading}
        dataSource={files}
        pagination={false}
        scroll={{ x: 900 }}
        locale={{
          emptyText: (
            <Empty description={selfOperated ? "请先上传一份或多份质检交货单" : "请先上传一个或多个交货 Excel"} />
          )
        }}
        columns={batchFileColumns({ files, selfOperated, canEditFiles, computed, actions, downloadResult })}
      />
    </Card>
  );
}

function batchFileColumns({
  files,
  selfOperated,
  canEditFiles,
  computed,
  actions,
  downloadResult
}: {
  files: BatchFile[];
  selfOperated: boolean;
  canEditFiles: boolean;
  computed: boolean;
  actions: BatchFiles;
  downloadResult: (path: string, filename: string) => Promise<void>;
}) {
  const { move, removeFile } = actions;
  const showFileActions = canEditFiles || files.some((file) => file.download_ready);
  return [
    {
      title: "顺序",
      dataIndex: "file_order",
      width: 80,
      render: (value: number) => <span className="file-order">{String(value).padStart(2, "0")}</span>
    },
    { title: "来源文件", dataIndex: "original_name", ellipsis: true },
    {
      title: "供应商",
      dataIndex: "supplier_name",
      width: 150,
      render: (value: string) => value || <span className="muted">预检后识别</span>
    },
    {
      title: "交货",
      dataIndex: "delivery_total",
      width: 90,
      render: (value: number) => (computed ? value : "—")
    },
    {
      title: "可导入",
      dataIndex: "import_total",
      width: 90,
      render: (value: number) => (computed ? <span className="import-value">{value}</span> : "—")
    },
    {
      title: "待处理",
      dataIndex: "manual_total",
      width: 100,
      render: (value: number) => (computed ? <span className={value ? "pending-value" : ""}>{value}</span> : "—")
    },
    ...(showFileActions
      ? [
          {
            title: "操作",
            width: canEditFiles ? 250 : 170,
            fixed: "right" as const,
            render: (_: unknown, file: BatchFile, index: number) => (
              <Space>
                {canEditFiles && (
                  <>
                    <Tooltip title={selfOperated ? "上移，提前扣减待入库余额" : "上移，提前扣减采购余额"}>
                      <Button
                        aria-label={`上移 ${file.original_name}`}
                        size="small"
                        icon={<ArrowUpOutlined />}
                        disabled={index === 0}
                        onClick={() => void move(file.id, -1)}
                      />
                    </Tooltip>
                    <Tooltip title={selfOperated ? "下移，延后扣减待入库余额" : "下移，延后扣减采购余额"}>
                      <Button
                        aria-label={`下移 ${file.original_name}`}
                        size="small"
                        icon={<ArrowDownOutlined />}
                        disabled={index === files.length - 1}
                        onClick={() => void move(file.id, 1)}
                      />
                    </Tooltip>
                    <Popconfirm
                      title="删除此交货文件？"
                      description="其余文件会自动重新编号。"
                      onConfirm={() => void removeFile(file)}
                    >
                      <Tooltip title="删除错传文件">
                        <Button
                          aria-label={`删除 ${file.original_name}`}
                          danger
                          size="small"
                          icon={<DeleteOutlined />}
                        />
                      </Tooltip>
                    </Popconfirm>
                  </>
                )}
                {file.download_ready && (
                  <Button
                    aria-label="下载单文件结果"
                    size="small"
                    icon={<DownloadOutlined />}
                    onClick={() =>
                      void downloadResult(
                        `/api/batch-files/${file.id}/download`,
                        `${file.original_name.replace(/\.(xls|xlsx)$/i, "")}_${selfOperated ? "积加入库" : "交货处理"}.xlsx`
                      )
                    }
                  >
                    下载单文件结果
                  </Button>
                )}
              </Space>
            )
          }
        ]
      : [])
  ];
}

function InboundFileStatus({ inboundFile }: { inboundFile: Batch["inbound_file"] }) {
  return (
    <Alert
      className="inline-alert"
      type={inboundFile?.uploaded ? "success" : "warning"}
      showIcon
      title={inboundFile?.uploaded ? `自营仓入库单：${inboundFile.original_name}` : "尚未上传自营仓入库单"}
      description="提供交货单、PO、SKU、站点和应收货数据；每个批次一份。"
    />
  );
}
