import { Alert, Button, Drawer, Form, Input, InputNumber, Select, Typography } from "antd";
import type { FormInstance } from "antd";
import type { SelfOperatedOverreceiptRuleVersion } from "../../types";
import type { RuleForm, RuleScope, SelfOperatedRuleForm } from "../../overreceiptRuleApi";

const DEFAULT_LIMITS = {
  short_tail_limit: 50,
  medium_tail_limit: 20,
  long_tail_limit: 10
};

const SELF_OPERATED_IMPACT_ITEMS = [
  ["匹配键", "供应商 + SKU + 完整站点"],
  ["额度共享", "额度按每个匹配键共享"],
  ["分配位置", "规则内超收挂到最后一个 PO 单"],
  ["业务边界", "不会改变上游交货量或采购量"]
];

const DELIVERY_IMPACT_ITEMS = [
  ["共享维度", "供应商 + SKU + 完整站点"],
  ["定位判断", "短尾 / 中尾 / 长尾分别配置"],
  ["仓库范围", "只允许精确命中白名单的仓库"],
  ["业务边界", "不会改变上游交货量或采购量"]
];

function ImpactPreview({ items }: { items: string[][] }) {
  return (
    <div className="overreceipt-impact-preview">
      {items.map(([label, value]) => (
        <div className="overreceipt-impact-row" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

export function RulePublishDrawer({
  publishScope,
  setPublishScope,
  form,
  selfOperatedForm,
  submitting,
  selfOperatedSubmitting,
  activeSelfOperatedRule,
  warehouses,
  warehousesLoading,
  loadWarehouses,
  confirmPublish,
  confirmSelfOperatedPublish
}: {
  publishScope?: RuleScope;
  setPublishScope: (scope?: RuleScope) => void;
  form: FormInstance<RuleForm>;
  selfOperatedForm: FormInstance<SelfOperatedRuleForm>;
  submitting: boolean;
  selfOperatedSubmitting: boolean;
  activeSelfOperatedRule?: SelfOperatedOverreceiptRuleVersion;
  warehouses: string[];
  warehousesLoading: boolean;
  loadWarehouses: () => Promise<void>;
  confirmPublish: (values: RuleForm) => Promise<void>;
  confirmSelfOperatedPublish: (values: SelfOperatedRuleForm) => Promise<void>;
}) {
  const drawerIsSelfOperated = publishScope === "self_operated";
  return (
    <Drawer
      className="overreceipt-publish-drawer"
      title={drawerIsSelfOperated ? "发布自营仓新版本" : "发布普通交货新版本"}
      open={publishScope !== undefined}
      size={460}
      onClose={() => setPublishScope(undefined)}
      footer={
        <div className="overreceipt-drawer-actions">
          <Button onClick={() => setPublishScope(undefined)}>取消</Button>
          <Button
            type="primary"
            htmlType="submit"
            form={drawerIsSelfOperated ? "self-operated-overreceipt-form" : "delivery-overreceipt-form"}
            loading={drawerIsSelfOperated ? selfOperatedSubmitting : submitting}
          >
            确认
          </Button>
        </div>
      }
    >
      <Alert
        className="overreceipt-drawer-notice"
        type="info"
        showIcon
        title="规则参数发布后不可修改"
        description="版本名称可以调整；新版本仅用于新批次。"
      />

      {drawerIsSelfOperated ? (
        <Form<SelfOperatedRuleForm>
          key="self_operated"
          id="self-operated-overreceipt-form"
          form={selfOperatedForm}
          layout="vertical"
          requiredMark
          initialValues={{ allowance: 5 }}
          onFinish={(values) => void confirmSelfOperatedPublish(values)}
        >
          <Form.Item
            label="规则版本名称"
            name="name"
            rules={[{ required: true, whitespace: true, message: "请输入规则版本名称" }]}
          >
            <Input placeholder="例如：2026-08 自营仓超收规则" />
          </Form.Item>
          <Form.Item
            label="每个匹配键允许超收"
            name="allowance"
            extra={
              activeSelfOperatedRule
                ? `当前启用版本为每键 +${activeSelfOperatedRule.allowance} 件`
                : "当前尚未启用自营仓超收规则"
            }
            rules={[{ required: true, message: "请输入允许超收数量" }]}
          >
            <InputNumber min={0} precision={0} suffix="件" />
          </Form.Item>
          <Typography.Title className="overreceipt-impact-title" level={5}>
            发布影响预览
          </Typography.Title>
          <ImpactPreview items={SELF_OPERATED_IMPACT_ITEMS} />
        </Form>
      ) : (
        <Form<RuleForm>
          key="delivery"
          id="delivery-overreceipt-form"
          form={form}
          layout="vertical"
          requiredMark
          initialValues={{ ...DEFAULT_LIMITS, allowed_warehouses: [] }}
          onFinish={(values) => void confirmPublish(values)}
        >
          <Form.Item
            label="规则版本名称"
            name="name"
            rules={[{ required: true, whitespace: true, message: "请输入规则版本名称" }]}
          >
            <Input placeholder="例如：2026-08 普通交货超收规则" />
          </Form.Item>
          <div className="overreceipt-limit-grid">
            <Form.Item label="短尾允许超收" name="short_tail_limit" rules={[{ required: true }]}>
              <InputNumber min={0} precision={0} suffix="件" />
            </Form.Item>
            <Form.Item label="中尾允许超收" name="medium_tail_limit" rules={[{ required: true }]}>
              <InputNumber min={0} precision={0} suffix="件" />
            </Form.Item>
            <Form.Item label="长尾允许超收" name="long_tail_limit" rules={[{ required: true }]}>
              <InputNumber min={0} precision={0} suffix="件" />
            </Form.Item>
          </div>
          <Form.Item
            label="允许超收仓库"
            name="allowed_warehouses"
            extra="仓库留空表示不允许自动超收；通常不要选择供应商成品本地仓。"
          >
            <Select
              mode="multiple"
              allowClear
              loading={warehousesLoading}
              placeholder="选择允许超收的目的仓"
              options={warehouses.map((warehouse) => ({ value: warehouse, label: warehouse }))}
              onOpenChange={(open) => {
                if (open) void loadWarehouses();
              }}
            />
          </Form.Item>
          <Typography.Title className="overreceipt-impact-title" level={5}>
            发布影响预览
          </Typography.Title>
          <ImpactPreview items={DELIVERY_IMPACT_ITEMS} />
        </Form>
      )}
    </Drawer>
  );
}
