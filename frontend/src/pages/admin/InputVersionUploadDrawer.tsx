import { Alert, Button, Drawer, Form, Input, Typography, Upload } from "antd";
import { InboxOutlined, UploadOutlined } from "@ant-design/icons";
import type { FormInstance, UploadFile, UploadProps } from "antd";

import { INPUT_KIND_BY_VALUE } from "./adminConstants";
import type { InputKind } from "./adminConstants";

interface InputVersionUploadDrawerProps {
  kind: InputKind;
  hasActiveVersion: boolean;
  open: boolean;
  busy: boolean;
  uploading: boolean;
  form: FormInstance<{ name: string }>;
  files: UploadFile[];
  error: string | null;
  onFileChange: NonNullable<UploadProps["onChange"]>;
  onSubmit: () => void | Promise<void>;
  onClose: () => void;
}

export function InputVersionUploadDrawer({
  kind,
  hasActiveVersion,
  open,
  busy,
  uploading,
  form,
  files,
  error,
  onFileChange,
  onSubmit,
  onClose
}: InputVersionUploadDrawerProps) {
  const definition = INPUT_KIND_BY_VALUE[kind];

  return (
    <Drawer
      rootClassName="input-data-maintenance-drawer"
      classNames={{ header: "input-data-maintenance-header", body: "input-data-maintenance-body" }}
      styles={{
        header: { borderColor: "#e2e9e7", background: "#f7f9f8" },
        body: { padding: "22px 24px" }
      }}
      title={hasActiveVersion ? `更新${definition.label}` : `上传${definition.label}`}
      size={520}
      open={open}
      getContainer={false}
      destroyOnHidden
      motion={
        import.meta.env.MODE === "test"
          ? {
              motionAppear: false,
              motionEnter: false,
              motionLeave: false
            }
          : undefined
      }
      maskMotion={
        import.meta.env.MODE === "test"
          ? {
              motionAppear: false,
              motionEnter: false,
              motionLeave: false
            }
          : undefined
      }
      closable={!busy}
      maskClosable={!busy}
      keyboard={!busy}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="input-data-maintenance-form">
        <Typography.Title level={5}>{hasActiveVersion ? "上传替换当前版本" : "上传首个版本"}</Typography.Title>
        <Typography.Paragraph type="secondary">选择文件并确认版本名称；校验通过后立即启用。</Typography.Paragraph>
        {kind === "supplier" && (
          <Alert
            type="info"
            showIcon
            title="供应商别名为可选列"
            styles={{ root: { borderRadius: 8 } }}
            description="一个单元格内的多个别名请用 | 分隔。启用供应商之间名称或别名相同、互为子串时，上传会被拒绝并提示 Excel 行号。"
          />
        )}
        {error !== null && (
          <Alert
            className="inline-alert"
            type="error"
            showIcon
            title="上传失败"
            description={error}
            styles={{ root: { borderRadius: 8 } }}
          />
        )}
        <Form form={form} layout="vertical" clearOnDestroy>
          <Form.Item label="新版本名称" name="name" rules={[{ required: true, message: "请输入版本名称" }]}>
            <Input disabled={busy} placeholder={`例如：${kind}-20260721`} />
          </Form.Item>
          <Upload.Dragger
            className="input-data-uploader"
            disabled={busy}
            accept=".xls,.xlsx"
            maxCount={1}
            multiple={false}
            beforeUpload={() => false}
            fileList={files}
            onChange={onFileChange}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">拖放 Excel 到这里，或点击选择</p>
            <p className="ant-upload-hint">支持 .xls、.xlsx；选择后不会立即生效</p>
          </Upload.Dragger>
          <Button
            className="input-data-upload-submit"
            block
            type="primary"
            icon={<UploadOutlined />}
            aria-label="校验并启用新版本"
            aria-busy={uploading}
            disabled={busy}
            loading={uploading}
            onClick={() => void onSubmit()}
          >
            校验并启用新版本
          </Button>
        </Form>
        <Typography.Paragraph className="input-data-upload-impact" type="secondary">
          仅用于新批次；已有批次不变。
        </Typography.Paragraph>
      </div>
    </Drawer>
  );
}
