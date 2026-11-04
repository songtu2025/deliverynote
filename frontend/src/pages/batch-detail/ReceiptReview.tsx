import { receiptReviewColumns } from "./receiptReviewColumns";
import { receiptInputBusy, receiptSiteDisabledReason } from "../../receipt";
import { useReceiptSite } from "./useReceiptSite";
import { useEffect, useRef, useState } from "react";
import { Alert, Card, Space, Switch, Table } from "antd";
import { api } from "../../api";
import { formatBeijingDateTime } from "../../dateTime";
import type { Batch } from "../../types";
import ReceiptReviewDetails from "./ReceiptReviewDetails";
import type { ReceiptRow } from "./ReceiptReviewDetails";
import type { BatchAction } from "./useBatchAction";

export default function ReceiptReview({
  batch,
  runAction,
  load,
  onRefresh,
  onVersions,
  issuesOnly: initialIssuesOnly = false
}: {
  batch: Batch;
  runAction: BatchAction;
  load: (silent?: boolean) => Promise<unknown>;
  issuesOnly?: boolean;
  onRefresh?: () => Promise<void>;
  onVersions?: () => void;
}) {
  const [page, setPage] = useState(1);
  const [issuesOnly, setIssuesOnly] = useState(initialIssuesOnly);
  const [target, setTarget] = useState<ReceiptRow | null>(null);
  const busy = receiptBusy(batch);
  const captured = batch.receipt?.captured_at;
  const issueCount = batch.receipt?.issue_count ?? 0;
  const { rows, total, loading, error } = useReceiptRows(batch, busy, page, issuesOnly);

  useEffect(() => {
    if (issuesOnly && issueCount === 0) {
      setIssuesOnly(false);
      setPage(1);
    }
  }, [issuesOnly, issueCount]);

  const chooseSite = useReceiptSite(batch.id, runAction, load, () => setTarget(null));
  const siteDisabledReason = receiptSiteDisabledReason(batch);
  const refreshing = receiptInputBusy(batch);

  return (
    <Card
      title={<ReceiptTitle captured={captured} />}
      variant="borderless"
      className="section-card"
      classNames={{ body: "batch-detail-panel-body" }}
    >
      {error && <Alert type="error" title={error} />}
      {captured && (
        <>
          {issueCount > 0 && !initialIssuesOnly && (
            <Space className="inline-alert">
              <Switch
                checked={issuesOnly}
                onChange={(value) => {
                  setIssuesOnly(value);
                  setPage(1);
                }}
                aria-label="仅显示待核对"
              />
              <span>仅显示待核对 · {issueCount} 项</span>
            </Space>
          )}
          <Table<ReceiptRow>
            rowKey={(row) => `${row.file_id}:${row.sku}:${row.original_site}`}
            loading={loading || busy}
            dataSource={rows}
            locale={{ emptyText: receiptEmptyText(busy, loading) }}
            scroll={{ x: 1100 }}
            pagination={{
              current: page,
              pageSize: 20,
              total,
              showSizeChanger: false,
              placement: ["bottomEnd"],
              onChange: setPage
            }}
            columns={receiptReviewColumns({
              inline: initialIssuesOnly,
              siteDisabledReason,
              refreshing,
              chooseSite,
              onRefresh,
              onVersions,
              onOpen: setTarget
            })}
          />
        </>
      )}
      <ReceiptReviewDetails
        target={target}
        busy={Boolean(siteDisabledReason)}
        onClose={() => setTarget(null)}
        onChooseSite={chooseSite}
      />
    </Card>
  );
}

function ReceiptTitle({ captured }: { captured?: string }) {
  return (
    <div className="receipt-review-title">
      累计实收核对{" "}
      <span>本次申请 = 累计实收 − 历史已入库{captured && ` · 快照 ${formatBeijingDateTime(captured)}`}</span>
    </div>
  );
}

// 只有取历史与计算会改变核对结果；整批采购数据、导出任务不阻塞核对明细。
function receiptBusy(batch: Batch) {
  const active = (status?: string) => status === "queued" || status === "running";
  return active(batch.status) || active(batch.jobs?.prepare?.status) || active(batch.jobs?.compute?.status);
}

function receiptEmptyText(busy: boolean, loading: boolean) {
  if (busy) return "历史核对完成后显示";
  return loading ? "正在读取核对明细" : "没有核对记录";
}

function useReceiptRows(batch: Batch, busy: boolean, page: number, issuesOnly: boolean) {
  const [rows, setRows] = useState<ReceiptRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 只在首次加载或切换页码、筛选时显示加载遮罩，批次轮询刷新时保留当前列表。
  const loadedKey = useRef<string | null>(null);
  const captured = batch.receipt?.captured_at;
  const blocked = issuesOnly && !batch.receipt?.issue_count;

  useEffect(() => {
    if (!captured || busy || blocked) {
      // 被取消的请求不会再清除加载状态，这里统一复位，避免一直转圈。
      setLoading(false);
      return;
    }
    let cancelled = false;
    const query = new URLSearchParams({ page: String(page), page_size: "20", issues_only: String(issuesOnly) });
    const key = `${batch.id}:${query}`;
    if (loadedKey.current !== key) setLoading(true);
    api<{ items: ReceiptRow[]; total: number }>(`/api/batches/${batch.id}/receipts?${query}`)
      .then((result) => {
        if (!cancelled) {
          setRows(result.items);
          setTotal(result.total);
          setError(null);
          loadedKey.current = key;
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
  }, [batch.id, batch.updated_at, captured, busy, blocked, page, issuesOnly]);

  return { rows, total, loading, error };
}
