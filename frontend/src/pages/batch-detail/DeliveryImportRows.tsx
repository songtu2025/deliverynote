import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Empty, Input, Table } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { getBatchImportRows, REVIEW_PAGE_SIZE } from "../../batchDetailApi";
import type { Batch, DeliveryImportRow } from "../../types";
import { useDebouncedValue } from "../../useDebouncedValue";

export default function DeliveryImportRows({ batch }: { batch: Batch }) {
  const [query, setQuery] = useState("");
  const search = useDebouncedValue(query, 250);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<{ items: DeliveryImportRow[]; total: number }>({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  // 只在首次加载或切换页码、搜索时显示加载遮罩，批次刷新时保留当前列表。
  const loadedKey = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({
      offset: String((page - 1) * REVIEW_PAGE_SIZE),
      limit: String(REVIEW_PAGE_SIZE)
    });
    if (search.trim()) params.set("search", search.trim());
    const key = `${batch.id}:${params}`;
    if (loadedKey.current !== key) setLoading(true);
    getBatchImportRows(batch.id, params)
      .then((next) => {
        if (!cancelled) {
          setResult(next);
          setError(null);
          loadedKey.current = key;
        }
      })
      .catch((failure: unknown) => {
        if (!cancelled) setError(failure instanceof Error ? failure.message : "读取可导入记录失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [batch.id, batch.updated_at, batch.status, page, search, retry]);

  return (
    <Card variant="borderless" classNames={{ body: "batch-detail-panel-body" }}>
      <div className="table-toolbar">
        <Input
          aria-label="搜索可导入记录"
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索来源、SKU、站点或目的仓"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setPage(1);
          }}
        />
      </div>
      {error && (
        <Alert
          type="error"
          title={error}
          action={
            <Button aria-label="重试" onClick={() => setRetry((value) => value + 1)}>
              重试
            </Button>
          }
        />
      )}
      <Table<DeliveryImportRow>
        rowKey={(row) => `${row.file_id}:${row.row_index}`}
        loading={loading}
        size="small"
        dataSource={result.items}
        scroll={{ x: 1100 }}
        pagination={
          result.total > REVIEW_PAGE_SIZE
            ? {
                current: page,
                pageSize: REVIEW_PAGE_SIZE,
                total: result.total,
                showSizeChanger: false,
                placement: ["bottomEnd"],
                onChange: setPage
              }
            : false
        }
        locale={{
          emptyText: loading ? (
            "正在读取可导入记录"
          ) : (
            <Empty description={search.trim() ? "没有匹配的可导入记录" : "没有可导入记录"} />
          )
        }}
        columns={[
          { title: "文件", dataIndex: "file_name", width: 200, ellipsis: true },
          { title: "SKU", dataIndex: "sku", width: 150 },
          { title: "站点", dataIndex: "site", width: 180, ellipsis: true },
          { title: "目的仓", dataIndex: "warehouse", width: 150, ellipsis: true },
          { title: "本次交货量", dataIndex: "quantity", align: "right", width: 100 },
          { title: "单据备注", dataIndex: "document_note", width: 160, render: (value: string) => value || "—" },
          { title: "交货备注", dataIndex: "delivery_note", width: 160, render: (value: string) => value || "—" }
        ]}
      />
    </Card>
  );
}
