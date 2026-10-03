import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, App as AntApp, Button, Form, Modal, Typography } from "antd";
import { LockOutlined, ReloadOutlined } from "@ant-design/icons";

import { RulePublishDrawer } from "./overreceipt-rules/RulePublishDrawer";
import { RuleRenameModal } from "./overreceipt-rules/RuleRenameModal";
import { DeliveryPublishSummary, SelfOperatedPublishSummary } from "./overreceipt-rules/RulePublishConfirmation";

import { api, ApiError } from "../api";
import { RuleScopeSwitcher, CurrentSelfOperatedRule, CurrentDeliveryRule } from "./overreceipt-rules/RuleOverview";
import { RuleHistory } from "./overreceipt-rules/RuleHistory";
import type {
  RuleForm,
  SelfOperatedRuleForm,
  RenameRuleForm,
  RenameRuleTarget,
  RuleScope
} from "./overreceipt-rules/ruleTypes";
import type { OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "../types";

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
      content: <DeliveryPublishSummary values={values} />,
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
      content: <SelfOperatedPublishSummary values={values} />,
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

      <RuleRenameModal
        renameTarget={renameTarget}
        renameForm={renameForm}
        renaming={renaming}
        closeRename={closeRename}
        renameRule={renameRule}
      />

      <RulePublishDrawer
        publishScope={publishScope}
        setPublishScope={setPublishScope}
        form={form}
        selfOperatedForm={selfOperatedForm}
        submitting={submitting}
        selfOperatedSubmitting={selfOperatedSubmitting}
        activeSelfOperatedRule={activeSelfOperatedRule}
        warehouses={warehouses}
        warehousesLoading={warehousesLoading}
        loadWarehouses={loadWarehouses}
        confirmPublish={confirmPublish}
        confirmSelfOperatedPublish={confirmSelfOperatedPublish}
      />
    </div>
  );
}
