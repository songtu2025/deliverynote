export type InputKind = "purchase" | "product" | "supplier" | "position" | "template";

export interface InputKindDefinition {
  value: InputKind;
  label: string;
  purpose: string;
  impact: string;
  requiredFields: string[];
}

export const INPUT_KIND_DEFINITIONS: readonly InputKindDefinition[] = [
  {
    value: "purchase",
    label: "采购需求",
    purpose: "提供供应商、SKU、站点、目的仓和未交量，是交货匹配与余额扣减的依据。",
    impact: "新批次会锁定当前启用版本；同批次文件按用户顺序连续消耗采购余额。",
    requiredFields: ["单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"]
  },
  {
    value: "product",
    label: "商品信息",
    purpose: "补充商品站点、品类和锁仓标识，用于确认交货商品的匹配关系。",
    impact: "锁仓标识用于解决同一 SKU、站点的歧义，不改变采购余额规则。",
    requiredFields: ["SKU", "店铺/站点", "品类A", "锁仓MKSU"]
  },
  {
    value: "supplier",
    label: "供应商资料",
    purpose: "把交货文件识别为已登记供应商，并提供正式供应商编码。",
    impact: "未能唯一识别供应商会导致批次预检失败，需修正供应商资料或交货文件名后重试。",
    requiredFields: ["供应商编号", "供应商名称", "状态"]
  },
  {
    value: "position",
    label: "库位/排仓数据",
    purpose: "仅用于补充待处理导出的定位信息",
    impact: "不参与采购余额扣减或仓库分配；按店铺-站点与积加 SKU 补充定位字段。",
    requiredFields: ["店铺-站点", "积加SKU", "MSKU", "规模定位", "备货定位", "已下单可售天数"]
  },
  {
    value: "template",
    label: "导出模板",
    purpose: "定义最终交货导入文件的 A:G 表头、样例行格式和样式。",
    impact: "生成单文件结果和批次 ZIP 时使用，必须保持既有七列导出格式兼容。",
    requiredFields: ["*目的仓", "*供应商编码", "*SKU", "*本次交货量", "*站点", "单据备注", "交货备注"]
  }
];

export const INPUT_KIND_BY_VALUE = Object.fromEntries(
  INPUT_KIND_DEFINITIONS.map((definition) => [definition.value, definition])
) as Record<InputKind, InputKindDefinition>;
