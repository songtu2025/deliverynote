import { useRef } from "react";
import type { ReactNode } from "react";
import { Alert, Tabs } from "antd";
import type { TabsRef } from "antd/es/tabs";
import type { Batch } from "../../types";
import { batchPresentation } from "./batchPresentation";
import type { ExceptionReview } from "./useExceptionReview";

export default function SelfOperatedDetailTabs({
  batch,
  activeKey,
  onChange,
  reviewStats,
  files,
  versions,
  receipts,
  review
}: {
  batch: Batch;
  activeKey?: string;
  onChange: (key: string) => void;
  reviewStats?: ExceptionReview["reviewStats"];
  files: ReactNode;
  versions: ReactNode;
  receipts: ReactNode;
  review: ReactNode;
}) {
  const tabs = useRef<TabsRef>(null);
  const { computed, needsReview } = batchPresentation(batch);
  const defaultKey = needsReview ? "review" : batch.receipt?.captured_at ? "receipts" : "files";
  const pendingLabel = computed ? (reviewStats ? `${reviewStats.unfinishedCount} 条未完成` : "读取中") : "计算后生成";
  return (
    <Tabs
      ref={tabs}
      className="self-operated-detail-tabs"
      activeKey={activeKey ?? defaultKey}
      onChange={(key) => {
        onChange(key);
        requestAnimationFrame(() => tabs.current?.nativeElement?.scrollIntoView?.({ block: "start" }));
      }}
      tabBarGutter={24}
      items={[
        { key: "receipts", label: "累计实收核对", children: receipts },
        {
          key: "review",
          label: (
            <span>
              待处理审校 <small className="detail-tab-count">{pendingLabel}</small>
            </span>
          ),
          children: computed ? (
            review
          ) : (
            <Alert
              type="info"
              showIcon
              title="启动计算后生成待处理明细"
              description="预检只核对累计实收与历史；计算完成后，可在这里查看未匹配、超量等记录及其待处理数量。"
            />
          )
        },
        { key: "files", label: "业务文件", children: files },
        { key: "versions", label: "锁定版本", children: versions }
      ]}
    />
  );
}
