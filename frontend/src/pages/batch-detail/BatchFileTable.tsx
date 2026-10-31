import { batchFileResultName } from "./batchPresentation";
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
      title={selfOperated ? "本批次业务文件" : undefined}
      variant={selfOperated ? undefined : "borderless"}
      className="section-card file-order-card"
      classNames={{ body: "batch-detail-panel-body" }}
      extra={
        <span className="order-hint">
          {selfOperated ? "序号越小，越先扣减待入库余额和超收额度" : "序号越小，越先扣减采购余额"}
        </span>
      }
    >
      {selfOperated && <InboundFileStatus batch={batch} />}
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
      ellipsis: true,
      render: (value: string) => value || <span className="muted">预检后识别</span>
    },
    {
      title: selfOperated ? "本次申请" : "交货",
      dataIndex: "delivery_total",
      align: "right" as const,
      width: 90,
      render: (value: number, file: BatchFile) =>
        selfOperated ? (file.receipt ? (file.receipt.requested_total ?? "待核对") : "—") : computed ? value : "—"
    },
    {
      title: selfOperated ? "可入库" : "可导入",
      dataIndex: "import_total",
      align: "right" as const,
      width: 90,
      render: (value: number) => (computed ? <span className="import-value">{value}</span> : "—")
    },
    {
      title: "待处理",
      dataIndex: "manual_total",
      align: "right" as const,
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
                        batchFileResultName(file.original_name, selfOperated)
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

function InboundFileStatus({ batch }: { batch: Batch }) {
  const inboundFile = batch.inbound_file;
  const apiSource = Boolean(batch.version_ids.self_operated_inbound);
  return (
    <Alert
      className="inline-alert"
      type={inboundFile?.uploaded ? "success" : "warning"}
      showIcon
      title={
        inboundFile?.uploaded
          ? `待入库数据（${apiSource ? "API锁定" : "手动上传"}）：${inboundFile.original_name}`
          : "待入库数据尚未就绪"
      }
      description={
        apiSource
          ? "此版本记录创建来源；预检按本批交货单号获取并冻结完整历史与余额，计算使用同一份快照。"
          : "上传文件须包含原始应收货、已入库、入库状态和唯一积加明细ID；缺少历史时不能计算。"
      }
    />
  );
}
