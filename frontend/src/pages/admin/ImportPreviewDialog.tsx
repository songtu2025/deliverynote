import { Alert, Modal, Space, Typography } from "antd";

import type { PositionImportPreview } from "../../types";
import { DiffTags, IssueList } from "./PositionFeedback";

export function ImportPreviewDialog({
  preview,
  fileName,
  applying,
  onApply,
  onCancel,
  onClosed
}: {
  preview: PositionImportPreview | null;
  fileName: string;
  applying: boolean;
  onApply: () => void;
  onCancel: () => void;
  onClosed: () => void;
}) {
  return (
    <Modal
      title="Excel 整表替换预览"
      open={preview !== null}
      focusable={{ focusTriggerAfterClose: false }}
      okText="应用整表替换"
      cancelText="取消"
      okButtonProps={{ danger: true }}
      cancelButtonProps={{ disabled: applying }}
      confirmLoading={applying}
      closable={!applying}
      keyboard={!applying}
      mask={{ closable: !applying }}
      onOk={onApply}
      afterClose={onClosed}
      onCancel={() => {
        if (!applying) onCancel();
      }}
    >
      {preview && (
        <Space orientation="vertical" size={14} style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            title={`即将用 ${fileName} 的 ${preview.row_count} 行完整替换当前草稿`}
            description="只有确认应用后才会修改服务器草稿；当前正式版本不会改变。"
          />
          <DiffTags diff={preview.diff} />
          <Typography.Text>
            错误 {preview.error_count} · 警告 {preview.warning_count}
          </Typography.Text>
          <IssueList issues={preview.issues} />
        </Space>
      )}
    </Modal>
  );
}
