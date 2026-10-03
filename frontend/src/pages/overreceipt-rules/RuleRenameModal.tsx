import { Alert, Form, Input, Modal } from "antd";
import type { FormInstance } from "antd";
import type { RenameRuleForm, RenameRuleTarget } from "./ruleTypes";

export function RuleRenameModal({
  renameTarget,
  renameForm,
  renaming,
  closeRename,
  renameRule
}: {
  renameTarget?: RenameRuleTarget;
  renameForm: FormInstance<RenameRuleForm>;
  renaming: boolean;
  closeRename: () => void;
  renameRule: (values: RenameRuleForm) => Promise<void>;
}) {
  return (
    <Modal
      title="修改版本名称"
      open={renameTarget !== undefined}
      okText="保存"
      cancelText="取消"
      confirmLoading={renaming}
      onOk={() => renameForm.submit()}
      onCancel={closeRename}
      destroyOnHidden
    >
      <Alert className="overreceipt-drawer-notice" type="info" showIcon title="只修改名称，不影响规则参数或历史批次" />
      <Form<RenameRuleForm> form={renameForm} layout="vertical" onFinish={(values) => void renameRule(values)}>
        <Form.Item
          label="版本名称"
          name="name"
          rules={[{ required: true, whitespace: true, message: "请输入版本名称" }]}
        >
          <Input maxLength={200} autoFocus />
        </Form.Item>
      </Form>
    </Modal>
  );
}
