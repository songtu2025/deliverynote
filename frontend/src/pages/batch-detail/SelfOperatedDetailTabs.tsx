import type { ReactNode } from "react";
import { Drawer, Tabs, theme } from "antd";
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
        <Tabs
          classNames={{ header: "self-operated-tab-nav", item: "self-operated-tab-item" }}
          styles={{ header: { zIndex: token.zIndexBase + 1 } }}
          activeKey={selected}
          onChange={(key) => {
            if (key === "receipts") onChange(key);
            else if (key === "unfinished" || key === "resolved" || key === "all") {
              if (key !== reviewState.reviewScope) reviewState.changeScope(key);
              onReset();
              onChange("review");
            }
          }}
          tabBarGutter={12}
          items={[
            ...scopes.map(({ key, label, count }) => ({
              key,
              label: `${label}（${count ?? "读取中"}）`,
              children: key === reviewState.reviewScope ? review : null
            })),
            { key: "receipts", label: "累计实收核对", children: receipts }
          ]}
        />
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
