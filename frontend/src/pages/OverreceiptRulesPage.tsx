import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message
} from "antd";
import {
  CheckCircleFilled,
  EditOutlined,
  LockOutlined,
  PlusOutlined,
  ReloadOutlined
} from "@ant-design/icons";

import { api } from "../api";
import {
  formatBeijingDate,
  formatBeijingTime
} from "../dateTime";
import type {
  OverreceiptRuleVersion,
  SelfOperatedOverreceiptRuleVersion
} from "../types";

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

type RuleScope = "delivery" | "self_operated";

type RenameRuleTarget =
  | { scope: "delivery"; rule: OverreceiptRuleVersion }
  | { scope: "self_operated"; rule: SelfOperatedOverreceiptRuleVersion };

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

function RuleLimits({ rule }: { rule: OverreceiptRuleVersion }) {
  return (
    <Space className="rule-limit-list" wrap>
      <Tag color="green">短尾 +{rule.short_tail_limit}</Tag>
      <Tag color="blue">中尾 +{rule.medium_tail_limit}</Tag>
      <Tag>长尾 +{rule.long_tail_limit}</Tag>
    </Space>
  );
}

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

function RuleScopeSwitcher({
  scope,
  activeDeliveryRuleName,
  activeSelfOperatedAllowance,
  onChange
}: {
  scope: RuleScope;
  activeDeliveryRuleName?: string;
  activeSelfOperatedAllowance?: number;
  onChange: (scope: RuleScope) => void;
}) {
  return (
    <div className="overreceipt-scope-switcher" aria-label="超收规则范围">
      <button
        type="button"
        className={scope === "delivery" ? "is-active" : ""}
        aria-pressed={scope === "delivery"}
        onClick={() => onChange("delivery")}
      >
        <span className="overreceipt-scope-copy">
          <strong>交货超收</strong>
        </span>
        <span className={`overreceipt-scope-badge ${activeDeliveryRuleName ? "" : "is-disabled"}`}>
          {activeDeliveryRuleName ? `当前版本 ${activeDeliveryRuleName}` : "未启用"}
        </span>
      </button>
      <button
        type="button"
        className={scope === "self_operated" ? "is-active" : ""}
        aria-pressed={scope === "self_operated"}
        onClick={() => onChange("self_operated")}
      >
        <span className="overreceipt-scope-copy">
          <strong>自营仓入库</strong>
        </span>
        <span className={`overreceipt-scope-badge ${activeSelfOperatedAllowance !== undefined ? "" : "is-disabled"}`}>
          {activeSelfOperatedAllowance !== undefined
            ? `每键 +${activeSelfOperatedAllowance} 件`
            : "未启用"}
        </span>
      </button>
    </div>
  );
}

function CurrentSelfOperatedRule({
  rule,
  loading,
  onPublish,
  onRename
}: {
  rule?: SelfOperatedOverreceiptRuleVersion;
  loading: boolean;
  onPublish: () => void;
  onRename: (rule: SelfOperatedOverreceiptRuleVersion) => void;
}) {
  return (
    <Card className="section-card overreceipt-current-card" loading={loading}>
      <div className="overreceipt-current-heading">
        <div>
          <Typography.Text className="overreceipt-eyebrow">当前启用规则</Typography.Text>
          {rule ? (
            <div className="overreceipt-current-title">
              <Typography.Title level={4}>{rule.name}</Typography.Title>
              <Tag color="success" icon={<CheckCircleFilled />}>用于新批次</Tag>
            </div>
          ) : (
            <Typography.Title level={4}>尚未启用自营仓超收规则</Typography.Title>
          )}
        </div>
        <Space>
          {rule ? (
            <Button
              icon={<EditOutlined />}
              aria-label={`重命名 ${rule.name}`}
              onClick={() => onRename(rule)}
            >
              重命名
            </Button>
          ) : null}
          <Button type="primary" icon={<PlusOutlined />} onClick={onPublish}>
            发布新版本
          </Button>
        </Space>
      </div>
      {rule ? (
        <div className="overreceipt-metric-grid">
          <div className="overreceipt-metric is-accent">
            <span>超收额度</span>
            <strong>+{rule.allowance} 件</strong>
            <small>每个匹配键</small>
          </div>
          <div className="overreceipt-metric">
            <span>额度共享范围</span>
            <strong>供应商 + SKU + 完整站点</strong>
            <small>同一批次共用额度</small>
          </div>
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="新建批次允许超收数量为 0" />
      )}
    </Card>
  );
}

function CurrentDeliveryRule({
  rule,
  loading,
  onPublish,
  onRename
}: {
  rule?: OverreceiptRuleVersion;
  loading: boolean;
  onPublish: () => void;
  onRename: (rule: OverreceiptRuleVersion) => void;
}) {
  return (
    <Card className="section-card overreceipt-current-card" loading={loading}>
      <div className="overreceipt-current-heading">
        <div>
          <Typography.Text className="overreceipt-eyebrow">当前启用规则</Typography.Text>
          {rule ? (
            <div className="overreceipt-current-title">
              <Typography.Title level={4}>{rule.name}</Typography.Title>
              <Tag color="success" icon={<CheckCircleFilled />}>用于新批次</Tag>
            </div>
          ) : (
            <Typography.Title level={4}>尚未启用普通交货超收规则</Typography.Title>
          )}
        </div>
        <Space>
          {rule ? (
            <Button
              icon={<EditOutlined />}
              aria-label={`重命名 ${rule.name}`}
              onClick={() => onRename(rule)}
            >
              重命名
            </Button>
          ) : null}
          <Button type="primary" icon={<PlusOutlined />} onClick={onPublish}>
            发布新版本
          </Button>
        </Space>
      </div>
      {rule ? (
        <div className="overreceipt-metric-grid">
          <div className="overreceipt-metric is-accent">
            <span>规模定位额度</span>
            <RuleLimits rule={rule} />
            <small>分别控制短尾、中尾和长尾</small>
          </div>
          <div className="overreceipt-metric">
            <span>允许超收仓库</span>
            <strong>
              {rule.allowed_warehouses.length
                ? rule.allowed_warehouses.join("、")
                : "未开放任何仓库"}
            </strong>
            <small>目的仓名称必须精确匹配</small>
          </div>
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="新批次不会自动超收" />
      )}
    </Card>
  );
}

function HistoryCard({
  scope,
  rules,
  selfOperatedRules,
  loading,
  activatingId,
  selfOperatedActivatingId,
  onActivate,
  onActivateSelfOperated,
  onRename
}: {
  scope: RuleScope;
  rules: OverreceiptRuleVersion[];
  selfOperatedRules: SelfOperatedOverreceiptRuleVersion[];
  loading: boolean;
  activatingId?: number;
  selfOperatedActivatingId?: number;
  onActivate: (rule: OverreceiptRuleVersion) => void;
  onActivateSelfOperated: (rule: SelfOperatedOverreceiptRuleVersion) => void;
  onRename: (target: RenameRuleTarget) => void;
}) {
  const isSelfOperated = scope === "self_operated";
  const historicalRules = rules.filter((rule) => !rule.active);
  const historicalSelfOperatedRules = selfOperatedRules.filter((rule) => !rule.active);
  const count = isSelfOperated ? historicalSelfOperatedRules.length : historicalRules.length;
  const emptyText = (
    <div className="overreceipt-history-empty">
      <strong>暂无历史版本</strong>
      <span>发布新版本后，原版本会移到这里。</span>
    </div>
  );

  return (
    <Card
      className="section-card overreceipt-history-card"
      title={(
        <div className="overreceipt-history-heading">
          <strong>历史版本</strong>
          <small>可重新启用于新批次。</small>
        </div>
      )}
      extra={<Typography.Text type="secondary">{count} 个历史版本</Typography.Text>}
    >
      {isSelfOperated ? (loading || historicalSelfOperatedRules.length > 0 ? (
        <Table<SelfOperatedOverreceiptRuleVersion>
          className="overreceipt-history-table"
          rowKey="id"
          loading={loading}
          dataSource={historicalSelfOperatedRules}
          pagination={false}
          locale={{ emptyText }}
          tableLayout="fixed"
          components={{
            table: (props) => <table {...props} aria-label="自营仓超收规则历史版本" />
          }}
          columns={[
            {
              title: "版本",
              dataIndex: "name",
              render: (name: string) => <Typography.Text strong>{name}</Typography.Text>
            },
            {
              title: "允许超收",
              dataIndex: "allowance",
              width: 118,
              render: (value: number) => <strong className="overreceipt-allowance-value">+{value} 件</strong>
            },
            {
              title: "共享范围",
              width: 250,
              render: () => (
                <span className="overreceipt-table-stack">
                  供应商 + SKU + 完整站点
                  <small>批次内共享</small>
                </span>
              )
            },
            {
              title: "发布人",
              dataIndex: "created_by",
              width: 100,
              render: (value: number) => `用户 #${value}`
            },
            {
              title: "发布时间",
              dataIndex: "created_at",
              width: 150,
              render: (value: string) => (
                <span className="overreceipt-published-at">
                  {formatBeijingDate(value)}
                  <small>{formatBeijingTime(value)}</small>
                </span>
              )
            },
            {
              title: "操作",
              width: 174,
              render: (_, rule) => (
                <Space size={0}>
                  <Button
                    type="link"
                    aria-label={`重命名 ${rule.name}`}
                    onClick={() => onRename({ scope: "self_operated", rule })}
                  >
                    重命名
                  </Button>
                  <Button
                    type="link"
                    aria-label={`重新启用 ${rule.name}`}
                    loading={selfOperatedActivatingId === rule.id}
                    onClick={() => onActivateSelfOperated(rule)}
                  >
                    重新启用
                  </Button>
                </Space>
              )
            }
          ]}
        />
      ) : emptyText) : (loading || historicalRules.length > 0 ? (
        <Table<OverreceiptRuleVersion>
          className="overreceipt-history-table"
          rowKey="id"
          loading={loading}
          dataSource={historicalRules}
          pagination={false}
          locale={{ emptyText }}
          tableLayout="fixed"
          components={{
            table: (props) => <table {...props} aria-label="超收规则不可变版本" />
          }}
          columns={[
            {
              title: "版本",
              dataIndex: "name",
              width: 190,
              render: (name: string) => <Typography.Text strong>{name}</Typography.Text>
            },
            {
              title: "额度",
              width: 200,
              render: (_, rule) => <RuleLimits rule={rule} />
            },
            {
              title: "允许仓库",
              render: (_, rule) => rule.allowed_warehouses.length
                ? rule.allowed_warehouses.join("、")
                : <Typography.Text type="secondary">未开放任何仓库</Typography.Text>
            },
            {
              title: "发布人",
              dataIndex: "created_by",
              width: 100,
              render: (value: number) => `用户 #${value}`
            },
            {
              title: "发布时间",
              dataIndex: "created_at",
              width: 150,
              render: (value: string) => (
                <span className="overreceipt-published-at">
                  {formatBeijingDate(value)}
                  <small>{formatBeijingTime(value)}</small>
                </span>
              )
            },
            {
              title: "操作",
              width: 174,
              render: (_, rule) => (
                <Space size={0}>
                  <Button
                    type="link"
                    aria-label={`重命名 ${rule.name}`}
                    onClick={() => onRename({ scope: "delivery", rule })}
                  >
                    重命名
                  </Button>
                  <Button
                    type="link"
                    aria-label={`重新启用 ${rule.name}`}
                    loading={activatingId === rule.id}
                    onClick={() => onActivate(rule)}
                  >
                    重新启用
                  </Button>
                </Space>
              )
            }
          ]}
        />
      ) : emptyText)}
    </Card>
  );
}

export default function OverreceiptRulesPage({ active = true }: { active?: boolean }) {
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

  const load = useCallback(async (background = false) => {
    if (!background) setLoading(true);
    setError(null);
    try {
      const [ruleRows, selfOperatedRuleRows] = await Promise.all([
        api<OverreceiptRuleVersion[]>("/api/overreceipt-rule-versions"),
        api<SelfOperatedOverreceiptRuleVersion[]>("/api/self-operated-overreceipt-rule-versions")
      ]);
      setRules(ruleRows);
      setSelfOperatedRules(selfOperatedRuleRows);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "读取超收规则失败");
    } finally {
      loadedRef.current = true;
      if (!background) setLoading(false);
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
      message.error(loadError instanceof Error ? loadError.message : "读取仓库选项失败");
    } finally {
      setWarehousesLoading(false);
    }
  }, [warehousesLoaded, warehousesLoading]);

  useEffect(() => {
    if (!loadedRef.current || active) void load(loadedRef.current);
  }, [active, load]);

  const activeRule = useMemo(() => rules.find((rule) => rule.active), [rules]);
  const activeSelfOperatedRule = useMemo(
    () => selfOperatedRules.find((rule) => rule.active),
    [selfOperatedRules]
  );

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
        const renamed = await api<OverreceiptRuleVersion>(
          `/api/overreceipt-rule-versions/${target.rule.id}/name`,
          { method: "PUT", body: JSON.stringify({ name }) }
        );
        setRules((current) => current.map((rule) => (
          rule.id === renamed.id ? renamed : rule
        )));
      } else {
        const renamed = await api<SelfOperatedOverreceiptRuleVersion>(
          `/api/self-operated-overreceipt-rule-versions/${target.rule.id}/name`,
          { method: "PUT", body: JSON.stringify({ name }) }
        );
        setSelfOperatedRules((current) => current.map((rule) => (
          rule.id === renamed.id ? renamed : rule
        )));
      }
      message.success("版本名称已更新");
      closeRename();
    } catch (renameError) {
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
      message.success("超收规则已发布，将用于新批次");
      form.resetFields();
      setPublishScope(undefined);
      await load();
    } catch (publishError) {
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
          <Typography.Text type="secondary">
            参数发布后不可修改；新版本仅用于新批次。
          </Typography.Text>
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
      await api<SelfOperatedOverreceiptRuleVersion>(
        "/api/self-operated-overreceipt-rule-versions",
        { method: "POST", body: JSON.stringify(values) }
      );
      message.success("自营仓超收规则已发布，将用于新批次");
      selfOperatedForm.resetFields();
      setPublishScope(undefined);
      await load();
    } catch (publishError) {
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
          <Typography.Text>
            每个“供应商 + SKU + 完整站点”在新批次内共享 {values.allowance} 件超收额度。
          </Typography.Text>
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
      await api<OverreceiptRuleVersion>(
        `/api/overreceipt-rule-versions/${rule.id}/activate`,
        { method: "POST" }
      );
      message.success(`已重新启用 ${rule.name}，仅影响新建批次`);
      await load();
    } catch (activateError) {
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
      message.success(`已重新启用 ${rule.name}，仅影响新建自营仓批次`);
      await load();
    } catch (activateError) {
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
          <Typography.Text type="secondary">
            设置新批次的超收额度和适用仓库。
          </Typography.Text>
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

      <HistoryCard
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
        <Form<RenameRuleForm>
          form={renameForm}
          layout="vertical"
          onFinish={(values) => void renameRule(values)}
        >
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
        footer={(
          <div className="overreceipt-drawer-actions">
            <Button onClick={() => setPublishScope(undefined)}>取消</Button>
            <Button
              type="primary"
              htmlType="submit"
              form={drawerIsSelfOperated
                ? "self-operated-overreceipt-form"
                : "delivery-overreceipt-form"}
              loading={drawerIsSelfOperated ? selfOperatedSubmitting : submitting}
            >
              确认
            </Button>
          </div>
        )}
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
              extra={activeSelfOperatedRule
                ? `当前启用版本为每键 +${activeSelfOperatedRule.allowance} 件`
                : "当前尚未启用自营仓超收规则"}
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
