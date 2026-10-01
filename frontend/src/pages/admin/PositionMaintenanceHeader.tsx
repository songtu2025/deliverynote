import type { Ref } from "react";
import { Button, Popconfirm, Space, Typography, Upload } from "antd";
import type { UploadProps } from "antd";
import { ArrowLeftOutlined, DownloadOutlined, UploadOutlined } from "@ant-design/icons";

interface PositionMaintenanceHeaderProps {
  baseVersionName: string;
  busy: boolean;
  actionsDisabled: boolean;
  importing: boolean;
  validating: boolean;
  discarding: boolean;
  discardDisabled: boolean;
  discardConfirmOpen: boolean;
  importButtonRef: Ref<HTMLButtonElement>;
  publishButtonRef: Ref<HTMLButtonElement>;
  onBack: () => void;
  onDownload: () => Promise<void>;
  onImport: NonNullable<UploadProps["customRequest"]>;
  onDiscardOpenChange: (open: boolean) => void;
  onDiscardConfirm: () => Promise<void>;
  onPublish: () => void;
}

export function PositionMaintenanceHeader({
  baseVersionName,
  busy,
  actionsDisabled,
  importing,
  validating,
  discarding,
  discardDisabled,
  discardConfirmOpen,
  importButtonRef,
  publishButtonRef,
  onBack,
  onDownload,
  onImport,
  onDiscardOpenChange,
  onDiscardConfirm,
  onPublish
}: PositionMaintenanceHeaderProps) {
  return (
    <div className="position-workspace-heading">
      <div className="position-workspace-title">
        <Button
          autoFocus
          aria-label="返回基础资料"
          className="back-link"
          type="link"
          icon={<ArrowLeftOutlined />}
          disabled={busy}
          onClick={onBack}
        >
          返回基础资料
        </Button>
        <Typography.Title level={2} style={{ margin: 0 }}>
          MSKU 定位维护
        </Typography.Title>
        <Typography.Text type="secondary">基于 {baseVersionName}；修改自动保存到草稿，发布后生效。</Typography.Text>
      </div>
      <Space wrap className="position-workspace-actions">
        <Button aria-label="下载草稿" icon={<DownloadOutlined />} onClick={() => void onDownload()}>
          下载草稿
        </Button>
        <Upload accept=".xls,.xlsx" showUploadList={false} disabled={actionsDisabled} customRequest={onImport}>
          <Button
            ref={importButtonRef}
            aria-label="Excel 整表替换"
            icon={<UploadOutlined />}
            disabled={actionsDisabled}
            loading={importing}
          >
            Excel 整表替换
          </Button>
        </Upload>
        <Popconfirm
          fresh
          open={discardConfirmOpen}
          title="确定放弃整个服务器草稿？"
          description="草稿中的所有修改都会丢失，当前正式版本保持不变。"
          okText="确认放弃"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          cancelButtonProps={{ disabled: discarding }}
          onOpenChange={onDiscardOpenChange}
          onConfirm={onDiscardConfirm}
        >
          <Button danger disabled={discardDisabled} loading={discarding}>
            放弃草稿
          </Button>
        </Popconfirm>
        <Button
          type="primary"
          disabled={actionsDisabled}
          loading={validating}
          ref={publishButtonRef}
          onClick={onPublish}
        >
          发布新版本
        </Button>
      </Space>
    </div>
  );
}
