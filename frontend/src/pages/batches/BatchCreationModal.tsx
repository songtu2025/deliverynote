import { Alert, Button, Form, Input, Modal, Typography, Upload } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import type { InputVersion, OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "../../types";
import type { BatchWorkflow } from "./batchWorkspace";
import type { useBatchCreation } from "./useBatchCreation";

type Props = {
  workflow: BatchWorkflow;
  creation: ReturnType<typeof useBatchCreation>;
  activeVersions: Record<string, InputVersion>;
  versionKinds: Array<{ value: string; label: string }>;
  activeSelfOperatedRule?: SelfOperatedOverreceiptRuleVersion;
  activeOverreceiptRule?: OverreceiptRuleVersion;
};
export default function BatchCreationModal({
  workflow,
  creation,
  activeVersions,
  versionKinds,
  activeSelfOperatedRule,
  activeOverreceiptRule
}: Props) {
  const { form, creating, sourceFiles, deliveryFiles, create, closeCreate, selectSourceFiles, selectDeliveryFiles } =
    creation;
  return (
    <Modal
      className={workflow === "delivery" ? "delivery-batch-creation-modal" : undefined}
      title={workflow === "self_operated_inbound" ? "新建自营仓入库批次" : "新建交货批次"}
      open={creating}
      onCancel={closeCreate}
      onOk={() => void create()}
      okText={workflow === "self_operated_inbound" ? "创建批次" : "创建并上传文件"}
      cancelText="取消"
      okButtonProps={{
        disabled: workflow === "self_operated_inbound" ? !sourceFiles.length : !deliveryFiles.length
      }}
    >
      <Form name={`batch-create-${workflow}`} form={form} layout="vertical">
        <Form.Item
          label="批次名称"
          name="name"
          rules={[{ required: true, message: "请输入批次名称" }]}
          extra={workflow === "delivery" ? "默认包含北京时间，精确到秒；可按需修改。" : undefined}
        >
          <Input
            placeholder={
              workflow === "self_operated_inbound"
                ? "例如：2026-08-21 自营仓入库批次"
                : "例如：2026-10-08 交货批次 14:26:35"
            }
          />
        </Form.Item>
        {workflow === "delivery" && (
          <>
            <Form.Item label="交货文件" required>
              <Upload
                accept=".xls,.xlsx"
                multiple
                beforeUpload={() => false}
                fileList={deliveryFiles}
                onChange={selectDeliveryFiles}
              >
                <Button icon={<UploadOutlined />}>选择交货文件</Button>
              </Upload>
            </Form.Item>
            <Typography.Text type="secondary">至少选择一份；校验通过后创建批次。</Typography.Text>
          </>
        )}
        {workflow === "self_operated_inbound" && (
          <>
            <Form.Item label="质检交货单" required>
              <Upload
                accept=".xls,.xlsx"
                multiple
                beforeUpload={() => false}
                fileList={sourceFiles}
                onChange={selectSourceFiles}
              >
                <Button icon={<UploadOutlined />}>选择质检交货单</Button>
              </Upload>
            </Form.Item>
            <Typography.Text type="secondary">
              可同时选择多份；系统将按列表顺序共享扣减待入库余额和超收额度。
            </Typography.Text>
            <Alert
              className="self-operated-version-lock"
              type="info"
              showIcon
              title="锁定待入库数据版本"
              description={
                activeVersions.self_operated_inbound
                  ? `本批次将使用：${activeVersions.self_operated_inbound.name}`
                  : "请先同步并启用待入库 API 数据"
              }
            />
          </>
        )}
      </Form>
      <div className="locked-version-preview">
        <Typography.Text strong>锁定版本</Typography.Text>
        {versionKinds.map((kind) => (
          <div key={kind.value}>
            <span>{kind.label}</span>
            <strong>{activeVersions[kind.value]?.name ?? "未启用"}</strong>
          </div>
        ))}
        <div>
          <span>超收规则</span>
          <strong>
            {workflow === "self_operated_inbound"
              ? (activeSelfOperatedRule?.name ?? "未启用（允许超收 0 件）")
              : (activeOverreceiptRule?.name ?? "未启用（不自动超收）")}
          </strong>
        </div>
      </div>
    </Modal>
  );
}
