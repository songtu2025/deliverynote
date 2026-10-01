import { Alert, AutoComplete, Button, Drawer, Form, Input, Modal, Typography } from "antd";
import type { FormInstance } from "antd";

import type { PositionDraftRow } from "../../types";
import type { PositionRowValues } from "./positionDraftApi";
import type { usePositionRowEditor } from "./usePositionRowEditor";

const SCALE_OPTIONS = ["短尾", "中尾", "长尾"].map((value) => ({ value }));

export function RowEditorDrawer({
  open,
  editingRow,
  form,
  saving,
  conflicted,
  onDirty,
  onClose,
  onSave,
  leaveConfirmation,
  busy
}: {
  open: boolean;
  editingRow: PositionDraftRow | null;
  form: FormInstance<PositionRowValues>;
  saving: boolean;
  conflicted: boolean;
  onDirty: () => void;
  onClose: () => void;
  onSave: () => void;
  leaveConfirmation: Pick<ReturnType<typeof usePositionRowEditor>, "pendingLeave" | "confirmLeave" | "cancelLeave">;
  busy: boolean;
}) {
  return (
    <>
      <Drawer
        title={editingRow ? `编辑库位记录：${editingRow.jiaji_sku}` : "新增库位记录"}
        size={680}
        rootClassName="position-row-drawer"
        classNames={{
          header: "position-row-drawer-header",
          body: "position-row-drawer-body",
          footer: "position-row-drawer-footer"
        }}
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
          styles={{ root: { borderRadius: 8 } }}
          type="info"
          showIcon
          title="保存后立即写入服务器草稿"
          description="店铺-站点和积加 SKU 为必填；其他字段保留现有自定义文本。"
        />
        <Form<PositionRowValues> className="position-row-form" form={form} layout="vertical" onValuesChange={onDirty}>
          <div className="position-row-field-grid">
            <Form.Item
              className="position-row-field"
              label="店铺-站点"
              name="store_site"
              extra={<span className="position-row-field-help">用于与待处理数据的站点精确匹配，例如 SEEKWAY:US。</span>}
              rules={[{ required: true, whitespace: true, message: "请输入店铺-站点" }]}
            >
              <Input aria-label="店铺-站点" placeholder="例如：SEEKWAY:US" />
            </Form.Item>
            <Form.Item
              className="position-row-field"
              label="积加 SKU"
              name="jiaji_sku"
              extra={<span className="position-row-field-help">与店铺-站点共同组成主要匹配键。</span>}
              rules={[{ required: true, whitespace: true, message: "请输入积加 SKU" }]}
            >
              <Input aria-label="积加 SKU" placeholder="例如：SKU-A" />
            </Form.Item>
            <Form.Item
              className="position-row-field"
              label="MSKU（可选）"
              name="msku"
              extra={
                <span className="position-row-field-help">同一站点和积加 SKU 有多行时，MSKU 必须填写且唯一。</span>
              }
            >
              <Input aria-label="MSKU" placeholder="可留空" />
            </Form.Item>
            <Form.Item
              className="position-row-field"
              label="规模定位（可选）"
              name="scale_position"
              extra={
                <span className="position-row-field-help">常用值为短尾、中尾、长尾；已有自定义值可以继续保留。</span>
              }
            >
              <AutoComplete aria-label="规模定位" options={SCALE_OPTIONS} placeholder="选择常用值或输入自定义值" />
            </Form.Item>
            <Form.Item
              className="position-row-field"
              label="备货定位（可选）"
              name="stocking_position"
              extra={<span className="position-row-field-help">用于补充待处理导出中的备货定位。</span>}
            >
              <Input aria-label="备货定位" placeholder="例如：备货" />
            </Form.Item>
          </div>
        </Form>
      </Drawer>
      {/* 抽屉一起关闭时由抽屉恢复外部焦点，避免弹窗抢回已销毁的表单控件。 */}
      <Modal
        title="放弃未保存的表单修改？"
        destroyOnHidden
        focusable={{ focusTriggerAfterClose: open }}
        open={leaveConfirmation.pendingLeave !== null}
        okText={leaveConfirmation.pendingLeave === "back" ? "放弃并返回" : "放弃修改"}
        cancelText="继续编辑"
        okButtonProps={{ danger: true, disabled: busy }}
        cancelButtonProps={{ disabled: busy }}
        onOk={leaveConfirmation.confirmLeave}
        onCancel={leaveConfirmation.cancelLeave}
      >
        <Typography.Paragraph>右侧编辑面板中的内容尚未保存到服务器，离开后无法恢复。</Typography.Paragraph>
      </Modal>
    </>
  );
}
