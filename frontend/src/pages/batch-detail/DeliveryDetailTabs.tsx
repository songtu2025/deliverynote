import type { ReactNode } from "react";
import { Card, Tabs } from "antd";
import type { ExceptionReview } from "./useExceptionReview";

export default function DeliveryDetailTabs({
  computed,
  activeKey,
  onChange,
  reviewStats,
  fileCount,
  files,
  versions,
  review
}: {
  computed: boolean;
  activeKey?: string;
  onChange: (key: string) => void;
  reviewStats?: ExceptionReview["reviewStats"];
  fileCount: number;
  files: ReactNode;
  versions: ReactNode;
  review: ReactNode;
}) {
  const selected = !computed && activeKey === "review" ? "files" : (activeKey ?? (computed ? "review" : "files"));
  return (
    <Card className="delivery-detail-tabs" classNames={{ body: "delivery-detail-tabs-body" }}>
      <Tabs
        activeKey={selected}
        onChange={onChange}
        items={[
          ...(computed
            ? [{ key: "review", label: `待处理 ${reviewStats?.unfinishedCount ?? "—"}`, children: review }]
            : []),
          { key: "files", label: `来源文件 ${fileCount}`, children: files },
          { key: "versions", label: "锁定资料", children: versions }
        ]}
      />
    </Card>
  );
}
