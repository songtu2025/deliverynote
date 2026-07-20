import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
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
import { PlusOutlined, UploadOutlined } from "@ant-design/icons";
import type { UploadProps } from "antd";

import { api } from "../api";
import type { InputVersion, Role, User } from "../types";

const KINDS = [
  { value: "purchase", label: "采购需求" },
  { value: "product", label: "商品信息" },
  { value: "supplier", label: "供应商资料" },
  { value: "position", label: "库位/排仓数据" },
  { value: "template", label: "导出模板" }
];

export default function AdminPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [versions, setVersions] = useState<InputVersion[]>([]);
  const [userModal, setUserModal] = useState(false);
  const [userForm] = Form.useForm<{ username: string; password: string; role: Role }>();
  const [versionForm] = Form.useForm<{ kind: string; name: string; activate: boolean }>();

  const load = async () => {
    try {
      const [userRows, versionRows] = await Promise.all([
        api<User[]>("/api/users"),
        api<InputVersion[]>("/api/input-versions")
      ]);
      setUsers(userRows);
      setVersions(versionRows);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取管理员数据失败");
    }
  };

  useEffect(() => {
    void load();
  }, []);

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
      message.success("输入版本已上传");
    } catch (error) {
      options.onError?.(error instanceof Error ? error : new Error("上传失败"));
      message.error(error instanceof Error ? error.message : "上传失败");
    }
  };

  const activate = async (id: number) => {
    try {
      await api<InputVersion>(`/api/input-versions/${id}/activate`, { method: "POST" });
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "启用失败");
    }
  };

  return (
    <div className="page-shell">
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>管理员维护</Typography.Title>
          <Typography.Text type="secondary">维护内部账号和五类批次输入版本。</Typography.Text>
        </div>
      </div>
      <Tabs
        items={[
          {
            key: "versions",
            label: "输入版本",
            children: (
              <Space direction="vertical" size={18} style={{ width: "100%" }}>
                <Card title="上传新版本">
                  <Form
                    form={versionForm}
                    layout="inline"
                    initialValues={{ activate: true }}
                  >
                    <Form.Item name="kind" rules={[{ required: true }]}>
                      <Select placeholder="输入类型" options={KINDS} style={{ width: 170 }} />
                    </Form.Item>
                    <Form.Item name="name" rules={[{ required: true }]}>
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
                  dataSource={versions}
                  columns={[
                    {
                      title: "类型",
                      dataIndex: "kind",
                      render: (kind: string) => KINDS.find((item) => item.value === kind)?.label ?? kind
                    },
                    { title: "版本", dataIndex: "name" },
                    { title: "文件", dataIndex: "original_name" },
                    {
                      title: "状态",
                      dataIndex: "active",
                      width: 100,
                      render: (active: boolean) => active ? <Tag color="success">已启用</Tag> : <Tag>未启用</Tag>
                    },
                    {
                      title: "操作",
                      width: 100,
                      render: (_, version) => (
                        <Button type="link" disabled={version.active} onClick={() => void activate(version.id)}>
                          启用
                        </Button>
                      )
                    }
                  ]}
                />
              </Space>
            )
          },
          {
            key: "users",
            label: "用户",
            children: (
              <Card
                title="内部账号"
                extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setUserModal(true)}>创建用户</Button>}
              >
                <Table<User>
                  rowKey="id"
                  dataSource={users}
                  pagination={false}
                  columns={[
                    { title: "用户名", dataIndex: "username" },
                    {
                      title: "角色",
                      dataIndex: "role",
                      render: (role: Role) => role === "admin" ? "管理员" : "操作员"
                    },
                    {
                      title: "状态",
                      dataIndex: "active",
                      render: (active: boolean) => active ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>
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
          <Form.Item label="初始密码" name="password" rules={[{ required: true, min: 8 }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item label="角色" name="role" rules={[{ required: true }]}>
            <Select options={[{ value: "operator", label: "操作员" }, { value: "admin", label: "管理员" }]} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}