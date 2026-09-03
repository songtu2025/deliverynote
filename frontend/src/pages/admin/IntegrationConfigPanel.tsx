import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Skeleton,
  Space,
  Spin,
  Tag,
  Typography
} from "antd";
import {
  CheckCircleFilled,
  CloudServerOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  WarningFilled
} from "@ant-design/icons";

import { api } from "../../api";

interface GerpgoConfigStatus {
  configured: boolean;
  base_url: string;
  app_id_hint: string;
  has_app_id: boolean;
  has_app_key: boolean;
  source: "environment" | "managed";
}
interface GerpgoConfigForm {
  base_url: string;
  app_id: string;
  app_key: string;
}

export function IntegrationConfigPanel() {
  const [form] = Form.useForm<GerpgoConfigForm>();
  const [config, setConfig] = useState<GerpgoConfigStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const sourceLabel = config?.source === "managed" ? "管理员配置" : "服务环境";

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await api<GerpgoConfigStatus>(
        "/api/admin/integrations/gerpgo"
      );
      setConfig(next);
      form.setFieldsValue({
        base_url: next.base_url,
        app_id: "",
        app_key: ""
      });
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "读取接口配置失败"
      );
    } finally {
      setLoading(false);
    }
  }, [form]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  const saveConfig = async () => {
    let values: GerpgoConfigForm;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");
    try {
      const next = await api<GerpgoConfigStatus>(
        "/api/admin/integrations/gerpgo",
        {
          method: "PUT",
          body: JSON.stringify(values)
        }
      );
      setConfig(next);
      form.setFieldsValue({
        base_url: next.base_url,
        app_id: "",
        app_key: ""
      });
      setNotice("连接验证通过，配置已保存");
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "验证或保存失败"
      );
    } finally {
      setSaving(false);
    }
  };

  if (loading && config === null && !error) {
    return (
      <Card
        className="admin-panel-card integration-config-panel"
        aria-busy="true"
        aria-label="正在读取接口配置"
      >
        <Form form={form} component={false} />
        <Skeleton active title={{ width: 180 }} paragraph={{ rows: 6 }} />
      </Card>
    );
  }
  return (
    <Card
      className="admin-panel-card integration-config-panel"
      title="接口配置"
      extra={(
        <Tag
          color={config === null ? undefined : config.configured ? "success" : "warning"}
        >
          {config === null ? "读取中" : config.configured ? "已配置" : "未配置"}
        </Tag>
      )}
    >
      <div className="integration-config-provider">
        <span className="integration-config-provider-icon" aria-hidden>
          <CloudServerOutlined />
        </span>
        <div>
          <Typography.Title level={4}>积加开放平台</Typography.Title>
          <Typography.Text type="secondary">
            采购和待入库数据共用此配置。
          </Typography.Text>
        </div>
      </div>

      <Spin spinning={loading && config === null}>
        <div className="integration-config-workspace">
        <aside className="integration-config-summary" aria-label="连接概览">
          <div className="integration-config-status">
            {config?.configured ? (
              <CheckCircleFilled className="is-success" aria-hidden />
            ) : (
              <WarningFilled className="is-warning" aria-hidden />
            )}
            <div>
              <Typography.Text strong>
                {config?.configured ? "配置可用" : "尚未配置"}
              </Typography.Text>
              <Typography.Text type="secondary">
                {config?.configured
                  ? config.source === "managed"
                    ? "使用管理员配置。"
                    : "使用服务环境配置；保存后改用管理员配置。"
                  : "填写凭证，连接成功后保存。"}
              </Typography.Text>
            </div>
          </div>

          <dl className="integration-config-facts">
            <div>
              <dt>凭证来源</dt>
              <dd>{sourceLabel}</dd>
            </div>
            <div>
              <dt>同步范围</dt>
              <dd>采购数据、待入库数据</dd>
            </div>
          </dl>

          <div className="integration-config-security-note">
            <SafetyCertificateOutlined aria-hidden />
            <Typography.Text type="secondary">
              App Key 仅在服务端使用，页面不回显。
            </Typography.Text>
          </div>
        </aside>

        <section
          className="integration-config-editor"
          aria-labelledby="integration-config-form-title"
        >
          <div className="integration-config-editor-heading">
            <div>
              <Typography.Title id="integration-config-form-title" level={5}>
                连接参数
              </Typography.Title>
              <Typography.Text type="secondary">
                保存时先验证连接。
              </Typography.Text>
            </div>
          </div>

          {error && (
            <Alert
              type="error"
              showIcon
              title="操作失败"
              description={error}
            />
          )}
          {notice && <Alert type="success" showIcon title={notice} />}

          <Form
            className="integration-config-form"
            form={form}
            layout="vertical"
            requiredMark="optional"
          >
            <Form.Item
              label="API 地址"
              name="base_url"
              rules={[
                { required: true, message: "请输入 API 地址" },
                {
                  pattern: /^https?:\/\//i,
                  message: "API 地址必须以 http:// 或 https:// 开头"
                }
              ]}
            >
              <Input placeholder="https://open.gerpgo.com" />
            </Form.Item>

            <div className="integration-config-credentials">
              <Form.Item
                label="App ID"
                name="app_id"
                extra={
                  config?.has_app_id
                    ? `当前：${config.app_id_hint}；留空则不修改`
                    : "首次配置时必须填写"
                }
                rules={[
                  {
                    required: !config?.has_app_id,
                    message: "请输入 App ID"
                  }
                ]}
              >
                <Input autoComplete="off" placeholder="请输入 App ID" />
              </Form.Item>

              <Form.Item
                label="App Key"
                name="app_key"
                extra={
                  config?.has_app_key
                    ? "密钥已保存；留空则不修改"
                    : "首次配置时必须填写"
                }
                rules={[
                  {
                    required: !config?.has_app_key,
                    message: "请输入 App Key"
                  }
                ]}
              >
                <Input.Password
                  autoComplete="new-password"
                  placeholder="请输入 App Key"
                />
              </Form.Item>
            </div>

            <div className="integration-config-actions">
              <Space wrap>
                <Button
                  type="primary"
                  loading={saving}
                  disabled={loading}
                  onClick={() => void saveConfig()}
                >
                  测试并保存
                </Button>
                <Button
                  icon={<ReloadOutlined />}
                  loading={loading}
                  disabled={saving}
                  onClick={() => void loadConfig()}
                >
                  重新读取
                </Button>
              </Space>
            </div>
          </Form>
        </section>
        </div>
      </Spin>
    </Card>
  );
}
