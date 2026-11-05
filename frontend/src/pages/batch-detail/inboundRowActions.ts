type InboundRowAction = "site" | "versions" | "refresh";

export function inboundRowActions(reason: string, computed: boolean, candidates: string[] = []): InboundRowAction[] {
  const action = receiptActions[reason];
  if (action === "site" && !candidates.length) return [];
  if (computed && action === "refresh") return [];
  return action ? [action] : [];
}

const receiptActions: Record<string, InboundRowAction> = {
  产品信息站点不唯一: "site",
  产品信息未匹配: "versions",
  未找到自营仓入库单: "refresh",
  供应商不一致: "refresh",
  PO名称为空: "refresh",
  应收货无效: "refresh"
};
