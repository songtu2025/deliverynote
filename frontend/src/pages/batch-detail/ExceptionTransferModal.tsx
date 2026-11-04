import { useEffect, useState } from "react";
import { Alert, App, Button, Flex, Form, InputNumber, Modal, Select, Table, Typography } from "antd";
import type { DeliveryException } from "../../types";
import { remainingTransferQuantity, transferExceptions } from "../../exceptionTransferApi";
import type { TransferItem, TransferOptions } from "../../exceptionTransferApi";
import { preflightBatch, startBatchJob } from "../../batchDetailApi";
import TransferPurchaseDetails, { estimateTransfers, transferSiteOptions } from "./TransferPurchaseDetails";
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
  const estimate = estimateTransfers(records, items, sites);
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
      width={1320}
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
      footer={(_, { OkBtn, CancelBtn }) => (
        <Flex justify="space-between" align="center" gap="small" wrap>
          <Typography.Text style={{ fontVariantNumeric: "tabular-nums" }}>
            合计转交 {estimate.total} 件 = 预计可扣 {estimate.available ? estimate.deductible : "—"} + 预计待处理{" "}
            {estimate.available ? estimate.pending : "—"}
          </Typography.Text>
          <Flex gap="small">
            <CancelBtn />
            <OkBtn />
          </Flex>
        </Flex>
      )}
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
          scroll={{ x: 1200, y: "min(440px, calc(100vh - 280px))" }}
          onRow={() => ({ style: { verticalAlign: "middle" } })}
          columns={[
            { title: "SKU", dataIndex: "sku", width: 150 },
            { title: "原站点", dataIndex: "full_site", width: 190 },
            {
              title: "可转",
              width: 56,
              align: "right",
              render: (_, record) => (
                <span style={{ fontVariantNumeric: "tabular-nums" }}>{remainingTransferQuantity(record)}</span>
              )
            },
            {
              title: "转交数量",
              width: 96,
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
                    style={{ width: "100%" }}
                    aria-label={record.sku + " 转交数量"}
                    styles={{ input: { textAlign: "right", fontVariantNumeric: "tabular-nums" } }}
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
              width: 280,
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
                    popupMatchSelectWidth={false}
                    optionFilterProp="value"
                    options={sites[index] ? transferSiteOptions(sites[index]) : []}
                  />
                </Form.Item>
              )
            },
            {
              title: "采购去向",
              render: (_, record, index) => (
                <TransferPurchaseDetails data={sites[index]} site={items?.[index]?.full_site ?? record.full_site} />
              )
            },
            {
              title: "预计",
              width: 150,
              render: (_, __, index) => {
                const row = estimate.rows[index];
                if (!row) return <Typography.Text type="secondary">—</Typography.Text>;
                return (
                  <Typography.Text type={row.pending ? "warning" : "success"}>
                    {row.pending
                      ? `${row.deductible ? `可扣 ${row.deductible}，` : ""}${row.pending} 件进待处理`
                      : "全部可扣"}
                  </Typography.Text>
                );
              }
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
