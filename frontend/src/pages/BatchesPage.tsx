import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Form,
  Input,
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
  PlusOutlined,
  RightOutlined,
  SearchOutlined
} from "@ant-design/icons";

import { api } from "../api";
import { beijingDateTimeParts, formatBeijingDateTime } from "../dateTime";
import type { Batch, InputVersion, OverreceiptRuleVersion } from "../types";

export const STATUS_LABELS: Record<string, string> = {
  draft: "准备文件",
  preflight_ready: "预检通过",
  queued: "等待计算",
  running: "正在计算",
  succeeded: "计算完成",
  failed: "处理失败",
  expired: "任务已过期"
};

const STATUS_COLORS: Record<string, string> = {
  draft: "default",
  preflight_ready: "cyan",
  queued: "blue",
  running: "processing",
  succeeded: "success",
  failed: "error",
  expired: "warning"
};

const VERSION_KINDS = [
  { value: "purchase", label: "采购需求" },
  { value: "product", label: "商品信息" },
  { value: "supplier", label: "供应商资料" },
  { value: "position", label: "库位/排仓" },
  { value: "template", label: "导出模板" }
];

const STATUS_OPTIONS = Object.entries(STATUS_LABELS).map(([value, label]) => ({
  value,
  label
}));

function nextAction(batch: Batch): string {
  if (batch.status === "draft") return batch.file_count ? "执行预检" : "上传交货文件";
  if (batch.status === "preflight_ready") return "启动计算";
  if (batch.status === "queued" || batch.status === "running") return "等待后台任务";
  if (batch.status === "failed" || batch.status === "expired") return "查看原因并重试";
  if (batch.download_ready) return "下载结果";
  if ((batch.summary?.manual_total ?? 0) > 0) return "审校待处理";
  return "生成导出";
}

function todayBatchName(): string {
  const parts = beijingDateTimeParts();
  return `${parts.year}-${parts.month}-${parts.day} 交货批次`;
}

export function StatusTag({ status }: { status: string }) {
  return <Tag color={STATUS_COLORS[status]}>{STATUS_LABELS[status] ?? status}</Tag>;
}

export default function BatchesPage({ onOpen }: { onOpen: (id: number) => void }) {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [versions, setVersions] = useState<InputVersion[]>([]);
  const [overreceiptRules, setOverreceiptRules] = useState<OverreceiptRuleVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>();
  const [form] = Form.useForm<{ name: string }>();

  const load = async () => {
    setLoading(true);
    try {
      const [batchRows, versionRows, overreceiptRuleRows] = await Promise.all([
        api<Batch[]>("/api/batches"),
        api<InputVersion[]>("/api/input-versions"),
        api<OverreceiptRuleVersion[]>("/api/overreceipt-rule-versions")
      ]);
      setBatches(batchRows);
      setVersions(versionRows);
      setOverreceiptRules(overreceiptRuleRows);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取批次失败");
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
  const missingKinds = VERSION_KINDS.filter((kind) => !activeVersions[kind.value]);
  const activeOverreceiptRule = overreceiptRules.find((rule) => rule.active);
  const ready = missingKinds.length === 0;

  const filtered = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase("zh-CN");
    return batches.filter((batch) => {
      const matchesQuery = !keyword || batch.name.toLocaleLowerCase("zh-CN").includes(keyword);
      return matchesQuery && (!statusFilter || batch.status === statusFilter);
    });
  }, [batches, query, statusFilter]);

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

  const openCreate = () => {
    form.setFieldsValue({ name: todayBatchName() });
    setCreating(true);
  };

  return (
    <div className="page-shell batch-list-page">
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>交货批次</Typography.Title>
          <Typography.Text type="secondary">
            按文件顺序共享采购余额，每个批次独立锁定基础资料版本。
          </Typography.Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={!ready}
          title={ready ? "新建交货批次" : "请先补齐五类启用版本"}
          onClick={openCreate}
        >
          新建批次
        </Button>
      </div>

      {ready ? (
        <div className="readiness-strip" aria-label="基础资料已就绪">
          <div className="readiness-title">
            <CheckCircleFilled /> 基础资料已就绪
          </div>
          {VERSION_KINDS.map((kind) => (
            <div className="readiness-item" key={kind.value}>
              <span>{kind.label}</span>
              <strong>{activeVersions[kind.value]?.name}</strong>
            </div>
          ))}
        </div>
      ) : (
        <Alert
          className="section-card"
          type="warning"
          showIcon
          title="暂时不能创建批次"
          description={`缺少启用的基础资料：${missingKinds.map((kind) => kind.label).join("、")}。请联系管理员补齐。`}
        />
      )}

      <Alert
        className="section-card"
        type={activeOverreceiptRule ? "success" : "info"}
        showIcon
        title={
          activeOverreceiptRule
            ? `新批次将锁定超收规则：${activeOverreceiptRule.name}`
            : "尚无启用的超收规则；新批次不会自动超收"
        }
      />

      <div className="table-toolbar batch-list-toolbar">
        <div className="table-filter-field">
          <label htmlFor="batch-search">搜索</label>
          <Input
            id="batch-search"
            aria-label="搜索"
            allowClear
            prefix={<SearchOutlined />}
            placeholder="搜索批次名称"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="table-filter-field">
          <label htmlFor="batch-status-filter">状态</label>
          <Select
            id="batch-status-filter"
            aria-label="状态"
            allowClear
            placeholder="全部状态"
            options={STATUS_OPTIONS}
            value={statusFilter}
            onChange={setStatusFilter}
          />
        </div>
        <Typography.Text className="batch-result-count" type="secondary">
          共 {filtered.length} 个批次
        </Typography.Text>
      </div>

      <Table<Batch>
        className="batch-list-table"
        rowKey="id"
        loading={loading}
        dataSource={filtered}
        components={{
          table: (props) => <table {...props} aria-label="交货批次列表" />
        }}
        locale={{ emptyText: <Empty description={query || statusFilter ? "没有匹配的批次" : "暂无批次"} /> }}
        pagination={filtered.length > 12 ? { pageSize: 12, showSizeChanger: false } : false}
        columns={[
          {
            title: "批次",
            dataIndex: "name",
            render: (value: string, batch) => (
              <Button className="batch-name-link" type="link" onClick={() => onOpen(batch.id)}>
                {value}
              </Button>
            )
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 130,
            render: (value: string) => (
              <div className="batch-table-value">
                <span className="batch-cell-label">状态</span>
                <StatusTag status={value} />
              </div>
            )
          },
          {
            title: "文件 / 数量",
            width: 190,
            render: (_, batch) => (
              <div className="batch-table-value">
                <span className="batch-cell-label">文件 / 数量</span>
                <span className="batch-volume">
                  {batch.file_count} 个文件
                  {batch.summary && batch.summary.delivery_total > 0
                    ? " · 交货 " + batch.summary.delivery_total
                    : ""}
                </span>
              </div>
            )
          },
          {
            title: "下一步",
            width: 170,
            render: (_, batch) => (
              <div className="batch-table-value">
                <span className="batch-cell-label">下一步</span>
                <span className="next-action">{nextAction(batch)}</span>
              </div>
            )
          },
          {
            title: "更新时间",
            dataIndex: "updated_at",
            width: 190,
            render: (value: string) => (
              <div className="batch-table-value">
                <span className="batch-cell-label">更新时间</span>
                <span>{formatBeijingDateTime(value)}</span>
              </div>
            )
          },
          {
            title: "操作",
            width: 100,
            render: (_, batch) => (
              <Button
                className="batch-open-action"
                type="link"
                aria-label={"打开 " + batch.name}
                onClick={() => onOpen(batch.id)}
              >
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
        okText="创建并上传文件"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="批次名称"
            name="name"
            rules={[{ required: true, message: "请输入批次名称" }]}
          >
            <Input placeholder="例如：2026-07-21 交货批次" />
          </Form.Item>
        </Form>
        <div className="locked-version-preview">
          <Typography.Text strong>本批次将锁定以下版本</Typography.Text>
          {VERSION_KINDS.map((kind) => (
            <div key={kind.value}>
              <span>{kind.label}</span>
              <strong>{activeVersions[kind.value]?.name ?? "未启用"}</strong>
            </div>
          ))}
          <div>
            <span>超收规则</span>
            <strong>{activeOverreceiptRule?.name ?? "未启用（不自动超收）"}</strong>
          </div>
        </div>
      </Modal>
    </div>
  );
}
