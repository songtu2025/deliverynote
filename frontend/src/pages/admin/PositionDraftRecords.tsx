import { Alert, Button, Card, Checkbox, Input, Popconfirm, Select, Table, Typography } from "antd";
import type { TableProps } from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";

import type { PositionDraftRow } from "../../types";
import type { usePositionDraftRows } from "./usePositionDraftRows";

interface PositionDraftRecordsProps {
  rowsState: ReturnType<typeof usePositionDraftRows>;
  columns: TableProps<PositionDraftRow>["columns"];
  disabled: boolean;
  bulkDeleting: boolean;
  bulkDeleteConfirmOpen: boolean;
  onNewRow: () => void;
  onBulkDeleteOpenChange: (open: boolean) => void;
  onBulkDeleteConfirm: () => Promise<void>;
}

const POSITION_TABLE_COMPONENTS: NonNullable<TableProps<PositionDraftRow>["components"]> = {
  table: (props) => <table {...props} aria-label="库位草稿记录" />
};

export function PositionDraftRecords({
  rowsState,
  columns,
  disabled,
  bulkDeleting,
  bulkDeleteConfirmOpen,
  onNewRow,
  onBulkDeleteOpenChange,
  onBulkDeleteConfirm
}: PositionDraftRecordsProps) {
  const {
    rows,
    rowsTotal,
    rowsLoading,
    rowsError,
    search,
    setSearch,
    site,
    setSite,
    scale,
    setScale,
    issueFilter,
    setIssueFilter,
    onlyModified,
    setOnlyModified,
    page,
    setPage,
    pageSize,
    setPageSize,
    selectedRowIds,
    setSelectedRowIds,
    refreshRows,
    resetFilters,
    hasActiveFilters
  } = rowsState;

  return (
    <Card
      className="position-records-card"
      classNames={{ header: "position-records-header" }}
      title={
        <span>
          草稿记录 <small className="position-records-count">共 {rowsTotal} 条</small>
        </span>
      }
      extra={
        <Button aria-label="新增记录" type="primary" icon={<PlusOutlined />} disabled={disabled} onClick={onNewRow}>
          新增记录
        </Button>
      }
    >
      <div className="table-toolbar position-filter-toolbar">
        <div className="position-filter-field position-filter-search">
          <label htmlFor="position-search">搜索</label>
          <Input.Search
            id="position-search"
            aria-label="搜索草稿"
            allowClear
            value={search}
            placeholder="站点、SKU、MSKU 或定位"
            onChange={(event) => {
              setPage(1);
              setSearch(event.target.value);
            }}
          />
        </div>
        <div className="position-filter-field">
          <label htmlFor="position-site-filter">站点</label>
          <Input
            id="position-site-filter"
            aria-label="站点筛选"
            allowClear
            value={site}
            placeholder="精确筛选"
            onChange={(event) => {
              setPage(1);
              setSite(event.target.value);
            }}
          />
        </div>
        <div className="position-filter-field">
          <label htmlFor="position-scale-filter">规模定位</label>
          <Input
            id="position-scale-filter"
            aria-label="规模定位筛选"
            allowClear
            value={scale}
            placeholder="精确筛选"
            onChange={(event) => {
              setPage(1);
              setScale(event.target.value);
            }}
          />
        </div>
        <div className="position-filter-field">
          <label htmlFor="position-issue-filter">问题</label>
          <Select
            id="position-issue-filter"
            aria-label="问题筛选"
            value={issueFilter}
            options={[
              { value: "all", label: "全部问题" },
              { value: "errors", label: "仅错误" }
            ]}
            onChange={(value) => {
              setPage(1);
              setIssueFilter(value);
            }}
          />
        </div>
        <div className="position-filter-field position-filter-scope">
          <span>范围</span>
          <Checkbox
            checked={onlyModified}
            onChange={(event) => {
              setPage(1);
              setOnlyModified(event.target.checked);
            }}
          >
            仅看已修改
          </Checkbox>
        </div>
        {hasActiveFilters && (
          <Button aria-label="重置筛选" icon={<ReloadOutlined />} onClick={resetFilters}>
            重置
          </Button>
        )}
      </div>
      <div className="position-selection-bar">
        <Typography.Text type="secondary">已选择 {selectedRowIds.length} 条</Typography.Text>
        <Popconfirm
          fresh
          open={bulkDeleteConfirmOpen}
          title={`删除选中的 ${selectedRowIds.length} 条记录？`}
          description="删除会立即保存到服务器草稿，发布前不影响正式版本。"
          okText="确认删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          cancelButtonProps={{ disabled: bulkDeleting }}
          disabled={selectedRowIds.length === 0 || disabled}
          onOpenChange={onBulkDeleteOpenChange}
          onConfirm={onBulkDeleteConfirm}
        >
          <Button danger disabled={selectedRowIds.length === 0 || disabled} loading={bulkDeleting}>
            批量删除（{selectedRowIds.length}）
          </Button>
        </Popconfirm>
      </div>

      {rowsError && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          title="无法读取草稿记录"
          description={rowsError}
          action={
            <Button size="small" onClick={refreshRows}>
              重新加载
            </Button>
          }
        />
      )}
      <Table<PositionDraftRow>
        rowKey="id"
        size="small"
        classNames={{
          root: "position-records-table",
          header: { cell: "position-records-cell" },
          body: { cell: "position-records-cell" }
        }}
        styles={{ header: { cell: { paddingInline: 10 } }, body: { cell: { paddingInline: 10 } } }}
        loading={rowsLoading}
        columns={columns}
        dataSource={rows}
        components={POSITION_TABLE_COMPONENTS}
        rowSelection={{
          selectedRowKeys: selectedRowIds,
          preserveSelectedRowKeys: false,
          getCheckboxProps: () => ({ disabled }),
          onChange: (keys) => setSelectedRowIds(keys.map(Number))
        }}
        scroll={{ x: 1020 }}
        locale={{ emptyText: rowsError ? "读取失败" : "草稿中没有符合条件的记录" }}
        pagination={{
          current: page,
          pageSize,
          total: rowsTotal,
          showSizeChanger: true,
          pageSizeOptions: [20, 50, 100],
          showTotal: (total) => `共 ${total} 条`,
          onChange: (nextPage, nextPageSize) => {
            setPage(nextPageSize !== pageSize ? 1 : nextPage);
            setPageSize(nextPageSize);
          }
        }}
      />
    </Card>
  );
}
