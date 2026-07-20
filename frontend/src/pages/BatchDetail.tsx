import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Space,
  Statistic,
  Switch,
  Table,
  Typography,
  Upload,
  message
} from "antd";
import type { UploadProps } from "antd";
import {
  ArrowDownOutlined,
  ArrowLeftOutlined,
  ArrowUpOutlined,
  CloudUploadOutlined,
  DownloadOutlined,
  ExportOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  SafetyCertificateOutlined
} from "@ant-design/icons";

import { api, download } from "../api";
import type {
  Batch,
  BatchFile,
  DeliveryException,
  Job,
  SplitPart
} from "../types";
import { StatusTag } from "./BatchesPage";

const VERSION_LABELS: Record<string, string> = {
  purchase: "采购",
  product: "商品",
  supplier: "供应商",
  position: "库位/排仓",
  template: "导出模板"
};

type SplitFormValues = { parts: SplitPart[] };

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export default function BatchDetail({ batchId, onBack }: { batchId: number; onBack: () => void }) {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [exceptions, setExceptions] = useState<DeliveryException[]>([]);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [splitTarget, setSplitTarget] = useState<DeliveryException | null>(null);
  const [splitForm] = Form.useForm<SplitFormValues>();
  const splitParts = Form.useWatch("parts", splitForm) ?? [];

  const load = async () => {
    setLoading(true);
    try {
      const [batchResult, exceptionRows] = await Promise.all([
        api<Batch>(`/api/batches/${batchId}`),
        api<DeliveryException[]>(`/api/batches/${batchId}/exceptions`)
      ]);
      setBatch(batchResult);
      setExceptions(exceptionRows);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取批次失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [batchId]);

  const totals = useMemo(() => {
    if (batch?.summary) {
      return {
        delivery: batch.summary.delivery_total,
        imported: batch.summary.import_total,
        manual: batch.summary.manual_total
      };
    }
    const files = batch?.files ?? [];
    return files.reduce(
      (sum, file) => ({
        delivery: sum.delivery + file.delivery_total,
        imported: sum.imported + file.import_total,
        manual: sum.manual + file.manual_total
      }),
      { delivery: 0, imported: 0, manual: 0 }
    );
  }, [batch]);

  const pollJob = async (jobId: number) => {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const job = await api<Job>(`/api/jobs/${jobId}`);
      if (job.status === "succeeded") {
        await load();
        message.success(job.kind === "compute" ? "批次计算完成" : "导出完成");
        return;
      }
      if (job.status === "failed") {
        await load();
        throw new Error(job.error_message ?? "任务失败");
      }
      await wait(1500);
    }
    throw new Error("任务仍在运行，请稍后刷新")
  };

  const runAction = async (name: string, operation: () => Promise<void>) => {
    setAction(name);
    try {
      await operation();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "操作失败");
    } finally {
      setAction(null);
    }
  };

  const uploadFile: NonNullable<UploadProps["customRequest"]> = async (options) => {
    await runAction("upload", async () => {
      const formData = new FormData();
      formData.append("file", options.file as File);
      await api<BatchFile>(`/api/batches/${batchId}/files`, {
        method: "POST",
        body: formData
      });
      options.onSuccess?.({});
      await load();
    });
  };

  const move = async (fileId: number, offset: number) => {
    if (!batch?.files) return;
    const ids = batch.files.map((file) => file.id);
    const index = ids.indexOf(fileId);
    const next = index + offset;
    if (index < 0 || next < 0 || next >= ids.length) return;
    [ids[index], ids[next]] = [ids[next], ids[index]];
    await runAction("order", async () => {
      await api<Batch>(`/api/batches/${batchId}/files/order`, {
        method: "PUT",
        body: JSON.stringify({ file_ids: ids })
      });
      await load();
    });
  };

  const preflight = () => runAction("preflight", async () => {
    await api<Batch>(`/api/batches/${batchId}/preflight`, { method: "POST" });
    await load();
    message.success("预检通过，可以启动计算");
  });

  const compute = () => runAction("compute", async () => {
    const job = await api<Job>(`/api/batches/${batchId}/compute`, { method: "POST" });
    await load();
    await pollJob(job.id);
  });

  const startExport = () => runAction("export", async () => {
    const job = await api<Job>(`/api/batches/${batchId}/export`, { method: "POST" });
    await pollJob(job.id);
  });

  const openSplit = (record: DeliveryException) => {
    setSplitTarget(record);
    splitForm.setFieldsValue({
      parts: record.parts.length
        ? record.parts
        : [
            {
              quantity: record.manual_quantity,
              destination: record.destination,
              site: record.full_site.includes("、") ? "" : record.full_site,
              supplier_code: "",
              sku: record.sku,
              delivery_note: record.reason,
              resolved: false
            }
          ]
    });
  };

  const saveSplit = async () => {
    if (!splitTarget) return;
    const values = await splitForm.validateFields();
    await runAction("split", async () => {
      await api<DeliveryException>(`/api/exceptions/${splitTarget.id}/split`, {
        method: "PUT",
        body: JSON.stringify(values)
      });
      setSplitTarget(null);
      splitForm.resetFields();
      await load();
      message.success("拆分已保存，数量总额未改变");
    });
  };

  if (!batch) {
    return <Card loading={loading} />;
  }

  const files = batch.files ?? [];
  const conserved = totals.delivery === totals.imported + totals.manual;
  const splitTotal = splitParts.reduce((sum, part) => sum + Number(part?.quantity ?? 0), 0);

  return (
    <div className="page-shell">
      <div className="page-heading">
        <div>
          <Button type="link" icon={<ArrowLeftOutlined />} onClick={onBack} style={{ paddingLeft: 0 }}>
            返回批次列表
          </Button>
          <Typography.Title level={2}>{batch.name}</Typography.Title>
          <Space><StatusTag status={batch.status} /><span className="muted">批次 #{batch.id}</span></Space>
        </div>
        <Space wrap>
          <Upload accept=".xls,.xlsx" showUploadList={false} customRequest={uploadFile}>
            <Button icon={<CloudUploadOutlined />} loading={action === "upload"}>上传交货文件</Button>
          </Upload>
          <Button
            icon={<SafetyCertificateOutlined />}
            disabled={batch.status !== "draft" && batch.status !== "failed"}
            onClick={() => void preflight()}
            loading={action === "preflight"}
          >
            预检
          </Button>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            disabled={batch.status !== "preflight_ready" && batch.status !== "failed"}
            loading={action === "compute"}
            onClick={() => void compute()}
          >
            启动计算
          </Button>
        </Space>
      </div>

      {batch.error_message && <Alert type="error" showIcon message="任务失败" description={batch.error_message} className="section-card" />}

      <div className="summary-grid">
        <Card><Statistic title="交货总量" value={totals.delivery} /></Card>
        <Card><Statistic title="可导入总量" value={totals.imported} /></Card>
        <Card><Statistic title="待处理量" value={totals.manual} /></Card>
        <Card>
          <Statistic title="数量守恒" value={conserved ? "通过" : "异常"} />
          <div className={conserved ? "conservation-ok" : "conservation-bad"}>
            {totals.delivery} = {totals.imported} + {totals.manual}
          </div>
        </Card>
      </div>

      <Card title="本批次锁定输入版本" className="section-card">
        <Descriptions size="small" column={{ xs: 2, sm: 3, lg: 5 }}>
          {Object.entries(batch.version_ids).map(([kind, id]) => (
            <Descriptions.Item key={kind} label={VERSION_LABELS[kind] ?? kind}>#{id}</Descriptions.Item>
          ))}
        </Descriptions>
      </Card>

      <Card title="来源文件与处理顺序" className="section-card">
        <Table<BatchFile>
          rowKey="id"
          loading={loading}
          dataSource={files}
          pagination={false}
          columns={[
            {
              title: "顺序",
              dataIndex: "file_order",
              width: 80,
              render: (value: number) => <span className="file-order">{String(value).padStart(2, "0")}</span>
            },
            { title: "来源文件", dataIndex: "original_name" },
            { title: "供应商", dataIndex: "supplier_name", width: 140 },
            { title: "交货", dataIndex: "delivery_total", width: 90 },
            { title: "导入", dataIndex: "import_total", width: 90 },
            { title: "待处理", dataIndex: "manual_total", width: 90 },
            {
              title: "操作",
              width: 230,
              render: (_, file, index) => (
                <Space>
                  <Button size="small" icon={<ArrowUpOutlined />} disabled={index === 0} onClick={() => void move(file.id, -1)} />
                  <Button size="small" icon={<ArrowDownOutlined />} disabled={index === files.length - 1} onClick={() => void move(file.id, 1)} />
                  {file.download_ready && (
                    <Button
                      size="small"
                      icon={<DownloadOutlined />}
                      onClick={() => void download(`/api/batch-files/${file.id}/download`, `${file.original_name.replace(/\.(xls|xlsx)$/i, "")}_交货处理.xlsx`)}
                    >
                      下载
                    </Button>
                  )}
                </Space>
              )
            }
          ]}
        />
      </Card>

      <Card
        title="待处理审校与拆分"
        className="section-card"
        extra={
          <Space>
            <Button
              icon={<ExportOutlined />}
              disabled={batch.status !== "succeeded"}
              loading={action === "export"}
              onClick={() => void startExport()}
            >
              生成导出
            </Button>
            {batch.download_ready && (
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                onClick={() => void download(`/api/batches/${batch.id}/download`, `${batch.name}.zip`)}
              >
                下载批次 ZIP
              </Button>
            )}
          </Space>
        }
      >
        <Table<DeliveryException>
          rowKey="id"
          dataSource={exceptions}
          columns={[
            { title: "SKU", dataIndex: "sku" },
            { title: "站点", dataIndex: "full_site" },
            { title: "目的仓", dataIndex: "destination" },
            { title: "待处理量", dataIndex: "manual_quantity", width: 110 },
            { title: "原因", dataIndex: "reason" },
            { title: "审校状态", dataIndex: "status", width: 110 },
            {
              title: "操作",
              width: 100,
              render: (_, record) => <Button type="link" onClick={() => openSplit(record)}>拆分审校</Button>
            }
          ]}
        />
      </Card>

      <Modal
        title={`拆分审校 · ${splitTarget?.sku ?? ""}`}
        width={900}
        open={splitTarget !== null}
        onCancel={() => setSplitTarget(null)}
        onOk={() => void saveSplit()}
        okText="保存拆分"
        confirmLoading={action === "split"}
      >
        <div className="split-total">
          原待处理量：<strong>{splitTarget?.manual_quantity ?? 0}</strong>；当前拆分合计：
          <strong className={splitTotal === splitTarget?.manual_quantity ? "conservation-ok" : "conservation-bad"}>{splitTotal}</strong>
        </div>
        <Form form={splitForm} layout="vertical">
          <Form.List name="parts">
            {(fields, { add, remove }) => (
              <Space direction="vertical" style={{ width: "100%" }}>
                {fields.map((field, index) => (
                  <Card key={field.key} size="small" title={`拆分 ${index + 1}`} extra={fields.length > 1 ? <Popconfirm title="删除此拆分？" onConfirm={() => remove(field.name)}><Button danger type="link">删除</Button></Popconfirm> : null}>
                    <Space wrap align="start">
                      <Form.Item name={[field.name, "quantity"]} label="数量" rules={[{ required: true }]}>
                        <InputNumber min={1} precision={0} />
                      </Form.Item>
                      <Form.Item name={[field.name, "destination"]} label="目的仓">
                        <Input style={{ width: 180 }} />
                      </Form.Item>
                      <Form.Item name={[field.name, "site"]} label="完整站点">
                        <Input style={{ width: 220 }} />
                      </Form.Item>
                      <Form.Item name={[field.name, "sku"]} label="SKU">
                        <Input style={{ width: 150 }} />
                      </Form.Item>
                      <Form.Item name={[field.name, "supplier_code"]} label="供应商编码">
                        <Input style={{ width: 150 }} />
                      </Form.Item>
                      <Form.Item name={[field.name, "resolved"]} label="可正式导入" valuePropName="checked">
                        <Switch />
                      </Form.Item>
                    </Space>
                    <Form.Item name={[field.name, "delivery_note"]} label="交货备注">
                      <Input />
                    </Form.Item>
                  </Card>
                ))}
                <Button block type="dashed" icon={<PlusOutlined />} onClick={() => add({ quantity: 1, resolved: false })}>
                  增加拆分
                </Button>
              </Space>
            )}
          </Form.List>
        </Form>
      </Modal>
    </div>
  );
}