import { useEffect, useState } from "react";
import { Alert, App, Button, Form, InputNumber, Modal, Select, Table } from "antd";
import type { DeliveryException } from "../../types";
import {
  getTransferPurchases,
  getTransferSites,
  remainingTransferQuantity,
  transferExceptions
} from "../../exceptionTransferApi";
import type { TransferItem } from "../../exceptionTransferApi";

type SiteOptions = { options: { value: string; label: string }[]; purchaseError: string | null };

export default function ExceptionTransferModal({
  batchId,
  records,
  onClose,
  onSuccess
}: {
  batchId: number;
  records: DeliveryException[];
  onClose: () => void;
  onSuccess: (id: number) => void;
}) {
  const [form] = Form.useForm<{ items: TransferItem[] }>();
  const { message } = App.useApp();
  const [sites, setSites] = useState<SiteOptions[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void Promise.all(records.map((record) => loadSites(record.id, controller.signal)))
      .then(
        (result) => {
          if (!controller.signal.aborted) setSites(result);
        },
        (failure: unknown) => {
          if (!controller.signal.aborted) setError(errorMessage(failure));
        }
      )
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [records, attempt]);

  async function submit() {
    const values = await form.validateFields().catch(() => null);
    if (!values || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const items = values.items.map((item, index) => ({ ...item, exception_id: records[index].id }));
      const result = await transferExceptions(batchId, items);
      void message.success("已创建交货批次");
      onSuccess(result.id);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={"转交货批次（" + records.length + " 条）"}
      open
      width={940}
      okText="创建交货批次"
      cancelText="取消"
      confirmLoading={submitting}
      okButtonProps={{ disabled: loading || sites.length !== records.length }}
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
            !sites.length && (
              <Button type="link" onClick={() => setAttempt((value) => value + 1)}>
                重试
              </Button>
            )
          }
        />
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
          scroll={{ x: 820, y: 360 }}
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
              render: (_, record, index) => (
                <Form.Item
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
              width: 300,
              render: (_, record, index) => (
                <Form.Item
                  name={["items", index, "full_site"]}
                  rules={[
                    {
                      validator: (_, value: string) =>
                        sites[index]?.options.some((option) => option.value === value)
                          ? Promise.resolve()
                          : Promise.reject(new Error("请选择商品资料中的完整站点"))
                    }
                  ]}
                  extra={sites[index]?.purchaseError}
                >
                  <Select
                    aria-label={record.sku + " 目标站点"}
                    showSearch
                    optionFilterProp="label"
                    options={sites[index]?.options ?? []}
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

async function loadSites(exceptionId: number, signal: AbortSignal): Promise<SiteOptions> {
  const [sites, purchases] = await Promise.all([
    getTransferSites(exceptionId, signal),
    getTransferPurchases(exceptionId, signal).then(
      (value) => ({ items: value.items, error: null }),
      (failure: unknown) => ({ items: [], error: errorMessage(failure) })
    )
  ]);
  return {
    options: sites.sites.map((site) => ({
      value: site,
      label:
        site +
        "（未交 " +
        (purchases.error
          ? "—"
          : purchases.items
              .filter((item) => item.site === site)
              .reduce((total, item) => total + item.remaining_quantity, 0)) +
        " 件）"
    })),
    purchaseError: purchases.error
  };
}
