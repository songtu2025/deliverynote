import type { Batch } from "../../types";

export type BatchWorkflow = "delivery" | "self_operated_inbound";

export const DELIVERY_VERSION_KINDS = [
  { value: "purchase", label: "采购需求" },
  { value: "product", label: "商品信息" },
  { value: "supplier", label: "供应商资料" },
  { value: "position", label: "MSKU定位" },
  { value: "template", label: "导出模板" }
];

export const SELF_OPERATED_VERSION_KINDS = [
  { value: "product", label: "商品信息" },
  { value: "supplier", label: "供应商资料" },
  { value: "self_operated_inbound", label: "待入库 API 数据" },
  { value: "inbound_template", label: "积加入库模板" }
];

export function nextAction(batch: Batch): string {
  if (batch.status === "draft") {
    if (batch.workflow === "self_operated_inbound") {
      return batch.file_count && batch.inbound_file?.uploaded ? "执行预检" : "上传质检交货单";
    }
    return batch.file_count ? "执行预检" : "上传交货文件";
  }
  if (batch.status === "preflight_ready") return "启动计算";
  if (batch.status === "queued" || batch.status === "running") return "等待后台任务";
  if (batch.status === "failed" || batch.status === "expired") return "查看原因并重试";
  if (batch.download_ready) return "下载结果";
  if ((batch.summary?.manual_total ?? 0) > 0) return "审校待处理";
  return "生成导出";
}

export function canDeleteBatch(batch: Batch): boolean {
  return batch.status !== "queued" && batch.status !== "running";
}
