import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
  message
} from "antd";
import {
  CheckCircleFilled,
  HistoryOutlined,
  KeyOutlined,
  PlusOutlined,
  UploadOutlined
} from "@ant-design/icons";
import type { UploadProps } from "antd";

import { api, expireSession } from "../api";
import type { AuditLog, InputVersion, Role, User } from "../types";

const KINDS = [
  { value: "purchase", label: "采购需求" },
  { value: "product", label: "商品信息" },
  { value: "supplier", label: "供应商资料" },
  { value: "position", label: "库位/排仓数据" },
  { value: "template", label: "导出模板" }
];

const AUDIT_LABELS: Record<string, string> = {
  login: "登录",
  logout: "退出",
  create_user: "创建用户",
  update_user_status: "更新用户状态",
  reset_user_password: "重置密码",
  upload_input_version: "上传输入版本",
  activate_input_version: "启用输入版本",
  create_batch: "创建批次",
  upload_batch_file: "上传交货文件",
  delete_batch_file: "删除交货文件",
  reorder_batch_files: "调整文件顺序",
  preflight_batch: "执行预检",
  queue_compute: "启动计算",
  queue_export: "生成导出",
  save_split: "保存拆分",
  worker_compute_succeeded: "计算完成",
  worker_export_succeeded: "导出完成",
  worker_compute_failed: "计算失败",
  worker_export_failed: "导出失败"
};

type AdminPageProps = { currentUser: User };

export default function AdminPage({ currentUser }: AdminPageProps) {
  const [users, setUsers] = useState<User[]>([]);
  const [versions, setVersions] = useState<InputVersion[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [userModal, setUserModal] = useState(false);
  const [passwordTarget, setPasswordTarget] = useState<User | null>(null);
  const [userForm] = Form.useForm<{ username: string; password: string; role: Role }>();
  const [versionForm] = Form.useForm<{ kind: string; name: string; activate: boolean }>();
  const [passwordForm] = Form.useForm<{ password: string }>();

  const load = async () => {
    setLoading(true);
    try {
      const [userRows, versionRows, auditRows] = await Promise.all([
        api<User[]>("/api/users"),
        api<InputVersion[]>("/api/input-versions"),
        api<AuditLog[]>("/api/audit-logs")
      ]);
      setUsers(userRows);
      setVersions(versionRows);
      setAuditLogs(auditRows);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取管理员数据失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const activeVersions = useMemo(
    () => Object.fromEntries(versions.filter((version) => version.active).map((version) => [version.kind, version])),
    [versions]
  );
  const readyCount = KINDS.filter((kind) => activeVersions[kind.value]).length;

  const createUser = async () => {
    const values = await userForm.validateFields();
    try {
      await api<User>("/api/users", {
        method: "POST",
        body: JSON.stringify(values)
      });
      setUserModal(false);
      userForm.resetFields();
      await load();
      message.success("用户已创建");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建用户失败");
    }
  };

  const uploadVersion: NonNullable<UploadProps["customRequest"]> = async (options) => {
    try {
      const values = await versionForm.validateFields();
      const formData = new FormData();
      formData.append("name", values.name);
      formData.append("activate", String(values.activate ?? false));
      formData.append("file", options.file as File);
      await api<InputVersion>(`/api/input-versions/${values.kind}`, {
        method: "POST",
        body: formData
      });
      options.onSuccess?.({});
      versionForm.resetFields();
      await load();
      message.success("文件校验通过，输入版本已上传");
    } catch (error) {
      options.onError?.(error instanceof Error ? error : new Error("上传失败"));
      message.error(error instanceof Error ? error.message : "上传失败");
    }
  };

  const activate = async (version: InputVersion) => {
    try {
      await api<InputVersion>(`/api/input-versions/${version.id}/activate`, { method: "POST" });
      await load();
      message.success(`${version.name} 已启用，仅影响以后创建的批次`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "启用失败");
    }
  };

  const updateStatus = async (user: User) => {
    try {
      await api<User>(`/api/users/${user.id}/status`, {
        method: "PUT",
        body: JSON.stringify({ active: !user.active })
      });
      await load();
      message.success(user.active ? "用户已停用" : "用户已启用");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "更新用户状态失败");
    }
  };

  const resetPassword = async () => {
    if (!passwordTarget) return;
    const values = await passwordForm.validateFields();
    const resettingSelf = passwordTarget.id === currentUser.id;
    try {
      await api<void>(`/api/users/${passwordTarget.id}/password`, {
        method: "PUT",
        body: JSON.stringify(values)
      });
      setPasswordTarget(null);
      passwordForm.resetFields();
      if (resettingSelf) {
        expireSession("密码已重置，请使用新密码重新登录");
        return;
      }
      await load();
      message.success("密码已重置，该用户需要重新登录");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "重置密码失败");
    }
  };

  return (
    <div className="page-shell">
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>管理员维护</Typography.Title>
          <Typography.Text type="secondary">确保五类输入资料可用，并维护内部账号与操作记录。</Typography.Text>
        </div>
      </div>

      <Tabs
        animated={false}
        items={[
          {
            key: "versions",
            label: "输入资料",
            children: (
              <Space orientation="vertical" size={18} style={{ width: "100%" }}>
                {readyCount < KINDS.length && (
                  <Alert
                    type="warning"
                    showIcon
                    title={`基础资料未就绪（${readyCount}/${KINDS.length}）`}
                    description="缺少启用版本时，操作员无法创建新批次。"
                  />
                )}
                <div className="version-readiness-grid">
                  {KINDS.map((kind) => {
                    const active = activeVersions[kind.value];
                    return (
                      <Card className="version-status-card" key={kind.value} size="small">
                        <div className="version-card-title">
                          <span>{kind.label}</span>
                          {active ? <CheckCircleFilled /> : <Tag color="warning">未启用</Tag>}
                        </div>
                        <strong>{active?.name ?? "等待上传"}</strong>
                        <Typography.Text ellipsis type="secondary">
                          {active?.original_name ?? "—"}
                        </Typography.Text>
                      </Card>
                    );
                  })}
                </div>

                <Card title="上传并校验新版本">
                  <Form form={versionForm} layout="inline" initialValues={{ activate: true }}>
                    <Form.Item name="kind" rules={[{ required: true, message: "请选择输入类型" }]}>
                      <Select placeholder="输入类型" options={KINDS} style={{ width: 170 }} />
                    </Form.Item>
                    <Form.Item name="name" rules={[{ required: true, message: "请输入版本名称" }]}>
                      <Input placeholder="版本名称" style={{ width: 220 }} />
                    </Form.Item>
                    <Form.Item name="activate" valuePropName="checked">
                      <Switch checkedChildren="上传后启用" unCheckedChildren="仅上传" />
                    </Form.Item>
                    <Form.Item>
                      <Upload accept=".xls,.xlsx" showUploadList={false} customRequest={uploadVersion}>
                        <Button icon={<UploadOutlined />}>选择 Excel 并上传</Button>
                      </Upload>
                    </Form.Item>
                  </Form>
                </Card>

                <Table<InputVersion>
                  rowKey="id"
                  loading={loading}
                  dataSource={versions}
                  scroll={{ x: 980 }}
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                  columns={[
                    {
                      title: "类型",
                      dataIndex: "kind",
                      width: 140,
                      render: (kind: string) => KINDS.find((item) => item.value === kind)?.label ?? kind
                    },
                    { title: "版本", dataIndex: "name", width: 180 },
                    { title: "文件", dataIndex: "original_name", ellipsis: true, width: 240 },
                    {
                      title: "上传时间",
                      dataIndex: "created_at",
                      width: 190,
                      render: (value: string) => new Date(value).toLocaleString("zh-CN")
                    },
                    {
                      title: "状态",
                      dataIndex: "active",
                      width: 100,
                      render: (active: boolean) => active ? <Tag color="success">当前启用</Tag> : <Tag>历史版本</Tag>
                    },
                    {
                      title: "操作",
                      width: 100,
                      render: (_, version) => version.active ? null : (
                        <Popconfirm
                          title="启用此版本？"
                          description="仅影响以后创建的批次，已有批次继续使用锁定版本。"
                          onConfirm={() => void activate(version)}
                        >
                          <Button type="link">启用</Button>
                        </Popconfirm>
                      )
                    }
                  ]}
                />
              </Space>
            )
          },
          {
            key: "users",
            label: "用户管理",
            children: (
              <Card
                title="内部账号"
                extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setUserModal(true)}>创建用户</Button>}
              >
                <Table<User>
                  rowKey="id"
                  loading={loading}
                  dataSource={users}
                  pagination={false}
                  scroll={{ x: 760 }}
                  columns={[
                    { title: "用户名", dataIndex: "username", width: 180 },
                    {
                      title: "角色",
                      dataIndex: "role",
                      width: 120,
                      render: (role: Role) => role === "admin" ? "管理员" : "操作员"
                    },
                    {
                      title: "状态",
                      dataIndex: "active",
                      width: 120,
                      render: (active: boolean) => active ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>
                    },
                    {
                      title: "操作",
                      width: 260,
                      render: (_, user) => (
                        <Space>
                          <Button icon={<KeyOutlined />} onClick={() => setPasswordTarget(user)}>重置密码</Button>
                          <Popconfirm
                            title={user.active ? "停用此用户？" : "重新启用此用户？"}
                            description={user.active ? "停用后，该用户的现有登录会立即失效。" : undefined}
                            disabled={user.id === currentUser.id}
                            onConfirm={() => void updateStatus(user)}
                          >
                            <Button disabled={user.id === currentUser.id} danger={user.active}>
                              {user.active ? "停用" : "启用"}
                            </Button>
                          </Popconfirm>
                        </Space>
                      )
                    }
                  ]}
                />
              </Card>
            )
          },
          {
            key: "audit",
            label: <Space size={6}><HistoryOutlined />操作记录</Space>,
            children: (
              <Card title="最近 200 条操作记录">
                <Table<AuditLog>
                  rowKey="id"
                  loading={loading}
                  dataSource={auditLogs}
                  scroll={{ x: 780 }}
                  pagination={{ pageSize: 15, showSizeChanger: false }}
                  columns={[
                    {
                      title: "时间",
                      dataIndex: "created_at",
                      width: 190,
                      render: (value: string) => new Date(value).toLocaleString("zh-CN")
                    },
                    {
                      title: "操作人",
                      dataIndex: "user_id",
                      width: 130,
                      render: (id: number | null) => id ? users.find((user) => user.id === id)?.username ?? `用户 #${id}` : "系统 Worker"
                    },
                    {
                      title: "操作",
                      dataIndex: "action",
                      width: 180,
                      render: (action: string) => AUDIT_LABELS[action] ?? action
                    },
                    {
                      title: "对象",
                      width: 180,
                      render: (_, log) => `${log.entity_type} #${log.entity_id}`
                    }
                  ]}
                />
              </Card>
            )
          }
        ]}
      />

      <Modal
        title="创建内部用户"
        open={userModal}
        onCancel={() => setUserModal(false)}
        onOk={() => void createUser()}
        okText="创建"
      >
        <Form form={userForm} layout="vertical" initialValues={{ role: "operator" }}>
          <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="初始密码" name="password" rules={[{ required: true, min: 8, message: "密码至少 8 位" }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item label="角色" name="role" rules={[{ required: true }]}>
            <Select options={[{ value: "operator", label: "操作员" }, { value: "admin", label: "管理员" }]} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`重置密码 · ${passwordTarget?.username ?? ""}`}
        open={passwordTarget !== null}
        onCancel={() => setPasswordTarget(null)}
        onOk={() => void resetPassword()}
        okText="重置密码"
      >
        <Alert className="password-reset-alert" type="info" showIcon title="保存后，该用户的现有登录会立即失效。" />
        <Form form={passwordForm} layout="vertical">
          <Form.Item label="新密码" name="password" rules={[{ required: true, min: 8, message: "密码至少 8 位" }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
