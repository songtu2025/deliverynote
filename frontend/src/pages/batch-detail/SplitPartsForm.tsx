import { Button, Form, Input, InputNumber, Radio, Space } from "antd";
import { CheckCircleFilled, PlusOutlined } from "@ant-design/icons";
import type { ExceptionEditor } from "./useExceptionEditor";
import { initialSplitPart } from "./reviewDraft";

export default function SplitPartsForm({ editor }: { editor: ExceptionEditor }) {
  const { splitTarget, splitForm, setReviewDirty, splitValid, splitTotal, splitRemaining, splitCandidateSites } =
    editor;
  if (!splitTarget) return null;
  return (
    <>
      <div className={`split-conservation ${splitValid ? "valid" : "invalid"}`}>
        <div>
          <span>原待处理</span>
          <strong>{splitTarget.manual_quantity}</strong>
        </div>
        <div>
          <span>已拆分</span>
          <strong>{splitTotal}</strong>
        </div>
        <div>
          <span>剩余</span>
          <strong>{splitRemaining}</strong>
        </div>
        {splitValid && <CheckCircleFilled aria-label="数量守恒通过" />}
      </div>
      <Form form={splitForm} layout="vertical" onValuesChange={() => setReviewDirty(true)}>
        <Form.List name="parts">
          {(fields, { add, remove }) => (
            <Space orientation="vertical" size={12} style={{ width: "100%" }}>
              {fields.map((field, index) => (
                <div className="split-part" key={field.key}>
                  <div className="split-part-heading">
                    <strong>拆分 {index + 1}</strong>
                    {fields.length > 1 && (
                      <Button danger type="link" size="small" onClick={() => remove(field.name)}>
                        删除
                      </Button>
                    )}
                  </div>
                  <div className="split-fields-row split-primary-fields">
                    <Form.Item
                      name={[field.name, "quantity"]}
                      label="数量"
                      rules={[{ required: true, type: "number", min: 1, message: "数量必须大于 0" }]}
                    >
                      <InputNumber min={1} precision={0} style={{ width: 130 }} />
                    </Form.Item>
                    <Form.Item name={[field.name, "resolved"]} label="处理结果">
                      <Radio.Group className="resolution-choice">
                        <Radio.Button value={true}>可正式导入</Radio.Button>
                        <Radio.Button value={false}>继续保留待处理</Radio.Button>
                      </Radio.Group>
                    </Form.Item>
                  </div>
                  <Form.Item
                    name={[field.name, "destination"]}
                    label="目的仓"
                    rules={[
                      {
                        validator: (_, value) =>
                          splitForm.getFieldValue(["parts", field.name, "resolved"]) && !value
                            ? Promise.reject(new Error("可正式导入部分必须填写目的仓"))
                            : Promise.resolve()
                      }
                    ]}
                  >
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name={[field.name, "site"]}
                    label="完整站点"
                    rules={[
                      {
                        validator: (_, value) =>
                          splitForm.getFieldValue(["parts", field.name, "resolved"]) && !value
                            ? Promise.reject(new Error("可正式导入部分必须填写完整站点"))
                            : Promise.resolve()
                      }
                    ]}
                  >
                    {splitCandidateSites.length > 1 ? (
                      <Radio.Group className="candidate-site-options">
                        {splitCandidateSites.map((site) => (
                          <Radio key={site} value={site}>
                            {site}
                          </Radio>
                        ))}
                      </Radio.Group>
                    ) : (
                      <Input />
                    )}
                  </Form.Item>
                  <div className="split-fields-row">
                    <Form.Item name={[field.name, "sku"]} label="SKU">
                      <Input />
                    </Form.Item>
                    <Form.Item name={[field.name, "supplier_code"]} label="供应商编码">
                      <Input placeholder="默认沿用来源文件" />
                    </Form.Item>
                  </div>
                  <Form.Item name={[field.name, "delivery_note"]} label="交货备注">
                    <Input />
                  </Form.Item>
                </div>
              ))}
              <Button
                block
                type="dashed"
                icon={<PlusOutlined />}
                onClick={() => add(initialSplitPart(splitTarget, splitRemaining > 0 ? splitRemaining : 1))}
              >
                添加拆分{splitRemaining > 0 ? `（剩余 ${splitRemaining}）` : ""}
              </Button>
            </Space>
          )}
        </Form.List>
      </Form>{" "}
    </>
  );
}
