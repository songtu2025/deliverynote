import { Button, Input, Popconfirm, Select, Typography } from "antd";
import { CheckCircleFilled, DeleteOutlined, SearchOutlined } from "@ant-design/icons";
import { STATUS_OPTIONS } from "../../BatchStatusTag";
import type { BatchWorkflow } from "./batchWorkspace";
import type { useBatchList } from "./useBatchList";
import type { useBatchDeletion } from "./useBatchDeletion";
export default function BatchListToolbar({
  workflow,
  active,
  canDeleteBatches,
  list,
  deletion
}: {
  workflow: BatchWorkflow;
  active: boolean;
  canDeleteBatches: boolean;
  list: ReturnType<typeof useBatchList>;
  deletion: ReturnType<typeof useBatchDeletion>;
}) {
  const { batchTotal, query, setQuery, setPage, statusFilter, setStatusFilter } = list;
  const {
    selectedBatchIds,
    bulkDeleteConfirmOpen,
    setBulkDeleteConfirmOpen,
    bulkDeleteButtonRef,
    bulkDeleteCancelRef,
    closeBulkDeleteOnEscape,
    bulkDeleteCancelProps,
    cancelBulkDelete,
    deleteSelectedBatches,
    deleting
  } = deletion;
  return (
    <div
      className={`table-toolbar batch-list-toolbar${selectedBatchIds.length ? " is-selecting" : ""}`}
      aria-label={workflow === "self_operated_inbound" ? "入库批次筛选" : "交货批次筛选"}
    >
      <div className="batch-list-toolbar-heading">
        <strong>{workflow === "self_operated_inbound" ? "入库批次" : "交货批次"}</strong>
        <Typography.Text className="batch-result-count" type="secondary">
          {batchTotal} 个批次
        </Typography.Text>
        {selectedBatchIds.length > 0 && (
          <Typography.Text className="batch-selection-count" aria-live="polite">
            <CheckCircleFilled aria-hidden />
            已选 {selectedBatchIds.length} 项
          </Typography.Text>
        )}
        {canDeleteBatches && selectedBatchIds.length > 0 && (
          <Popconfirm
            open={active && bulkDeleteConfirmOpen}
            onOpenChange={setBulkDeleteConfirmOpen}
            afterOpenChange={(open) => {
              // 等浮层显示后再聚焦，避免把焦点送进隐藏或已经离开的页面。
              if (open && bulkDeleteConfirmOpen && active && bulkDeleteButtonRef.current?.isConnected) {
                bulkDeleteCancelRef.current?.focus({ preventScroll: true });
              }
            }}
            title={`永久删除选中的 ${selectedBatchIds.length} 个批次？`}
            description="将删除批次记录、上传文件和结果文件，无法恢复。"
            okText="永久删除"
            cancelText="取消"
            okButtonProps={{ danger: true, onKeyDown: closeBulkDeleteOnEscape }}
            cancelButtonProps={bulkDeleteCancelProps}
            disabled={!selectedBatchIds.length}
            onCancel={cancelBulkDelete}
            onConfirm={() => {
              setBulkDeleteConfirmOpen(false);
              void deleteSelectedBatches(selectedBatchIds);
            }}
          >
            <Button
              ref={bulkDeleteButtonRef}
              onKeyDown={closeBulkDeleteOnEscape}
              danger
              size="small"
              icon={<DeleteOutlined />}
              aria-label={`删除已选（${selectedBatchIds.length}）`}
              disabled={!selectedBatchIds.length}
              loading={deleting}
            >
              批量删除
            </Button>
          </Popconfirm>
        )}
      </div>
      <div className="table-filter-field">
        <label htmlFor={`${workflow}-batch-search`}>搜索</label>
        <Input
          id={`${workflow}-batch-search`}
          aria-label="搜索"
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索批次名称"
          value={query}
          onChange={(event) => {
            setPage(1);
            setQuery(event.target.value);
          }}
        />
      </div>
      <div className="table-filter-field">
        <label htmlFor={`${workflow}-batch-status-filter`}>状态</label>
        <Select
          id={`${workflow}-batch-status-filter`}
          aria-label="状态"
          allowClear
          placeholder="全部状态"
          options={STATUS_OPTIONS}
          value={statusFilter}
          onChange={(value) => {
            setPage(1);
            setStatusFilter(value);
          }}
        />
      </div>
    </div>
  );
}
