import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message
} from "antd";
import { CheckCircleFilled, ReloadOutlined } from "@ant-design/icons";

import { api } from "../api";
import type { OverreceiptRuleVersion } from "../types";

type RuleForm = {
  name: string;
  short_tail_limit: number;
  medium_tail_limit: number;
  long_tail_limit: number;
  allowed_warehouses: string[];
};

const DEFAULT_LIMITS = {
  short_tail_limit: 50,
  medium_tail_limit: 20,
  long_tail_limit: 10
};

function RuleLimits({ rule }: { rule: OverreceiptRuleVersion }) {
  return (
    <Space wrap>
      <Tag color="green">短尾 +{rule.short_tail_limit}</Tag>
      <Tag color="blue">中尾 +{rule.medium_tail_limit}</Tag>
      <Tag>长尾 +{rule.long_tail_limit}</Tag>
    </Space>
  );
}

export default function OverreceiptRulesPage() {
  const [rules, setRules] = useState<OverreceiptRuleVersion[]>([]);
  const [warehouses, setWarehouses] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [activatingId, setActivatingId] = useState<number>();
  const [error, setError] = useState<string | null>(null);
  const [form] = Form.useForm<RuleForm>();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ruleRows, warehouseRows] = await Promise.all([
        api<OverreceiptRuleVersion[]>("/api/overreceipt-rule-versions"),
        api<string[]>("/api/overreceipt-rule-versions/warehouses")
      ]);
      setRules(ruleRows);
      setWarehouses(warehouseRows);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "读取超收规则失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const activeRule = useMemo(() => rules.find((rule) => rule.active), [rules]);

  const publish = async () => {
    const values = await form.validateFields();
    setSubmitting(true);
    try {
      await api<OverreceiptRuleVersion>("/api/overreceipt-rule-versions", {
        method: "POST",
        body: JSON.stringify(values)
      });
      message.success("超收规则新版本已发布，仅新建批次会使用它");
      form.resetFields();
      await load();
    } catch (publishError) {
      message.error(publishError instanceof Error ? publishError.message : "发布失败");
    } finally {
      setSubmitting(false);
    }
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

  return (
    <div className="page-shell overreceipt-page">
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>超收规则</Typography.Title>
          <Typography.Text type="secondary">
            所有操作员均可发布规则；批次创建后锁定当时版本，历史结果可复现。
          </Typography.Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
          刷新
        </Button>
      </div>

      {error && (
        <Alert
          className="section-card"
          type="error"
          showIcon
          title="超收规则读取失败"
          description={error}
          action={<Button onClick={() => void load()}>重试</Button>}
        />
      )}

      <Card className="section-card overreceipt-active-card" loading={loading}>
        <Typography.Text className="overreceipt-eyebrow">当前启用版本</Typography.Text>
        {activeRule ? (
          <div className="overreceipt-active-content">
            <div>
              <Typography.Title level={4}>{activeRule.name}</Typography.Title>
              <RuleLimits rule={activeRule} />
            </div>
            <div className="overreceipt-warehouse-list">
              <Typography.Text type="secondary">允许超收仓库（精确匹配）</Typography.Text>
              <Space wrap>
                {activeRule.allowed_warehouses.map((warehouse) => (
                  <Tag key={warehouse}>{warehouse}</Tag>
                ))}
              </Space>
            </div>
            <Tag color="success" icon={<CheckCircleFilled />}>正在用于新批次</Tag>
          </div>
        ) : (
          <Empty description="尚未发布超收规则；新批次不会自动超收" />
        )}
      </Card>

      <div className="overreceipt-layout">
        <Card title="发布新版本" className="section-card">
          <Alert
            className="section-card"
            type="info"
            showIcon
            title="发布后不可修改"
            description={
              <span>
                调整时发布新版本。规模定位为空或多个 MSKU 定位冲突时不自动超收；通常不要勾选
                <Typography.Text code>供应链成品仓</Typography.Text>。仓库留空表示所有仓库都不允许超收。
              </span>
            }
          />
          <Form<RuleForm>
            form={form}
            layout="vertical"
            requiredMark={false}
            initialValues={{ ...DEFAULT_LIMITS, allowed_warehouses: [] }}
          >
            <Form.Item
              label="规则版本名称"
              name="name"
              rules={[{ required: true, whitespace: true, message: "请输入规则版本名称" }]}
            >
              <Input placeholder="例如：2026-08 超收规则" />
            </Form.Item>
            <div className="overreceipt-limit-grid">
              <Form.Item label="短尾允许超收" name="short_tail_limit" rules={[{ required: true }]}>
                <InputNumber min={0} precision={0} />
              </Form.Item>
              <Form.Item label="中尾允许超收" name="medium_tail_limit" rules={[{ required: true }]}>
                <InputNumber min={0} precision={0} />
              </Form.Item>
              <Form.Item label="长尾允许超收" name="long_tail_limit" rules={[{ required: true }]}>
                <InputNumber min={0} precision={0} />
              </Form.Item>
            </div>
            <Form.Item
              label="允许超收仓库"
              name="allowed_warehouses"
            >
              <Select
                mode="multiple"
                allowClear
                placeholder="选择允许超收的目的仓"
                options={warehouses.map((warehouse) => ({ value: warehouse, label: warehouse }))}
              />
            </Form.Item>
            <Button type="primary" onClick={() => void publish()} loading={submitting}>
              发布并用于新批次
            </Button>
          </Form>
        </Card>

        <Card title="不可变版本记录" className="section-card overreceipt-history-card">
          <Table<OverreceiptRuleVersion>
            rowKey="id"
            loading={loading}
            dataSource={rules}
            pagination={false}
            locale={{ emptyText: <Empty description="暂无规则版本" /> }}
            scroll={{ x: 760 }}
            columns={[
              {
                title: "版本",
                dataIndex: "name",
                render: (name: string, rule) => (
                  <Space orientation="vertical" size={2}>
                    <Typography.Text strong>{name}</Typography.Text>
                    {rule.active && <Tag color="success">当前启用</Tag>}
                  </Space>
                )
              },
              {
                title: "额度",
                render: (_, rule) => <RuleLimits rule={rule} />
              },
              {
                title: "允许仓库",
                render: (_, rule) => rule.allowed_warehouses.join("、")
              },
              {
                title: "发布时间",
                dataIndex: "created_at",
                width: 190,
                render: (value: string) => new Date(value).toLocaleString("zh-CN")
              },
              {
                title: "操作",
                width: 110,
                render: (_, rule) => rule.active ? null : (
                  <Button
                    type="link"
                    loading={activatingId === rule.id}
                    onClick={() => void activate(rule)}
                  >
                    重新启用
                  </Button>
                )
              }
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
