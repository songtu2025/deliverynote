import { useRef, useState, type ReactNode } from "react";
import { Drawer, Segmented, theme } from "antd";
import type { Batch } from "../../types";
import { batchPresentation } from "./batchPresentation";
import type { ExceptionReview } from "./useExceptionReview";

export default function SelfOperatedDetailTabs({
  batch,
  activeKey,
  onChange,
  reviewStats,
  reviewState,
  onReset,
  materialsOpen,
  onCloseMaterials,
  files,
  versions,
  receipts,
  review
}: {
  batch: Batch;
  activeKey?: string;
  onChange: (key: string) => void;
  reviewStats?: ExceptionReview["reviewStats"];
  reviewState: ExceptionReview;
  onReset: () => void;
  materialsOpen: boolean;
  onCloseMaterials: () => void;
  files: ReactNode;
  versions: ReactNode;
  receipts: ReactNode;
  review: ReactNode;
}) {
  const { token } = theme.useToken();
  const [receiptsVisited, setReceiptsVisited] = useState(activeKey === "receipts");
  const reviewRef = useRef<HTMLDivElement>(null);
  const [reviewHeight, setReviewHeight] = useState<number>();
  const { computed } = batchPresentation(batch);
  const selected = activeKey === "receipts" ? "receipts" : reviewState.reviewScope;
  const scopes = [
    { key: "unfinished", label: "未完成", count: reviewStats?.unfinishedCount },
    { key: "resolved", label: "已处理", count: reviewStats?.resolvedCount },
    { key: "all", label: "全部审校", count: reviewStats?.totalCount }
  ] as const;
  return (
    <div className="self-operated-detail-tabs">
      {computed ? (
        <>
          <div className="self-operated-tab-nav" style={{ zIndex: token.zIndexBase + 1 }}>
            <Segmented
              aria-label="审校状态与实收核对"
              classNames={{ item: "self-operated-tab-item" }}
              value={selected}
              onChange={(key) => {
                if (key === "receipts") {
                  setReceiptsVisited(true);
                  onChange(key);
                } else if (key === "unfinished" || key === "resolved" || key === "all") {
                  // 空结果保留切换前的工作区高度，避免页面缩短后浏览器强制调整滚动位置。
                  if (selected !== "receipts") setReviewHeight(reviewRef.current?.offsetHeight);
                  if (key !== reviewState.reviewScope) reviewState.changeScope(key);
                  onReset();
                  onChange("review");
                }
              }}
              options={[
                ...scopes.map(({ key, label, count }) => ({
                  value: key,
                  label: `${label}（${count ?? "读取中"}）`
                })),
                { value: "receipts", label: "累计实收核对" }
              ]}
            />
          </div>
          {/* 审校状态只改变筛选条件，保持同一表格实例，避免切换面板造成高度瞬间收缩。 */}
          <div
            ref={reviewRef}
            className="self-operated-review-content"
            hidden={selected === "receipts"}
            style={{ minHeight: reviewHeight }}
          >
            {review}
          </div>
          <div hidden={selected !== "receipts"}>{receiptsVisited && receipts}</div>
        </>
      ) : (
        <>
          {files}
          {batch.receipt?.captured_at ? receipts : null}
        </>
      )}
      <Drawer title="批次资料" open={materialsOpen} onClose={onCloseMaterials} size="large">
        {computed && files}
        {versions}
      </Drawer>
    </div>
  );
}
