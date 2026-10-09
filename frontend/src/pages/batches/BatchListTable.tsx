import { Button, Empty, Popconfirm, Space, Table } from "antd";
import { RightOutlined } from "@ant-design/icons";
import type { Batch } from "../../types";
import { formatBeijingDateTime } from "../../dateTime";
import StatusTag from "../../BatchStatusTag";
import { canDeleteBatch, nextAction } from "./batchWorkspace";
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
      tableLayout={delivery ? "fixed" : undefined}
      rowSelection={
        canDeleteBatches
          ? {
              selectedRowKeys: selectedBatchIds,
              preserveSelectedRowKeys: true,
              columnWidth: delivery ? 44 : 52,
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
      locale={{ emptyText: <Empty description={query || statusFilter ? "没有匹配的批次" : "暂无批次"} /> }}
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
              {delivery && <span className="batch-id">批次 #{batch.id}</span>}
            </div>
          )
        },
        {
          title: "状态",
          dataIndex: "status",
          width: delivery ? 104 : 130,
          render: (value: string) => (
            <div className="batch-table-value">
              <span className="batch-cell-label">状态</span>
              <StatusTag status={value} />
            </div>
          )
        },
        {
          title: "文件 / 数量",
          width: delivery ? 186 : 190,
          render: (_, batch) => (
            <div className="batch-table-value">
              <span className="batch-cell-label">文件 / 数量</span>
              <span className="batch-volume">
                {batch.workflow === "self_operated_inbound"
                  ? `${batch.file_count} 份质检单 + ${batch.inbound_file?.uploaded ? 1 : 0} 份待入库数据`
                  : `${batch.file_count} 个文件`}
                {batch.summary && batch.summary.delivery_total > 0 ? " · 交货 " + batch.summary.delivery_total : ""}
              </span>
              {delivery && batch.summary && (
                <span className="batch-allocation">
                  可导入 {batch.summary.import_total} · <span>待处理 {batch.summary.manual_total}</span>
                </span>
              )}
            </div>
          )
        },
        {
          title: "下一步",
          width: delivery ? 120 : 170,
          render: (_, batch) => {
            const action = nextAction(batch, workflow);
            return (
              <div className="batch-table-value">
                <span className="batch-cell-label">下一步</span>
                <span className="next-action">{action}</span>
                {delivery && batch.download_ready && action === "查看待处理" && (
                  <span className="batch-result-availability">结果可下载</span>
                )}
              </div>
            );
          }
        },
        {
          title: "更新时间",
          dataIndex: "updated_at",
          width: delivery ? 168 : 190,
          render: (value: string) => (
            <div className="batch-table-value">
              <span className="batch-cell-label">更新时间</span>
              <span>{formatBeijingDateTime(value)}</span>
            </div>
          )
        },
        {
          title: "操作",
          width: canDeleteBatches ? (delivery ? 124 : 170) : 100,
          render: (_, batch) => (
            <Space className="batch-row-actions" size={0}>
              <Button
                className="batch-open-action"
                type="link"
                aria-label={"打开 " + batch.name}
                onClick={() => onOpen(batch.id)}
              >
                <Space size={4}>
                  打开
                  <RightOutlined />
                </Space>
              </Button>
              {canDeleteBatches && (
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
                    danger
                    type="link"
                    aria-label={`删除批次 ${batch.name}`}
                    disabled={!canDeleteBatch(batch)}
                    loading={deletingBatchIds.includes(batch.id)}
                    title={canDeleteBatch(batch) ? "删除批次" : "运行中的批次不能删除"}
                  >
                    删除
                  </Button>
                </Popconfirm>
              )}
            </Space>
          )
        }
      ]}
    />
  );
}
