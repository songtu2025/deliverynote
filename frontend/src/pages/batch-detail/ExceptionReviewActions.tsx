import { Button, Tooltip } from "antd";
import type { ExceptionEditor } from "./useExceptionEditor";

export default function ExceptionReviewActions({ editor, action }: { editor: ExceptionEditor; action: string | null }) {
  const {
    exceptionTotal,
    reviewNavigationLocked,
    canReviewPrevious,
    canReviewNext,
    navigateReview,
    setSplitTarget,
    splitTarget
  } = editor;
  return (
    <div className="drawer-footer">
      {exceptionTotal > 1 && (
        <div className="drawer-review-navigation">
          <Tooltip title={reviewNavigationLocked ? "当前有未保存修改，请先保存" : ""}>
            <span>
              <Button
                disabled={!canReviewPrevious || reviewNavigationLocked}
                onClick={() => navigateReview("previous")}
              >
                上一条
              </Button>
            </span>
          </Tooltip>
          <Tooltip title={reviewNavigationLocked ? "当前有未保存修改，请先保存" : ""}>
            <span>
              <Button disabled={!canReviewNext || reviewNavigationLocked} onClick={() => navigateReview("next")}>
                下一条
              </Button>
            </span>
          </Tooltip>
        </div>
      )}
      <div className="drawer-review-actions">
        <Button aria-label="取消" onClick={() => setSplitTarget(null)}>
          取消
        </Button>
        {splitTarget?.allowed_actions.includes("split") && <SplitSaveActions editor={editor} action={action} />}
      </div>
    </div>
  );
}

function SplitSaveActions({ editor, action }: { editor: ExceptionEditor; action: string | null }) {
  const { canReviewNext, splitValid, saveSplit } = editor;
  return (
    <>
      {canReviewNext && (
        <Tooltip title={splitValid ? "" : "拆分数量必须为正数，且合计必须等于原待处理量"}>
          <Button
            aria-label="保存"
            disabled={!splitValid}
            loading={action === "split"}
            onClick={() => void saveSplit(false)}
          >
            保存
          </Button>
        </Tooltip>
      )}
      <Tooltip title={splitValid ? "" : "拆分数量必须为正数，且合计必须等于原待处理量"}>
        <Button
          aria-label={canReviewNext ? "保存，下一条" : "保存"}
          type="primary"
          disabled={!splitValid}
          loading={action === "split"}
          onClick={() => void saveSplit(canReviewNext)}
        >
          {canReviewNext ? "保存，下一条" : "保存"}
        </Button>
      </Tooltip>
    </>
  );
}
