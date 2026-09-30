import { Alert, AutoComplete, Button, Drawer, Form, Input } from "antd";
import type { FormInstance } from "antd";

import type { PositionDraftRow } from "../../types";
import type { PositionRowValues } from "./positionDraftApi";

const SCALE_OPTIONS = ["短尾", "中尾", "长尾"].map((value) => ({ value }));

export function RowEditorDrawer({
  open,
  editingRow,
  form,
  saving,
  conflicted,
  onDirty,
  onClose,
  onSave
}: {
  open: boolean;
  editingRow: PositionDraftRow | null;
  form: FormInstance<PositionRowValues>;
  saving: boolean;
  conflicted: boolean;
  onDirty: () => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <Drawer
      title={editingRow ? `编辑库位记录：${editingRow.jiaji_sku}` : "新增库位记录"}
      size={680}
      rootClassName="position-row-drawer"
      open={open}
      destroyOnHidden
      closable={!saving}
      keyboard={!saving}
      maskClosable={false}
      onClose={() => {
        if (!saving) onClose();
      }}
      footer={
        <div className="drawer-footer">
          <Button disabled={saving} onClick={onClose}>
            取消
          </Button>
          <Button type="primary" loading={saving} disabled={conflicted} onClick={onSave}>
            保存到草稿
          </Button>
        </div>
      }
    >
      <Alert
        className="inline-alert"
        type="info"
        showIcon
        title="保存后立即写入服务器草稿"
        description="店铺-站点和积加 SKU 为必填；其他字段保留现有自定义文本。"
      />
      <Form<PositionRowValues> className="position-row-form" form={form} layout="vertical" onValuesChange={onDirty}>
        <div className="position-row-field-grid">
          <Form.Item
            label="店铺-站点"
            name="store_site"
            extra="用于与待处理数据的站点精确匹配，例如 SEEKWAY:US。"
            rules={[{ required: true, whitespace: true, message: "请输入店铺-站点" }]}
          >
            <Input aria-label="店铺-站点" placeholder="例如：SEEKWAY:US" />
          </Form.Item>
          <Form.Item
            label="积加 SKU"
            name="jiaji_sku"
            extra="与店铺-站点共同组成主要匹配键。"
            rules={[{ required: true, whitespace: true, message: "请输入积加 SKU" }]}
          >
            <Input aria-label="积加 SKU" placeholder="例如：SKU-A" />
          </Form.Item>
          <Form.Item label="MSKU（可选）" name="msku" extra="同一站点和积加 SKU 有多行时，MSKU 必须填写且唯一。">
            <Input aria-label="MSKU" placeholder="可留空" />
          </Form.Item>
          <Form.Item
            label="规模定位（可选）"
            name="scale_position"
            extra="常用值为短尾、中尾、长尾；已有自定义值可以继续保留。"
          >
            <AutoComplete aria-label="规模定位" options={SCALE_OPTIONS} placeholder="选择常用值或输入自定义值" />
          </Form.Item>
          <Form.Item label="备货定位（可选）" name="stocking_position" extra="用于补充待处理导出中的备货定位。">
            <Input aria-label="备货定位" placeholder="例如：备货" />
          </Form.Item>
        </div>
      </Form>
    </Drawer>
  );
}
