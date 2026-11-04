import { useEffect, useState } from "react";
import { Alert, App, Button, Form, InputNumber, Modal, Select, Table, Typography } from "antd";
import type { DeliveryException } from "../../types";
import { remainingTransferQuantity, transferExceptions } from "../../exceptionTransferApi";
import type { TransferItem, TransferOptions } from "../../exceptionTransferApi";
import { preflightBatch, startBatchJob } from "../../batchDetailApi";
import TransferPurchaseDetails, { transferSiteOptions } from "./TransferPurchaseDetails";
import { formatBeijingDateTime } from "../../dateTime";

export default function ExceptionTransferModal({
  batchId,
  records,
  optionsCache,
  loadOptions,
  onClose,
  onSuccess
}: {
  batchId: number;
  records: DeliveryException[];
  optionsCache: Map<number, TransferOptions>;
  loadOptions: (id: number) => Promise<TransferOptions>;
  onClose: () => void;
  onSuccess: (id: number) => void;
}) {
  const [form] = Form.useForm<{ items: TransferItem[] }>();
  const { message } = App.useApp();
  const [sites, setSites] = useState(() => records.map((record) => optionsCache.get(record.id)));
  const [loading, setLoading] = useState(() => records.some((record) => !optionsCache.has(record.id)));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const items = Form.useWatch("items", form) as TransferItem[] | undefined;
  const queriedAt = sites.find((site) => site?.queried_at)?.queried_at;
  useEffect(() => {
    let active = true;
    setLoading(records.some((record) => !optionsCache.has(record.id)));
    setError(null);
    void Promise.all(records.map((record) => loadOptions(record.id)))
      .then(
        (result) => {
          if (active) setSites(result);
        },
        (failure: unknown) => {
          if (active) setError(errorMessage(failure));
        }
      )
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [records, attempt, optionsCache, loadOptions]);

  async function submit() {
    const values = await form.validateFields().catch(() => null);
    if (!values || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const items = values.items.map((item, index) => ({ ...item, exception_id: records[index].id }));
      const result = await transferExceptions(batchId, items);
      await computeCreatedBatch(result.id);
      onSuccess(result.id);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setSubmitting(false);
    }
  }

  async function computeCreatedBatch(id: number) {
    let preflightReady = false;
    try {
      const result = await preflightBatch(id);
      preflightReady = result.status === "preflight_ready";
      if (preflightReady) await startBatchJob(id, "compute");
      void message.success(preflightReady ? `已创建交货批次 #${id} 并开始计算` : `已创建交货批次 #${id}，预检未通过`);
    } catch (failure) {
      void message.warning(
        `已创建交货批次 #${id}，${preflightReady ? "计算启动失败" : "预检未通过"}：${errorMessage(failure)}`
      );
    }
  }

  return (
    <Modal
      title={"转交货批次（" + records.length + " 条）"}
      open
      width={1100}
      style={{ maxWidth: "calc(100vw - 32px)" }}
      okText="创建交货批次"
      cancelText="取消"
      confirmLoading={submitting}
      okButtonProps={{ disabled: loading || sites.some((site) => !site) }}
      cancelButtonProps={{ disabled: submitting }}
      closable={!submitting}
      mask={{ closable: !submitting }}
      keyboard={!submitting}
      onCancel={onClose}
      onOk={() => void submit()}
    >
      {error && (
        <Alert
          type="error"
          showIcon
          title={error}
          action={
            sites.some((site) => !site) && (
              <Button type="link" onClick={() => setAttempt((value) => value + 1)}>
                重试
              </Button>
            )
          }
        />
      )}
      {queriedAt && (
        <Typography.Text type="secondary">采购数据时间：{formatBeijingDateTime(queriedAt)}</Typography.Text>
      )}
      <Form
        form={form}
        initialValues={{
          items: records.map((record) => ({
            quantity: remainingTransferQuantity(record),
            full_site: record.full_site
          }))
        }}
      >
        <Table<DeliveryException>
          rowKey="id"
          size="small"
          pagination={false}
          loading={loading}
          dataSource={records}
          scroll={{ x: 1000, y: 440 }}
          onRow={() => ({ style: { verticalAlign: "middle" } })}
          expandable={{
            defaultExpandAllRows: true,
            expandedRowRender: (record, index) => {
              const site = items?.[index]?.full_site ?? record.full_site;
              const quantity = records.reduce(
                (total, row, rowIndex) =>
                  row.sku === record.sku && (items?.[rowIndex]?.full_site ?? row.full_site) === site
                    ? total + (Number(items?.[rowIndex]?.quantity ?? remainingTransferQuantity(row)) || 0)
                    : total,
                0
              );
              return <TransferPurchaseDetails data={sites[index]} site={site} quantity={quantity} />;
            }
          }}
          columns={[
            { title: "SKU", dataIndex: "sku", width: 130 },
            { title: "原站点", dataIndex: "full_site", width: 190 },
            {
              title: "剩余可转量",
              width: 100,
              align: "right",
              render: (_, record) => remainingTransferQuantity(record)
            },
            {
              title: "转交数量",
              width: 130,
              align: "right",
              render: (_, record, index) => (
                <Form.Item
                  style={{ marginBottom: 0 }}
                  name={["items", index, "quantity"]}
                  rules={[
                    {
                      validator: (_, value: unknown) =>
                        typeof value === "number" &&
                        Number.isInteger(value) &&
                        value > 0 &&
                        value <= remainingTransferQuantity(record)
                          ? Promise.resolve()
                          : Promise.reject(new Error("请输入剩余量以内的正整数"))
                    }
                  ]}
                >
                  <InputNumber
                    aria-label={record.sku + " 转交数量"}
                    styles={{ input: { textAlign: "right" } }}
                    min={1}
                    max={remainingTransferQuantity(record)}
                    step={1}
                    changeOnBlur={false}
                    onInput={(value) =>
                      form.setFieldValue(["items", index, "quantity"], value.trim() ? Number(value) : null)
                    }
                  />
                </Form.Item>
              )
            },
            {
              title: "目标站点",
              width: 350,
              render: (_, record, index) => (
                <Form.Item
                  style={{ marginBottom: 0 }}
                  name={["items", index, "full_site"]}
                  rules={[
                    {
                      validator: (_, value: string) =>
                        sites[index]?.sites.includes(value)
                          ? Promise.resolve()
                          : Promise.reject(new Error("请选择商品资料中的完整站点"))
                    }
                  ]}
                >
                  <Select
                    aria-label={record.sku + " 目标站点"}
                    showSearch
                    optionFilterProp="value"
                    options={sites[index] ? transferSiteOptions(sites[index]) : []}
                  />
                </Form.Item>
              )
            }
          ]}
        />
      </Form>
    </Modal>
  );
}

function errorMessage(failure: unknown) {
  return failure instanceof Error ? failure.message : "转交失败，请重试";
}
