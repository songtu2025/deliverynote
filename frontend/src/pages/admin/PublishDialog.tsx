import { Alert, Checkbox, Form, Input, Modal, Space } from "antd";

import type { PositionDraftValidation } from "../../types";
import { DiffTags, IssueList } from "./PositionFeedback";

export function PublishDialog({
  validation,
  versionName,
  nameError,
  publishError,
  warningsConfirmed,
  publishing,
  blocked,
  onNameChange,
  onWarningsChange,
  onPublish,
  onCancel,
  onClosed
}: {
  validation: PositionDraftValidation | null;
  versionName: string;
  nameError: string | null;
  publishError: string | null;
  warningsConfirmed: boolean;
  publishing: boolean;
  blocked: boolean;
  onNameChange: (value: string) => void;
  onWarningsChange: (checked: boolean) => void;
  onPublish: () => void;
  onCancel: () => void;
  onClosed: () => void;
}) {
  return (
    <Modal
      title="发布新的MSKU定位版本"
      open={validation !== null}
      styles={{ body: { maxHeight: "calc(100vh - 300px)", overflowY: "auto" } }}
      okText="确认发布"
      cancelText="继续修改草稿"
      okButtonProps={{ disabled: blocked }}
      cancelButtonProps={{ disabled: publishing }}
      confirmLoading={publishing}
      closable={!publishing}
      keyboard={!publishing}
      mask={{ closable: !publishing }}
      focusable={{ focusTriggerAfterClose: false }}
      afterClose={onClosed}
      onOk={onPublish}
      onCancel={() => {
        if (!publishing) onCancel();
      }}
    >
      {validation && (
        <Space orientation="vertical" size={14} style={{ width: "100%" }}>
          <Alert type="info" showIcon title="仅用于新批次；已有批次不变" description="发布后立即启用。" />
          <Form layout="vertical">
            <Form.Item label="新版本名称" required validateStatus={nameError ? "error" : undefined} help={nameError}>
              <Input
                aria-label="新版本名称"
                value={versionName}
                disabled={publishing}
                maxLength={200}
                onChange={(event) => onNameChange(event.target.value)}
              />
            </Form.Item>
          </Form>
          {publishError && <Alert type="error" showIcon title="发布未完成" description={publishError} />}
          <DiffTags diff={validation.diff} />
          {validation.error_count > 0 && (
            <Alert type="error" showIcon title={`存在 ${validation.error_count} 个错误，修正后才能发布`} />
          )}
          {validation.warning_count > 0 && (
            <Alert type="warning" showIcon title={`存在 ${validation.warning_count} 个警告，请确认后发布`} />
          )}
          <IssueList issues={validation.issues} />
          {validation.warning_count > 0 && (
            <Checkbox
              disabled={publishing}
              checked={warningsConfirmed}
              onChange={(event) => onWarningsChange(event.target.checked)}
            >
              我已检查并确认发布这些警告
            </Checkbox>
          )}
        </Space>
      )}
    </Modal>
  );
}
