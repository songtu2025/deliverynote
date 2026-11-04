import { useEffect, useState, type ReactNode } from "react";
import { Card, Tabs } from "antd";
import type { ExceptionReview } from "./useExceptionReview";
import type { Batch } from "../../types";
import DeliveryImportRows from "./DeliveryImportRows";
import { getBatchImportRows } from "../../batchDetailApi";

export default function DeliveryDetailTabs({
  batch,
  computed,
  activeKey,
  onChange,
  reviewStats,
  fileCount,
  files,
  versions,
  review
}: {
  batch: Batch;
  computed: boolean;
  activeKey?: string;
  onChange: (key: string) => void;
  reviewStats?: ExceptionReview["reviewStats"];
  fileCount: number;
  files: ReactNode;
  versions: ReactNode;
  review: ReactNode;
}) {
  const importCount = useImportRowCount(batch, computed);
  const selected = computed ? (activeKey ?? "review") : activeKey === "versions" ? "versions" : "files";
  return (
    <Card className="delivery-detail-tabs" classNames={{ body: "delivery-detail-tabs-body" }}>
      <Tabs
        activeKey={selected}
        onChange={onChange}
        items={[
          ...(computed
            ? [
                { key: "review", label: `待处理 ${reviewStats?.unfinishedCount ?? "—"}`, children: review },
                {
                  key: "imports",
                  label: `可导入 ${importCount ?? "—"}`,
                  children: <DeliveryImportRows key={batch.id} batch={batch} />
                }
              ]
            : []),
          { key: "files", label: `来源文件 ${fileCount}`, children: files },
          { key: "versions", label: "锁定资料", children: versions }
        ]}
      />
    </Card>
  );
}

// 标签与「待处理」一致按记录条数计数，件数见数量条。
function useImportRowCount(batch: Batch, computed: boolean) {
  const [count, setCount] = useState<number>();
  useEffect(() => {
    if (!computed) return;
    let active = true;
    getBatchImportRows(batch.id, new URLSearchParams({ offset: "0", limit: "1" })).then(
      (result) => {
        if (active) setCount(result.total);
      },
      () => {
        if (active) setCount(undefined);
      }
    );
    return () => {
      active = false;
    };
  }, [batch.id, batch.updated_at, computed]);
  return count;
}
