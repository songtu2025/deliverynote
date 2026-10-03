import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Tag,
  Typography
} from "antd";
import { LockOutlined, ReloadOutlined } from "@ant-design/icons";

import { api, ApiError } from "../api";
import { RuleScopeSwitcher, CurrentSelfOperatedRule, CurrentDeliveryRule } from "./overreceipt-rules/RuleOverview";
import { RuleHistory } from "./overreceipt-rules/RuleHistory";
import type { RenameRuleTarget, RuleScope } from "./overreceipt-rules/ruleTypes";
import type { OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "../types";

type RuleForm = {
  name: string;
  short_tail_limit: number;
  medium_tail_limit: number;
  long_tail_limit: number;
  allowed_warehouses: string[];
};

type SelfOperatedRuleForm = {
  name: string;
  allowance: number;
};

type RenameRuleForm = {
  name: string;
};

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

export default function OverreceiptRulesPage({ active = true }: { active?: boolean }) {
  const { message } = AntApp.useApp();
  const [scope, setScope] = useState<RuleScope>("self_operated");
  const [rules, setRules] = useState<OverreceiptRuleVersion[]>([]);
  const [selfOperatedRules, setSelfOperatedRules] = useState<SelfOperatedOverreceiptRuleVersion[]>([]);
  const [warehouses, setWarehouses] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [warehousesLoading, setWarehousesLoading] = useState(false);
  const [warehousesLoaded, setWarehousesLoaded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [activatingId, setActivatingId] = useState<number>();
  const [selfOperatedSubmitting, setSelfOperatedSubmitting] = useState(false);
  const [selfOperatedActivatingId, setSelfOperatedActivatingId] = useState<number>();
  const [publishScope, setPublishScope] = useState<RuleScope>();
  const [renameTarget, setRenameTarget] = useState<RenameRuleTarget>();
  const [renaming, setRenaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form] = Form.useForm<RuleForm>();
  const [selfOperatedForm] = Form.useForm<SelfOperatedRuleForm>();
  const [renameForm] = Form.useForm<RenameRuleForm>();
  const [modal, modalContextHolder] = Modal.useModal();
  const loadedRef = useRef(false);
  const loadRequestRef = useRef(0);

  const load = useCallback(async (background = false, afterWrite = false) => {
    const requestId = ++loadRequestRef.current;
    if (!background) setLoading(true);
    setError(null);
    try {
      const [ruleRows, selfOperatedRuleRows] = await Promise.all([
        api<OverreceiptRuleVersion[]>("/api/overreceipt-rule-versions"),
        api<SelfOperatedOverreceiptRuleVersion[]>("/api/self-operated-overreceipt-rule-versions")
      ]);
      if (requestId !== loadRequestRef.current) return false;
      setRules(ruleRows);
      setSelfOperatedRules(selfOperatedRuleRows);
      return true;
    } catch (loadError) {
      if (loadError instanceof ApiError && loadError.status === 401) {
        if (afterWrite) throw loadError;
        return false;
      }
      if (requestId === loadRequestRef.current) {
        const detail = loadError instanceof Error ? loadError.message : "读取超收规则失败";
        setError(`${afterWrite ? "变更已保存，但读取超收规则失败：" : ""}${detail}`);
      }
      return false;
    } finally {
      if (requestId === loadRequestRef.current) {
        loadedRef.current = true;
        setLoading(false);
      }
    }
  }, []);

  const loadWarehouses = useCallback(async () => {
    if (warehousesLoaded || warehousesLoading) return;
    setWarehousesLoading(true);
    try {
      const rows = await api<string[]>("/api/overreceipt-rule-versions/warehouses");
      setWarehouses(rows);
      setWarehousesLoaded(true);
    } catch (loadError) {
      if (loadError instanceof ApiError && loadError.status === 401) return;
      message.error(loadError instanceof Error ? loadError.message : "读取仓库选项失败");
    } finally {
      setWarehousesLoading(false);
    }
  }, [message, warehousesLoaded, warehousesLoading]);

  useEffect(() => {
    if (!loadedRef.current || active) void load(loadedRef.current);
    return () => {
      loadRequestRef.current += 1;
    };
  }, [active, load]);

  const activeRule = useMemo(() => rules.find((rule) => rule.active), [rules]);
  const activeSelfOperatedRule = useMemo(() => selfOperatedRules.find((rule) => rule.active), [selfOperatedRules]);

  const openRename = (target: RenameRuleTarget) => {
    setRenameTarget(target);
    renameForm.setFieldsValue({ name: target.rule.name });
  };

  const closeRename = () => {
    setRenameTarget(undefined);
    renameForm.resetFields();
  };

  const renameRule = async (values: RenameRuleForm) => {
    if (!renameTarget) return;
    const target = renameTarget;
    const name = values.name.trim();
    setRenaming(true);
    try {
      if (target.scope === "delivery") {
        const renamed = await api<OverreceiptRuleVersion>(`/api/overreceipt-rule-versions/${target.rule.id}/name`, {
          method: "PUT",
          body: JSON.stringify({ name })
        });
        setRules((current) => current.map((rule) => (rule.id === renamed.id ? renamed : rule)));
      } else {
        const renamed = await api<SelfOperatedOverreceiptRuleVersion>(
          `/api/self-operated-overreceipt-rule-versions/${target.rule.id}/name`,
          { method: "PUT", body: JSON.stringify({ name }) }
        );
        setSelfOperatedRules((current) => current.map((rule) => (rule.id === renamed.id ? renamed : rule)));
      }
      message.success("版本名称已更新");
      closeRename();
    } catch (renameError) {
      if (renameError instanceof ApiError && renameError.status === 401) return;
      message.error(renameError instanceof Error ? renameError.message : "名称修改失败");
    } finally {
      setRenaming(false);
    }
  };

  const publish = async (values: RuleForm) => {
    setSubmitting(true);
    try {
      await api<OverreceiptRuleVersion>("/api/overreceipt-rule-versions", {
        method: "POST",
        body: JSON.stringify(values)
      });
      form.resetFields();
      setPublishScope(undefined);
      if (await load(false, true)) message.success("超收规则已发布，将用于新批次");
    } catch (publishError) {
      if (publishError instanceof ApiError && publishError.status === 401) return;
      message.error(publishError instanceof Error ? publishError.message : "发布失败");
      throw publishError;
    } finally {
      setSubmitting(false);
    }
  };

  const confirmPublish = async (values: RuleForm) => {
    await modal.confirm({
      title: "确认发布不可变版本？",
      content: (
        <div className="overreceipt-confirm-summary">
          <Typography.Text strong>{values.name}</Typography.Text>
          <Space wrap>
            <Tag color="green">短尾 +{values.short_tail_limit} 件</Tag>
            <Tag color="blue">中尾 +{values.medium_tail_limit} 件</Tag>
            <Tag>长尾 +{values.long_tail_limit} 件</Tag>
          </Space>
          <div className="overreceipt-confirm-warehouses">
            <Typography.Text type="secondary">允许超收仓库（精确匹配）</Typography.Text>
            {values.allowed_warehouses.length ? (
              <Space wrap>
                {values.allowed_warehouses.map((warehouse) => (
                  <Tag key={warehouse}>{warehouse}</Tag>
                ))}
              </Space>
            ) : (
              <Typography.Text type="warning">未开放任何仓库（不会自动超收）</Typography.Text>
            )}
          </div>
          <Typography.Text type="secondary">参数发布后不可修改；新版本仅用于新批次。</Typography.Text>
        </div>
      ),
      okText: "确认发布",
      cancelText: "返回修改",
      onOk: () => publish(values)
    });
  };

  const publishSelfOperated = async (values: SelfOperatedRuleForm) => {
    setSelfOperatedSubmitting(true);
    try {
      await api<SelfOperatedOverreceiptRuleVersion>("/api/self-operated-overreceipt-rule-versions", {
        method: "POST",
        body: JSON.stringify(values)
      });
      selfOperatedForm.resetFields();
      setPublishScope(undefined);
      if (await load(false, true)) message.success("自营仓超收规则已发布，将用于新批次");
    } catch (publishError) {
      if (publishError instanceof ApiError && publishError.status === 401) return;
      message.error(publishError instanceof Error ? publishError.message : "发布失败");
      throw publishError;
    } finally {
      setSelfOperatedSubmitting(false);
    }
  };

  const confirmSelfOperatedPublish = async (values: SelfOperatedRuleForm) => {
    await modal.confirm({
      title: "确认发布自营仓超收规则？",
      content: (
        <div className="overreceipt-confirm-summary">
          <Typography.Text strong>{values.name}</Typography.Text>
          <Typography.Text>每个“供应商 + SKU + 完整站点”在新批次内共享 {values.allowance} 件超收额度。</Typography.Text>
          <Typography.Text type="secondary">
            规则内超收数量挂到最后一个 PO 单，且不会改变上游交货量或采购量。
          </Typography.Text>
        </div>
      ),
      okText: "确认发布",
      cancelText: "返回修改",
      onOk: () => publishSelfOperated(values)
    });
  };

  const activate = async (rule: OverreceiptRuleVersion) => {
    setActivatingId(rule.id);
    try {
      await api<OverreceiptRuleVersion>(`/api/overreceipt-rule-versions/${rule.id}/activate`, { method: "POST" });
      if (await load(false, true)) message.success(`已重新启用 ${rule.name}，仅影响新建批次`);
    } catch (activateError) {
      if (activateError instanceof ApiError && activateError.status === 401) return;
      message.error(activateError instanceof Error ? activateError.message : "启用失败");
    } finally {
      setActivatingId(undefined);
    }
  };

  const activateSelfOperated = async (rule: SelfOperatedOverreceiptRuleVersion) => {
    setSelfOperatedActivatingId(rule.id);
    try {
      await api<SelfOperatedOverreceiptRuleVersion>(
        `/api/self-operated-overreceipt-rule-versions/${rule.id}/activate`,
        { method: "POST" }
      );
      if (await load(false, true)) message.success(`已重新启用 ${rule.name}，仅影响新建自营仓批次`);
    } catch (activateError) {
      if (activateError instanceof ApiError && activateError.status === 401) return;
      message.error(activateError instanceof Error ? activateError.message : "启用失败");
    } finally {
      setSelfOperatedActivatingId(undefined);
    }
  };

  const drawerIsSelfOperated = publishScope === "self_operated";

  return (
    <div className="page-shell overreceipt-page">
      {modalContextHolder}
      <div className="page-heading overreceipt-page-heading">
        <div>
          <Typography.Title level={2}>超收规则</Typography.Title>
          <Typography.Text type="secondary">设置新批次的超收额度和适用仓库。</Typography.Text>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => {
            setWarehouses([]);
            setWarehousesLoaded(false);
            void load();
          }}
          loading={loading}
        >
          刷新
        </Button>
      </div>

      {error ? (
        <Alert
          className="section-card"
          type="error"
          showIcon
          title="超收规则读取失败"
          description={error}
          action={<Button onClick={() => void load()}>重试</Button>}
        />
      ) : null}

      <RuleScopeSwitcher
        scope={scope}
        activeDeliveryRuleName={activeRule?.name}
        activeSelfOperatedAllowance={activeSelfOperatedRule?.allowance}
        onChange={setScope}
      />

      <div className="overreceipt-effect-notice">
        <LockOutlined />
        <span>仅用于新批次；已有批次仍使用原版本。</span>
      </div>

      {scope === "self_operated" ? (
        <CurrentSelfOperatedRule
          rule={activeSelfOperatedRule}
          loading={loading}
          onPublish={() => setPublishScope("self_operated")}
          onRename={(rule) => openRename({ scope: "self_operated", rule })}
        />
      ) : (
        <CurrentDeliveryRule
          rule={activeRule}
          loading={loading}
          onPublish={() => setPublishScope("delivery")}
          onRename={(rule) => openRename({ scope: "delivery", rule })}
        />
      )}

      <RuleHistory
        scope={scope}
        rules={rules}
        selfOperatedRules={selfOperatedRules}
        loading={loading}
        activatingId={activatingId}
        selfOperatedActivatingId={selfOperatedActivatingId}
        onActivate={(rule) => void activate(rule)}
        onActivateSelfOperated={(rule) => void activateSelfOperated(rule)}
        onRename={openRename}
      />

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
        <Alert
          className="overreceipt-drawer-notice"
          type="info"
          showIcon
          title="只修改名称，不影响规则参数或历史批次"
        />
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
    </div>
  );
}
