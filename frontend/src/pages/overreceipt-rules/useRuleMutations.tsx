import { useEffect, useRef, useState } from "react";
import { App as AntApp, Form, Modal } from "antd";
import { ApiError } from "../../api";
import { activateOverreceiptRule, publishOverreceiptRule, renameOverreceiptRule } from "../../overreceiptRuleApi";
import type { RuleForm, RuleScope, SelfOperatedRuleForm } from "../../overreceiptRuleApi";
import type { RenameRuleForm, RenameRuleTarget } from "./ruleTypes";
import type { RulesData } from "./useRulesData";
import { DeliveryPublishSummary, SelfOperatedPublishSummary } from "./RulePublishConfirmation";

export function useRuleMutations(data: RulesData, active: boolean) {
  const { message } = AntApp.useApp();
  const [publishScope, setPublishScope] = useState<RuleScope>();
  const [renameTarget, setRenameTarget] = useState<RenameRuleTarget>();
  const [renaming, setRenaming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [selfOperatedSubmitting, setSelfOperatedSubmitting] = useState(false);
  const [activatingId, setActivatingId] = useState<number>();
  const [selfOperatedActivatingId, setSelfOperatedActivatingId] = useState<number>();
  const [form] = Form.useForm<RuleForm>();
  const [selfOperatedForm] = Form.useForm<SelfOperatedRuleForm>();
  const [renameForm] = Form.useForm<RenameRuleForm>();
  const [modal, modalContextHolder] = Modal.useModal();
  const confirmationRef = useRef<{ destroy: () => void } | null>(null);

  useEffect(() => {
    setSubmitting(false);
    setSelfOperatedSubmitting(false);
    setActivatingId(undefined);
    setSelfOperatedActivatingId(undefined);
    setRenaming(false);
    return () => {
      confirmationRef.current?.destroy();
    };
  }, [active]);

  const openRename = (target: RenameRuleTarget) => {
    setRenameTarget(target);
    renameForm.setFieldsValue({ name: target.rule.name });
  };
  const closeRename = () => {
    setRenameTarget(undefined);
    renameForm.resetFields();
  };

  const handleWriteError = (error: unknown, isCurrent: () => boolean, fallback: string, keepConfirmation = false) => {
    if (!isCurrent() || (error instanceof ApiError && error.status === 401)) return;
    message.error(error instanceof Error ? error.message : fallback);
    // 发布失败必须拒绝确认回调，保留原确认框供用户重试。
    if (keepConfirmation) throw error;
  };

  const renameRule = async (values: RenameRuleForm) => {
    if (!renameTarget) return;
    const target = renameTarget;
    const isCurrent = data.beginOperation();
    setRenaming(true);
    try {
      if (target.scope === "delivery") {
        const renamed = await renameOverreceiptRule(target.scope, target.rule.id, values.name.trim());
        if (!isCurrent()) return;
        data.setRules((current) => current.map((rule) => (rule.id === renamed.id ? renamed : rule)));
      } else {
        const renamed = await renameOverreceiptRule(target.scope, target.rule.id, values.name.trim());
        if (!isCurrent()) return;
        data.setSelfOperatedRules((current) => current.map((rule) => (rule.id === renamed.id ? renamed : rule)));
      }
      message.success("版本名称已更新");
      closeRename();
    } catch (error) {
      handleWriteError(error, isCurrent, "名称修改失败");
    } finally {
      if (isCurrent()) setRenaming(false);
    }
  };

  const publish = async (scope: RuleScope, values: RuleForm | SelfOperatedRuleForm) => {
    const isCurrent = data.beginOperation();
    const isDelivery = scope === "delivery";
    const setBusy = isDelivery ? setSubmitting : setSelfOperatedSubmitting;
    setBusy(true);
    try {
      await publishOverreceiptRule(scope, values);
      if (!isCurrent()) return;
      (isDelivery ? form : selfOperatedForm).resetFields();
      setPublishScope(undefined);
      if ((await data.load(false, true)) && isCurrent()) {
        message.success(isDelivery ? "超收规则已发布，将用于新批次" : "自营仓超收规则已发布，将用于新批次");
      }
    } catch (error) {
      handleWriteError(error, isCurrent, "发布失败", true);
    } finally {
      if (isCurrent()) setBusy(false);
    }
  };

  const confirmPublish = async (values: RuleForm) => {
    const confirmation = modal.confirm({
      title: "确认发布不可变版本？",
      content: <DeliveryPublishSummary values={values} />,
      okText: "确认发布",
      cancelText: "返回修改",
      onOk: () => publish("delivery", values)
    });
    confirmationRef.current = confirmation;
    await confirmation;
  };
  const confirmSelfOperatedPublish = async (values: SelfOperatedRuleForm) => {
    const confirmation = modal.confirm({
      title: "确认发布自营仓超收规则？",
      content: <SelfOperatedPublishSummary values={values} />,
      okText: "确认发布",
      cancelText: "返回修改",
      onOk: () => publish("self_operated", values)
    });
    confirmationRef.current = confirmation;
    await confirmation;
  };

  const activate = async (target: RenameRuleTarget) => {
    const isCurrent = data.beginOperation();
    const isDelivery = target.scope === "delivery";
    const setBusy = isDelivery ? setActivatingId : setSelfOperatedActivatingId;
    setBusy(target.rule.id);
    try {
      await activateOverreceiptRule(target.scope, target.rule.id);
      if (!isCurrent()) return;
      if ((await data.load(false, true)) && isCurrent()) {
        message.success(`已重新启用 ${target.rule.name}，仅影响新建${isDelivery ? "" : "自营仓"}批次`);
      }
    } catch (error) {
      handleWriteError(error, isCurrent, "启用失败");
    } finally {
      if (isCurrent()) setBusy(undefined);
    }
  };

  return {
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
  };
}
