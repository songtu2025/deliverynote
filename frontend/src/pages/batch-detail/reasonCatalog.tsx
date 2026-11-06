import type { ReactNode } from "react";
import type { DeliveryException } from "../../types";
import { CandidateEvidence, DocumentEvidence, EvidenceMetrics } from "./reasonEvidence";

interface ReasonContext {
  hasOverreceiptRule: boolean;
  documentNote?: string;
  selfOperated?: boolean;
}

interface Guidance {
  title?: string;
  metrics?: [string, number | null][];
  message: string;
  help?: { label: string; title: string };
}

interface ReasonDefinition {
  reason: string;
  evidence: (record: DeliveryException, context: ReasonContext) => ReactNode;
  guidance: (record: DeliveryException, context: ReasonContext) => Guidance;
  actions: ("site" | "versions" | "refresh")[];
}

type KnownReasonCode = Exclude<DeliveryException["reason_code"], "unknown">;

function hasExactBreakdown(record: DeliveryException): record is DeliveryException & {
  purchase_allocated_quantity: number;
  overreceipt_allocated_quantity: number;
  overreceipt_remaining_quantity: number;
} {
  return (
    record.purchase_allocated_quantity !== null &&
    record.overreceipt_allocated_quantity !== null &&
    record.overreceipt_remaining_quantity !== null
  );
}

export const reasonCatalog: Record<KnownReasonCode, ReasonDefinition> = {
  product_not_found: {
    reason: "产品信息未匹配",
    evidence: (record) =>
      `${record.original_site.trim() ? `原始站点 ${record.original_site}` : "无原始站点"}：锁定商品资料无此 SKU 的该站点记录`,
    guidance: () => ({
      title: "处理建议",
      message:
        "批次锁定了创建时的商品资料，其中缺少该 SKU 的这个站点。在基础资料补充后需新建批次才会生效；本批可先线下处理。"
    }),
    actions: ["versions"]
  },
  ambiguous_product_site: {
    reason: "产品信息站点不唯一",
    evidence: (record) => <CandidateEvidence fullSite={record.full_site} />,
    guidance: (_record, context) => ({
      message: "选择候选站点",
      help: {
        label: "站点选择说明",
        title: context.selfOperated
          ? "存在多个候选站点，请选择正确站点后按调整重算整个批次。"
          : "选择正确的站点后即可导入。"
      }
    }),
    actions: ["site"]
  },
  purchase_balance_exceeded: {
    reason: "超出采购未交量",
    evidence: (record, context) => (
      <EvidenceMetrics
        metrics={[
          ["已分配", record.allocated_quantity],
          ["超出", record.manual_quantity]
        ]}
        state={context.hasOverreceiptRule ? "未命中超收规则" : "本批次未启用超收规则"}
      />
    ),
    guidance: (record, context) => ({
      title: "采购量与超出量",
      metrics: [
        ["已分配量", record.allocated_quantity],
        ["超出量", record.manual_quantity]
      ],
      message: context.hasOverreceiptRule ? "未命中本批次超收规则" : "本批次未启用超收规则",
      help: {
        label: "超收规则说明",
        title: context.hasOverreceiptRule
          ? "请核对该 SKU 的规模定位、规则额度和允许超收仓库；未命中的数量继续保留为待处理。"
          : "本批次按正常采购未交量分配，超出部分继续保留为待处理。"
      }
    }),
    actions: []
  },
  purchase_not_found: {
    reason: "未找到可交货采购需求",
    evidence: () => (
      <div className="exception-evidence-cell exception-evidence-check">
        <strong>需核对 </strong>
        <span>供应商、SKU、站点、目的仓</span>
      </div>
    ),
    guidance: () => ({
      message: "核对锁定采购版本",
      help: { label: "采购核对说明", title: "锁定的采购数据里没有这个 SKU 的未交量，请核对供应商、站点和目的仓。" }
    }),
    actions: []
  },
  overreceipt_limit_exceeded: {
    reason: "超出允许超收量",
    evidence: (record) =>
      hasExactBreakdown(record) ? (
        <EvidenceMetrics
          metrics={[
            ["正常采购", record.purchase_allocated_quantity],
            ["使用超收", record.overreceipt_allocated_quantity],
            ["剩余", record.overreceipt_remaining_quantity]
          ]}
        />
      ) : (
        <div className="exception-evidence-cell">
          <span className="exception-evidence-state">历史批次暂无额度明细</span>
        </div>
      ),
    guidance: (record) => ({
      title: "超收额度使用情况",
      metrics: [
        ["正常采购分配", record.purchase_allocated_quantity],
        ["本条使用超收额度", record.overreceipt_allocated_quantity],
        ["剩余额度", record.overreceipt_remaining_quantity]
      ],
      message: hasExactBreakdown(record) ? "本批次共享超收额度已用尽" : "历史批次暂无额度明细",
      help: {
        label: "超收额度说明",
        title: hasExactBreakdown(record)
          ? "超收额度已被前面的文件用完，超出部分保留待处理。"
          : "该记录生成时尚未保存正常采购与超收额度的分配构成，页面不会用规则上限倒推。"
      }
    }),
    actions: []
  },
  inbound_order_not_found: {
    reason: "未找到自营仓入库单",
    evidence: (_record, context) => <DocumentEvidence documentNote={context.documentNote} />,
    guidance: () => ({
      title: "处理建议",
      message:
        "锁定待入库数据中没有对应交货单号、SKU 和站点的入库单。请在积加核对关联交货单和商品站点后「同步积加入库记录」，或线下处理。"
    }),
    actions: ["refresh"]
  },
  supplier_mismatch: {
    reason: "供应商不一致",
    evidence: () => "入库单供应商与来源文件供应商不一致，请核对供应商名称",
    guidance: () => ({
      title: "处理建议",
      message:
        "匹配到的入库单供应商与来源文件不一致。请核对供应商资料及积加入库单的供应商名称，修正后「同步积加入库记录」，或线下处理。"
    }),
    actions: ["refresh"]
  },
  po_name_missing: {
    reason: "PO名称为空",
    evidence: () => "入库单 PO 名称为空，请核对关联采购单",
    guidance: () => ({
      title: "处理建议",
      message: "入库单缺少关联采购单，无法完成分配。请在积加补充关联采购单后「同步积加入库记录」，或线下处理。"
    }),
    actions: ["refresh"]
  },
  receivable_invalid: {
    reason: "应收货无效",
    evidence: () => "入库单应收货数量无效，请核对应收货字段是否为非负整数",
    guidance: () => ({
      title: "处理建议",
      message: "入库单应收货数量不是有效的非负整数。请在积加核对应收货字段并修正后「同步积加入库记录」，或线下处理。"
    }),
    actions: ["refresh"]
  },
  receivable_exceeded: {
    reason: "超出应收货",
    evidence: (record) => (
      <EvidenceMetrics
        metrics={[
          ["已分配", record.allocated_quantity],
          ["超出", record.manual_quantity]
        ]}
      />
    ),
    guidance: () => ({
      title: "处理建议",
      message:
        "本次申请超出本批可分配的应收货余额。请核对入库单应收货数量和前序文件分配，剩余数量可线下处理或转交货批次。"
    }),
    actions: []
  }
};

const unknownReason: ReasonDefinition = {
  reason: "未知原因",
  evidence: (record) => `${record.reason}：未登记的原因，请联系维护人员`,
  guidance: (record) => ({ title: "处理建议", message: `${record.reason}：未登记的原因，请联系维护人员` }),
  actions: []
};

export function getReasonDefinition(codeOrReason: string): ReasonDefinition {
  if (Object.hasOwn(reasonCatalog, codeOrReason)) return reasonCatalog[codeOrReason as KnownReasonCode];
  return Object.values(reasonCatalog).find((item) => item.reason === codeOrReason) ?? unknownReason;
}
