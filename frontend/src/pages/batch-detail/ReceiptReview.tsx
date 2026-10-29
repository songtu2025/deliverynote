import { useEffect, useState } from "react";
import { Alert, App, Button, Card, Popconfirm, Space, Switch, Table } from "antd";
import { api } from "../../api";
import { formatBeijingDateTime } from "../../dateTime";
import type { Batch } from "../../types";
import ReceiptReviewDetails from "./ReceiptReviewDetails";
import type { ReceiptRow } from "./ReceiptReviewDetails";
import type { BatchAction } from "./useBatchAction";

export default function ReceiptReview({
  batch,
  runAction,
  load
}: {
  batch: Batch;
  runAction: BatchAction;
  load: (silent?: boolean) => Promise<unknown>;
}) {
  const { message } = App.useApp();
  const [page, setPage] = useState(1);
  const [issuesOnly, setIssuesOnly] = useState(false);
  const [rows, setRows] = useState<ReceiptRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<ReceiptRow | null>(null);
  const busy = receiptBusy(batch);
  const captured = batch.receipt?.captured_at;

  useEffect(() => {
    let cancelled = false;
    if (!captured || busy) return;
    const query = new URLSearchParams({ page: String(page), page_size: "20", issues_only: String(issuesOnly) });
    setLoading(true);
    api<{ items: ReceiptRow[]; total: number }>(`/api/batches/${batch.id}/receipts?${query}`)
      .then((result) => {
        if (!cancelled) {
          setRows(result.items);
          setTotal(result.total);
          setError(null);
        }
      })
      .catch((failure: unknown) => {
        if (!cancelled) setError(failure instanceof Error ? failure.message : "读取核对明细失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [batch.id, batch.updated_at, captured, busy, page, issuesOnly]);

  const refresh = () =>
    runAction("refresh-history", async () => {
      await api(`/api/batches/${batch.id}/receipts/refresh`, { method: "POST" });
      setTarget(null);
      setPage(1);
      await load(true);
      message.info("已重新排队获取历史，原计算与导出已失效");
    });
  const chooseSite = (row: ReceiptRow, site: string) =>
    runAction("receipt-site", async () => {
      await api(`/api/batches/${batch.id}/files/${row.file_id}/receipt-site`, {
        method: "PUT",
        body: JSON.stringify({ sku: row.sku, original_site: row.original_site, full_site: site })
      });
      setTarget(null);
      await load(true);
      message.info("已保存该文件的站点选择，正在重新核对");
    });

  return (
    <Card
      title="累计实收核对"
      className="section-card"
      extra={
        <Popconfirm
          title="重新获取历史？"
          description="会清除当前计算与导出结果，再按本批单号获取最新历史。"
          onConfirm={refresh}
        >
          <Button disabled={busy || !batch.files?.length}>重新取数</Button>
        </Popconfirm>
      }
    >
      <ReceiptNotice batch={batch} />
      {error && <Alert type="error" title={error} />}
      {captured && (
        <>
          <Space className="inline-alert">
            <Switch
              checked={issuesOnly}
              onChange={(value) => {
                setIssuesOnly(value);
                setPage(1);
              }}
              aria-label="仅显示待核对"
            />
            <span>仅显示待核对 · {batch.receipt?.issue_count ?? 0} 项</span>
          </Space>
          <Table<ReceiptRow>
            rowKey={(row) => `${row.file_id}:${row.sku}:${row.original_site}`}
            loading={loading || busy}
            dataSource={rows}
            scroll={{ x: 1100 }}
            pagination={{ current: page, pageSize: 20, total, showSizeChanger: false, onChange: setPage }}
            columns={[
              { title: "文件", dataIndex: "filename", ellipsis: true, width: 200 },
              { title: "SKU", dataIndex: "sku", width: 170 },
              { title: "完整站点", dataIndex: "full_site", width: 200, ellipsis: true },
              { title: "累计实收", dataIndex: "cumulative", width: 90 },
              { title: "历史已入库", dataIndex: "history", width: 100, render: (value) => value ?? "待核对" },
              { title: "本次申请", dataIndex: "requested", width: 100, render: (value) => value ?? "待核对" },
              {
                title: "核对结果",
                dataIndex: "issue",
                width: 240,
                render: (value, row) => value || row.notice || "已核对"
              },
              {
                title: "操作",
                width: 100,
                render: (_, row) => (
                  <Button size="small" onClick={() => setTarget(row)}>
                    查看明细
                  </Button>
                )
              }
            ]}
          />
        </>
      )}
      <ReceiptReviewDetails target={target} busy={busy} onClose={() => setTarget(null)} onChooseSite={chooseSite} />
    </Card>
  );
}

function receiptBusy(batch: Batch) {
  return (
    ["queued", "running"].includes(batch.status) ||
    Object.values(batch.jobs ?? {}).some((job) => job?.status === "queued" || job?.status === "running")
  );
}

function ReceiptNotice({ batch }: { batch: Batch }) {
  const captured = batch.receipt?.captured_at;
  const description = captured
    ? `本次申请 = 累计实收 − 历史已入库。快照时间：${formatBeijingDateTime(captured)}。重复计算复用此快照；已完结单据只核算历史。`
    : "执行预检后获取完整历史。历史未确认时不计算、不导出；旧批次需要重新预检。";
  return (
    <Alert
      type={batch.receipt?.issue_count ? "warning" : "info"}
      showIcon
      className="inline-alert"
      title="表格「实收数量」按单份 Excel 内的累计实收解释，不跨文件累计。"
      description={description}
    />
  );
}
