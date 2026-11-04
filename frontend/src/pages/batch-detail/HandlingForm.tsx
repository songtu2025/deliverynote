import { Button, Flex, Form, Input, InputNumber, Typography } from "antd";
import { useId } from "react";

export type HandlingValues = { quantity: number; reason: string };

export default function HandlingForm({
  title,
  reasonLabel,
  quantity,
  reason,
  max,
  existing,
  busy,
  disabledReason,
  button,
  onSubmit,
  onRevoke
}: {
  title: string;
  reasonLabel: string;
  quantity: number;
  reason: string;
  max?: number;
  existing: boolean;
  busy: boolean;
  disabledReason: string | null;
  button: string;
  onSubmit: (values: HandlingValues) => void;
  onRevoke: () => void;
}) {
  const formId = useId();
  const [form] = Form.useForm<HandlingValues>();
  return (
    <section aria-label={title}>
      <Typography.Text strong>{title}</Typography.Text>
      <Form<HandlingValues>
        form={form}
        name={formId}
        layout="vertical"
        size="small"
        initialValues={{ quantity, reason }}
        disabled={busy || Boolean(disabledReason)}
        onFinish={onSubmit}
      >
        <Flex gap="small" wrap align="start">
          <Form.Item
            label="数量"
            name="quantity"
            rules={[
              { required: true, message: "请输入数量" },
              {
                type: "integer",
                min: 1,
                max,
                message: max === undefined ? "请输入正整数" : `请输入 1 至 ${max} 的整数`
              }
            ]}
          >
            <InputNumber
              min={1}
              max={max}
              changeOnBlur={false}
              style={{ width: 130 }}
              onInput={(value) => form.setFieldValue("quantity", value.trim() ? Number(value) : null)}
            />
          </Form.Item>
          <Form.Item
            label={reasonLabel}
            name="reason"
            style={{ flex: "1 1 220px" }}
            rules={[{ required: true, whitespace: true, message: `请填写${reasonLabel}` }]}
          >
            <Input />
          </Form.Item>
        </Flex>
        <Flex gap="small" align="center" wrap>
          <Button htmlType="submit" loading={busy}>
            {button}
          </Button>
          {existing && <Button onClick={onRevoke}>撤销{title}</Button>}
          {disabledReason && <Typography.Text type="secondary">{disabledReason}</Typography.Text>}
        </Flex>
      </Form>
    </section>
  );
}
