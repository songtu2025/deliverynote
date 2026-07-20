import { useEffect, useState } from "react";
import {
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
  message
} from "antd";
import { PlusOutlined, RightOutlined } from "@ant-design/icons";

import { api } from "../api";
import type { Batch } from "../types";

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  preflight_ready: "预检通过",
  queued: "等待计算",
  running: "计算中",
  succeeded: "计算成功",
  failed: "失败",
  expired: "已过期"
};

const STATUS_COLORS: Record<string, string> = {
  draft: "default",
  preflight_ready: "cyan",
  queued: "blue",
  running: "processing",
  succeeded: "success",
  failed: "error",
  expired: "default"
};

export function StatusTag({ status }: { status: string }) {
  return <Tag color={STATUS_COLORS[status]}>{STATUS_LABELS[status] ?? status}</Tag>;
}

export default function BatchesPage({ onOpen }: { onOpen: (id: number) => void }) {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [form] = Form.useForm<{ name: string }>();

  const load = async () => {
    setLoading(true);
    try {
      setBatches(await api<Batch[]>("/api/batches"));
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取批次失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const create = async () => {
    const values = await form.validateFields();
    try {
      const batch = await api<Batch>("/api/batches", {
        method: "POST",
        body: JSON.stringify(values)
      });
      setCreating(false);
      form.resetFields();
      onOpen(batch.id);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建批次失败");
    }
  };

  return (
    <div className="page-shell">
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>交货批次</Typography.Title>
          <Typography.Text type="secondary">
            每个批次独立锁定五类输入版本，并按文件顺序共享采购余额。
          </Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
          新建批次
        </Button>
      </div>
      <Table<Batch>
        rowKey="id"
        loading={loading}
        dataSource={batches}
        locale={{ emptyText: <Empty description="暂无批次" /> }}
        columns={[
          { title: "批次", dataIndex: "name" },
          {
            title: "状态",
            dataIndex: "status",
            width: 130,
            render: (value: string) => <StatusTag status={value} />
          },
          {
            title: "创建时间",
            dataIndex: "created_at",
            width: 190,
            render: (value: string) => new Date(value).toLocaleString("zh-CN")
          },
          {
            title: "操作",
            width: 120,
            render: (_, batch) => (
              <Button type="link" onClick={() => onOpen(batch.id)}>
                <Space size={4}>打开<RightOutlined /></Space>
              </Button>
            )
          }
        ]}
      />
      <Modal
        title="新建交货批次"
        open={creating}
        onCancel={() => setCreating(false)}
        onOk={() => void create()}
        okText="创建"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="批次名称"
            name="name"
            rules={[{ required: true, message: "请输入批次名称" }]}
          >
            <Input placeholder="例如：2026-07-20 交货批次" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}