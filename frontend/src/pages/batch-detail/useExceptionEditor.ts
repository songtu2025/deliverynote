import type { BatchAction } from "./useBatchAction";
import { useEffect, useState } from "react";
import { App as AntApp, Form } from "antd";
import type { DeliveryException, SplitPart } from "../../types";
import { REVIEW_PAGE_SIZE, saveExceptionSplit, resolveSelfOperatedSite } from "../../batchDetailApi";
import type { ExceptionPage, ExceptionReview } from "../useExceptionReview";
import { candidateSites, initialSplitPart, reviewNeighbors, summarizeSplit } from "./reviewDraft";

export type SplitFormValues = { parts: SplitPart[] };

export function useExceptionEditor({
  splitTarget,
  setSplitTarget,
  review,
  selfOperated,
  runAction,
  load
}: {
  splitTarget: DeliveryException | null;
  setSplitTarget: (target: DeliveryException | null) => void;
  review: ExceptionReview;
  selfOperated: boolean;
  runAction: BatchAction;
  load: (silent?: boolean) => Promise<ExceptionPage | null>;
}) {
  const { message } = AntApp.useApp();
  const { exceptions, exceptionTotal, reviewPage, setReviewPage, queueReviewDirection, replaceException } = review;
  const [reviewDirty, setReviewDirty] = useState(false);
  const [splitForm] = Form.useForm<SplitFormValues>();
  const splitParts = Form.useWatch("parts", splitForm) ?? [];
  const openSplit = setSplitTarget;
  useEffect(() => {
    if (!splitTarget) return;
    splitForm.resetFields();
    setReviewDirty(false);
    splitForm.setFieldsValue({
      parts: splitTarget.parts.length ? splitTarget.parts : [initialSplitPart(splitTarget)]
    });
  }, [splitForm, splitTarget]);
  const neighbors = reviewNeighbors(splitTarget, exceptions, reviewPage, exceptionTotal);
  const currentReviewIndex = neighbors.index;
  const previousReviewTarget = neighbors.previous;
  const nextReviewTarget = neighbors.next;
  const canReviewPrevious = neighbors.canPrevious;
  const canReviewNext = neighbors.canNext;
  const navigateReview = (direction: "previous" | "next") => {
    const withinPage = direction === "previous" ? previousReviewTarget : nextReviewTarget;
    if (withinPage) {
      openSplit(withinPage);
      return;
    }
    queueReviewDirection(direction === "previous" ? "last" : "first");
    setReviewPage((current) => current + (direction === "previous" ? -1 : 1));
  };
  const reviewNavigationLocked = reviewDirty;

  const split = summarizeSplit(splitTarget, splitParts);
  const splitTotal = split.total;
  const splitRemaining = split.remaining;
  const splitValid = split.valid;
  const splitCandidateSites =
    splitTarget?.reason_code === "ambiguous_product_site" ? candidateSites(splitTarget.full_site) : [];
  const selfOperatedSiteSelection = Boolean(selfOperated && splitTarget?.allowed_actions.includes("resolve_site"));
  const selectedSelfOperatedSite = String(splitParts[0]?.site ?? "").trim();
  const selfOperatedSiteValid = splitCandidateSites.includes(selectedSelfOperatedSite);

  const continueReview = (savedId: number, savedIndex: number, refreshed: ExceptionPage | null, advance: boolean) => {
    if (advance && refreshed) {
      const savedStillVisible = refreshed.items.findIndex((item) => item.id === savedId);
      const nextIndex = savedStillVisible >= 0 ? savedStillVisible + 1 : savedIndex;
      const next = refreshed.items[nextIndex];
      if (next) {
        openSplit(next);
        return true;
      }
      if (reviewPage * REVIEW_PAGE_SIZE < refreshed.total) {
        queueReviewDirection("first");
        setReviewPage(reviewPage + 1);
        return true;
      }
    }
    setSplitTarget(null);
    splitForm.resetFields();
    return false;
  };

  const saveSplit = async (advance: boolean) => {
    if (!splitTarget || !splitValid) return;
    const savedId = splitTarget.id;
    const savedIndex = currentReviewIndex;
    const values = await splitForm.validateFields();
    await runAction("split", async () => {
      const updated = await saveExceptionSplit(savedId, values.parts);
      replaceException(updated);
      const refreshed = await load(true);
      const continued = continueReview(savedId, savedIndex, refreshed, advance);
      message.success(continued ? "当前记录已保存，已打开下一条未完成记录" : "处理结果已保存，批次数量保持守恒");
    });
  };

  const saveSelfOperatedSite = async () => {
    if (!splitTarget || !selfOperatedSiteValid) return;
    await splitForm.validateFields([["parts", 0, "site"]]);
    await runAction("site-resolution", async () => {
      await resolveSelfOperatedSite(splitTarget.id, selectedSelfOperatedSite);
      setSplitTarget(null);
      splitForm.resetFields();
      await load(true);
      message.info("站点已保存，系统正在按新站点重新计算整个批次");
    });
  };

  return {
    splitTarget,
    setSplitTarget,
    splitForm,
    setReviewDirty,
    reviewPage,
    exceptionTotal,
    currentReviewIndex,
    canReviewPrevious,
    canReviewNext,
    navigateReview,
    reviewNavigationLocked,
    splitTotal,
    splitRemaining,
    splitValid,
    splitCandidateSites,
    selfOperatedSiteSelection,
    selfOperatedSiteValid,
    saveSplit,
    saveSelfOperatedSite
  };
}
export type ExceptionEditor = ReturnType<typeof useExceptionEditor>;
