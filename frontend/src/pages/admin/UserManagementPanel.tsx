import { useState } from "react";
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
  Table,
  Tag,
  Typography,
  message
} from "antd";
import { KeyOutlined, PlusOutlined } from "@ant-design/icons";
import type { TableProps } from "antd";

import { api, expireSession } from "../../api";
import type { Role, User } from "../../types";

interface UserManagementPanelProps {
  currentUser: User;
  users: User[];
  loading: boolean;
  error: string | null;
  onDataChanged: () => void | Promise<void>;
}

type UserAction = "create" | "status" | "password" | null;

const USER_TABLE_COMPONENTS: NonNullable<TableProps<User>["components"]> = {
  table: (props) => <table {...props} aria-label="内部账号" />
};

export function UserManagementPanel({
  currentUser,
  users,
  loading,
  error,
  onDataChanged
}: UserManagementPanelProps) {
  const [userModal, setUserModal] = useState(false);
  const [passwordTarget, setPasswordTarget] = useState<User | null>(null);
  const [action, setAction] = useState<UserAction>(null);
  const [userForm] = Form.useForm<{ username: string; password: string; role: Role }>();
  const [passwordForm] = Form.useForm<{ password: string }>();
  const adminCount = users.filter((user) => user.role === "admin").length;
  const operatorCount = users.filter((user) => user.role === "operator").length;
  const disabledCount = users.filter((user) => !user.active).length;

  const createUser = async () => {
    let values: { username: string; password: string; role: Role };
    try {
      values = await userForm.validateFields();
    } catch {
      return;
    }
    setAction("create");
    try {
      await api<User>("/api/users", {
        method: "POST",
        body: JSON.stringify(values)
      });
      setUserModal(false);
      userForm.resetFields();
      await onDataChanged();
      message.success("用户已创建");
    } catch (requestError) {
      message.error(requestError instanceof Error ? requestError.message : "创建用户失败");
    } finally {
      setAction(null);
    }
  };

  const updateStatus = async (user: User) => {
    if (user.id === currentUser.id || action !== null) return;
    setAction("status");
    try {
      await api<User>(`/api/users/${user.id}/status`, {
        method: "PUT",
        body: JSON.stringify({ active: !user.active })
      });
      await onDataChanged();
      message.success(user.active ? "用户已停用" : "用户已启用");
    } catch (requestError) {
      message.error(requestError instanceof Error ? requestError.message : "更新用户状态失败");
    } finally {
      setAction(null);
    }
  };

  const resetPassword = async () => {
    if (!passwordTarget) return;
    let values: { password: string };
    try {
      values = await passwordForm.validateFields();
    } catch {
      return;
    }
    const resettingSelf = passwordTarget.id === currentUser.id;
    setAction("password");
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
      await onDataChanged();
      message.success("密码已重置，该用户需要重新登录");
    } catch (requestError) {
      message.error(requestError instanceof Error ? requestError.message : "重置密码失败");
    } finally {
      setAction(null);
    }
  };

  return (
    <Card
      className="admin-panel-card user-management-panel"
      title="内部账号"
      extra={(
        <Button
          aria-label="创建用户"
          type="primary"
          icon={<PlusOutlined />}
          disabled={action !== null}
          onClick={() => setUserModal(true)}
        >
          创建用户
        </Button>
      )}
    >
      <div className="admin-panel-intro">
        <div>
          <Typography.Text strong>账号与权限</Typography.Text>
          <Typography.Paragraph type="secondary">
            管理员可维护基础资料和账号；操作员仅处理交货批次。停用账号会使其现有登录立即失效。
          </Typography.Paragraph>
        </div>
        <div className="user-summary" role="status" aria-label="账号摘要">
          <Tag>共 {users.length} 个账号</Tag>
          <Tag color="processing">{adminCount} 个管理员</Tag>
          <Tag>{operatorCount} 个操作员</Tag>
          {disabledCount > 0 && <Tag color="warning">{disabledCount} 个已停用</Tag>}
        </div>
      </div>

      {error && <Alert className="inline-alert" type="error" showIcon title="无法读取用户账号" description={error} />}

      <Table<User>
        rowKey="id"
        loading={loading}
        dataSource={users}
        components={USER_TABLE_COMPONENTS}
        pagination={false}
        locale={{ emptyText: error ? "读取失败" : "暂无内部账号" }}
        columns={[
          {
            title: "用户名",
            dataIndex: "username",
            width: 220,
            render: (username: string, user) => (
              <div className="user-name-cell">
                <strong>{username}</strong>
                {user.id === currentUser.id && <Tag color="blue">当前账号</Tag>}
              </div>
            )
          },
          {
            title: "角色",
            dataIndex: "role",
            width: 150,
            render: (role: Role) => role === "admin"
              ? <Tag color="processing">管理员</Tag>
              : <Tag>操作员</Tag>
          },
          {
            title: "状态",
            dataIndex: "active",
            width: 130,
            render: (active: boolean) => active ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>
          },
          {
            title: "操作",
            width: 300,
            render: (_, user) => {
              const isSelf = user.id === currentUser.id;
              return (
                <Space>
                  <Button
                    aria-label={`重置密码 ${user.username}`}
                    icon={<KeyOutlined />}
                    disabled={action !== null}
                    onClick={() => setPasswordTarget(user)}
                  >
                    重置密码
                  </Button>
                  <Popconfirm
                    title={user.active ? "停用此用户？" : "重新启用此用户？"}
                    description={user.active ? "停用后，该用户的现有登录会立即失效。" : undefined}
                    okText={user.active ? "确认停用" : "确认启用"}
                    cancelText="取消"
                    okButtonProps={{
                      danger: user.active,
                      "aria-label": user.active ? "确认停用" : "确认启用"
                    }}
                    cancelButtonProps={{ "aria-label": "取消" }}
                    disabled={isSelf || action !== null}
                    onConfirm={() => updateStatus(user)}
                  >
                    <Button
                      aria-label={`${user.active ? "停用" : "启用"} ${user.username}`}
                      disabled={isSelf || action !== null}
                      danger={user.active}
                    >
                      {user.active ? "停用" : "启用"}
                    </Button>
                  </Popconfirm>
                  {isSelf && <Typography.Text type="secondary">当前账号不可停用</Typography.Text>}
                </Space>
              );
            }
          }
        ]}
      />

      <Modal
        title="创建内部用户"
        open={userModal}
        onCancel={() => {
          if (action === null) setUserModal(false);
        }}
        onOk={() => void createUser()}
        okText="创建"
        cancelText="取消"
        okButtonProps={{ "aria-label": "创建" }}
        confirmLoading={action === "create"}
        cancelButtonProps={{ disabled: action === "create", "aria-label": "取消" }}
        closable={action !== "create"}
        keyboard={action !== "create"}
        mask={{ closable: action !== "create" }}
      >
        <Form form={userForm} layout="vertical" initialValues={{ role: "operator" }}>
          <Form.Item label="用户名" name="username" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item label="初始密码" name="password" rules={[{ required: true, min: 8, message: "密码至少 8 位" }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item label="角色" name="role" rules={[{ required: true, message: "请选择角色" }]}>
            <Select options={[{ value: "operator", label: "操作员" }, { value: "admin", label: "管理员" }]} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`重置密码 · ${passwordTarget?.username ?? ""}`}
        open={passwordTarget !== null}
        onCancel={() => {
          if (action === null) setPasswordTarget(null);
        }}
        onOk={() => void resetPassword()}
        okText="重置密码"
        cancelText="取消"
        okButtonProps={{ "aria-label": "重置密码" }}
        confirmLoading={action === "password"}
        cancelButtonProps={{ disabled: action === "password", "aria-label": "取消" }}
        closable={action !== "password"}
        keyboard={action !== "password"}
        mask={{ closable: action !== "password" }}
      >
        <Alert className="password-reset-alert" type="info" showIcon title="保存后，该用户的现有登录会立即失效。" />
        <Form form={passwordForm} layout="vertical">
          <Form.Item label="新密码" name="password" rules={[{ required: true, min: 8, message: "密码至少 8 位" }]}>
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
