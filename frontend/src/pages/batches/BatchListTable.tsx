import { Button, Empty, Popconfirm, Table } from "antd";
import { DeleteOutlined, LoadingOutlined } from "@ant-design/icons";
import type { Batch } from "../../types";
import { formatBeijingDateTime } from "../../dateTime";
import StatusTag from "../../BatchStatusTag";
import { receiptReady } from "../../receipt";
import { canDeleteBatch } from "./batchWorkspace";
import { batchStage } from "../../batchStage";
import type { BatchWorkflow } from "./batchWorkspace";
import type { useBatchList } from "./useBatchList";
import type { useBatchDeletion } from "./useBatchDeletion";
export default function BatchListTable({
  workflow,
  onOpen,
  canDeleteBatches,
  list,
  deletion
}: {
  workflow: BatchWorkflow;
  onOpen: (id: number) => void;
  canDeleteBatches: boolean;
  list: ReturnType<typeof useBatchList>;
  deletion: ReturnType<typeof useBatchDeletion>;
}) {
  const { batches, loading, query, statusFilter, page, setPage, batchTotal } = list;
  const { selectedBatchIds, setSelectedBatchIds, deletingBatchIds, deleteSelectedBatches } = deletion;
  const delivery = workflow === "delivery";
  return (
    <Table<Batch>
      className="batch-list-table"
      rowKey="id"
      tableLayout="fixed"
      rowSelection={
        canDeleteBatches
          ? {
              selectedRowKeys: selectedBatchIds,
              preserveSelectedRowKeys: true,
              columnWidth: 44,
              onChange: (keys) => {
                setSelectedBatchIds(keys.map(Number));
              },
              getCheckboxProps: (batch) => ({
                disabled: !canDeleteBatch(batch),
                "aria-label": `选择批次 ${batch.name}`
              })
            }
          : undefined
      }
      loading={loading}
      dataSource={batches}
      components={{
        table: (props) => (
          <table {...props} aria-label={workflow === "self_operated_inbound" ? "自营仓入库批次列表" : "交货批次列表"} />
        )
      }}
      locale={{ emptyText: <Empty description={query || statusFilter ? "没有匹配的批次" : "还没有批次"} /> }}
      pagination={
        batchTotal > 12
          ? {
              current: page,
              pageSize: 12,
              total: batchTotal,
              showSizeChanger: false,
              onChange: setPage
            }
          : false
      }
      columns={[
        {
          title: "批次",
          className: "batch-identity-cell",
          dataIndex: "name",
          render: (value: string, batch) => (
            <div className="batch-identity">
              <Button className="batch-name-link" type="link" title={value} onClick={() => onOpen(batch.id)}>
                {value}
              </Button>
              <span className="batch-id" title={delivery ? undefined : batch.inbound_file?.original_name}>
                批次 #{batch.id}
                {!delivery && ` / 待入库数据${batch.inbound_file?.uploaded ? "已就绪" : "未就绪"}`}
              </span>
            </div>
          )
        },
        {
          title: "状态",
          dataIndex: "status",
          width: 104,
          render: (_: string, batch) => (
            <div className="batch-table-value">
              <span className="batch-cell-label">状态</span>
              <StatusTag batch={batch} />
            </div>
          )
        },
        {
          title: "数量",
          width: 186,
          render: (_, batch) => {
            const summary = delivery || receiptReady(batch) ? batch.summary : undefined;
            return (
              <div className="batch-table-value">
                <span className="batch-cell-label">数量</span>
                <span className="batch-volume">
                  {!delivery ? `${batch.file_count} 份质检单` : `${batch.file_count} 个文件`}
                </span>
                {summary && summary.delivery_total > 0 && (
                  <div
                    className="batch-quantity-bar batch-list-quantity-bar"
                    role="img"
                    aria-label={`${delivery ? "可导入" : "可入库"} ${summary.import_total}，待处理 ${summary.manual_total}`}
                  >
                    <span
                      className="batch-quantity-segment quantity-import"
                      style={{ flexGrow: summary.import_total }}
                    />
                    <span
                      className="batch-quantity-segment quantity-pending"
                      style={{ flexGrow: summary.manual_total }}
                    />
                  </div>
                )}
                {summary ? (
                  <span className="batch-allocation">
                    {delivery ? "可导入" : "可入库"} {summary.import_total} / 待处理 <span>{summary.manual_total}</span>
                  </span>
                ) : !delivery ? (
                  <span className="batch-allocation">尚未计算</span>
                ) : null}
              </div>
            );
          }
        },
        {
          title: "下一步",
          width: 140,
          render: (_, batch) => {
            const { next, stage, pending } = batchStage(batch);
            return (
              <div className="batch-table-value">
                <span className="batch-cell-label">下一步</span>
                {next.key === "busy" ? (
                  <span className="batch-computing">
                    <LoadingOutlined /> {next.listLabel}
                  </span>
                ) : (
                  <Button
                    size="small"
                    type={next.primary ? "primary" : "default"}
                    danger={stage.tone === "error" || next.key === "expired"}
                    aria-label={"打开 " + batch.name}
                    title={next.listLabel}
                    onClick={() => onOpen(batch.id)}
                  >
                    {next.listLabel}
                  </Button>
                )}
                {!delivery && pending > 0 && next.key === "download" && (
                  <span className="batch-result-availability">待处理 {pending}</span>
                )}
                {delivery && batch.download_ready && next.key === "review" && (
                  <span className="batch-result-availability">结果可下载</span>
                )}
              </div>
            );
          }
        },
        {
          title: "更新时间",
          dataIndex: "updated_at",
          width: 168,
          render: (value: string) => (
            <div className="batch-table-value">
              <span className="batch-cell-label">更新时间</span>
              <span>{formatBeijingDateTime(value)}</span>
            </div>
          )
        },
        ...(canDeleteBatches
          ? [
              {
                title: "操作",
                width: 64,
                render: (_: unknown, batch: Batch) => (
                  <div className="batch-row-actions">
                    <Popconfirm
                      title={`永久删除“${batch.name}”？`}
                      description="将删除批次记录、上传文件和结果文件，无法恢复。"
                      okText="永久删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      disabled={!canDeleteBatch(batch)}
                      onConfirm={() => void deleteSelectedBatches([batch.id])}
                    >
                      <Button
                        className="batch-delete-action"
                        type="text"
                        icon={<DeleteOutlined />}
                        aria-label={`删除批次 ${batch.name}`}
                        disabled={!canDeleteBatch(batch)}
                        loading={deletingBatchIds.includes(batch.id)}
                        title={canDeleteBatch(batch) ? "删除批次" : "运行中的批次不能删除"}
                      />
                    </Popconfirm>
                  </div>
                )
              }
            ]
          : [])
      ]}
    />
  );
}
