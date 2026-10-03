import { useState } from "react";
import { Alert, Button, Typography } from "antd";
import { LockOutlined, ReloadOutlined } from "@ant-design/icons";
import type { RuleScope } from "../overreceiptRuleApi";
import { RulePublishDrawer } from "./overreceipt-rules/RulePublishDrawer";
import { RuleRenameModal } from "./overreceipt-rules/RuleRenameModal";
import { RuleScopeSwitcher, CurrentSelfOperatedRule, CurrentDeliveryRule } from "./overreceipt-rules/RuleOverview";
import { RuleHistory } from "./overreceipt-rules/RuleHistory";
import { useRulesData } from "./overreceipt-rules/useRulesData";
import { useRuleMutations } from "./overreceipt-rules/useRuleMutations";

export default function OverreceiptRulesPage({ active = true }: { active?: boolean }) {
  const [scope, setScope] = useState<RuleScope>("self_operated");
  const data = useRulesData(active);
  const { rules, selfOperatedRules, warehouses, loading, warehousesLoading, error, load, loadWarehouses, refresh } =
    data;
  const {
    publishScope,
    setPublishScope,
    renameTarget,
    renaming,
    submitting,
    selfOperatedSubmitting,
    activatingId,
    selfOperatedActivatingId,
    form,
    selfOperatedForm,
    renameForm,
    modalContextHolder,
    openRename,
    closeRename,
    renameRule,
    confirmPublish,
    confirmSelfOperatedPublish,
    activate
  } = useRuleMutations(data, active);
  const activeRule = rules.find((rule) => rule.active);
  const activeSelfOperatedRule = selfOperatedRules.find((rule) => rule.active);

  return (
    <div className="page-shell overreceipt-page">
      {modalContextHolder}
      <div className="page-heading overreceipt-page-heading">
        <div>
          <Typography.Title level={2}>超收规则</Typography.Title>
          <Typography.Text type="secondary">设置新批次的超收额度和适用仓库。</Typography.Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
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
        onActivate={(rule) => void activate({ scope: "delivery", rule })}
        onActivateSelfOperated={(rule) => void activate({ scope: "self_operated", rule })}
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
