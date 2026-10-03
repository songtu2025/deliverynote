import { useState } from "react";

export type SyncIssueFilter = "all" | "warning" | "error";
export type SyncInspectionState<Preview, Issue> = ReturnType<typeof useSyncInspection<Preview, Issue>>;

export function useSyncInspection<Preview, Issue>({
  jobId,
  hasCandidate,
  readPreview,
  readIssues,
  clearIssuesOnOpen = false
}: {
  jobId?: number;
  hasCandidate: boolean;
  readPreview: (jobId: number) => Promise<Preview>;
  readIssues: (jobId: number) => Promise<Issue[]>;
  clearIssuesOnOpen?: boolean;
}) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [issuesOpen, setIssuesOpen] = useState(false);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [issuesError, setIssuesError] = useState("");
  const [issues, setIssues] = useState<Issue[]>([]);
  const [issueFilter, setIssueFilter] = useState<SyncIssueFilter>("warning");

  const openPreview = async () => {
    if (!jobId || !hasCandidate) return;
    setPreviewOpen(true);
    setPreviewLoading(true);
    setPreviewError("");
    setPreview(null);
    try {
      setPreview(await readPreview(jobId));
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "读取候选数据失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const openIssues = async (filter: SyncIssueFilter) => {
    if (!jobId) return;
    setIssueFilter(filter);
    setIssuesOpen(true);
    setIssuesError("");
    setIssuesLoading(true);
    if (clearIssuesOnOpen) setIssues([]);
    try {
      setIssues(await readIssues(jobId));
    } catch (error) {
      setIssuesError(error instanceof Error ? error.message : "读取异常数据失败");
    } finally {
      setIssuesLoading(false);
    }
  };

  return {
    previewOpen,
    setPreviewOpen,
    previewLoading,
    previewError,
    preview,
    issuesOpen,
    setIssuesOpen,
    issuesLoading,
    issuesError,
    issues,
    issueFilter,
    setIssueFilter,
    openPreview,
    openIssues
  };
}
