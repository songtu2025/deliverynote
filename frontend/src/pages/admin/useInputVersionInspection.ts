import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../api";
import { getInputVersionInspection } from "../../inputVersionApi";
import type { InputVersionInspection, PositionIssue } from "../../types";

function issueCount(issues: PositionIssue[], severity: PositionIssue["severity"]): number {
  return issues.reduce(
    (total, issue) => total + (issue.severity === severity ? Math.max(1, issue.row_numbers.length) : 0),
    0
  );
}

export function useInputVersionInspection(activeVersionId: number | undefined, loading: boolean) {
  const [inspections, setInspections] = useState(() => new Map<number, InputVersionInspection>());
  const inspectionRequests = useRef(new Map<number, Promise<InputVersionInspection>>());
  const [inspectionLoading, setInspectionLoading] = useState(false);
  const [inspectionError, setInspectionError] = useState<{ versionId: number; message: string } | null>(null);
  const [inspectionAttempt, setInspectionAttempt] = useState(0);
  const inspection = activeVersionId === undefined ? null : (inspections.get(activeVersionId) ?? null);

  useEffect(() => {
    setInspectionError(null);
    if (loading || activeVersionId === undefined) {
      setInspectionLoading(false);
      return undefined;
    }

    let cancelled = false;
    const versionId = activeVersionId;
    if (inspection) {
      setInspectionLoading(false);
      return undefined;
    }

    let request = inspectionRequests.current.get(versionId);
    if (!request) {
      request = getInputVersionInspection(versionId).then(
        (inspection) => {
          setInspections((current) => {
            const next = new Map(current);
            next.set(versionId, inspection);
            return next;
          });
          inspectionRequests.current.delete(versionId);
          return inspection;
        },
        (error: unknown) => {
          inspectionRequests.current.delete(versionId);
          throw error;
        }
      );
      inspectionRequests.current.set(versionId, request);
    }

    setInspectionLoading(true);
    void request
      .catch((error: unknown) => {
        if (cancelled || (error instanceof ApiError && error.status === 401)) return;
        setInspectionError({
          versionId,
          message: error instanceof Error ? error.message : "读取当前版本失败"
        });
      })
      .finally(() => {
        if (!cancelled) setInspectionLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeVersionId, inspection, inspectionAttempt, loading]);

  const summary = inspection?.summary;

  return {
    inspection,
    inspectionLoading,
    inspectionError,
    retryInspection: () => setInspectionAttempt((value) => value + 1),
    errors: summary ? issueCount(summary.issues, "error") : 0,
    warnings: summary ? issueCount(summary.issues, "warning") : 0
  };
}
