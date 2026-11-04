export type InboundRowAction = "site" | "versions" | "refresh" | "allowance" | "offline" | "transfer";

export function inboundRowActions(
  reason: string,
  computed: boolean,
  options: { candidates?: string[]; remaining?: number } = {}
): InboundRowAction[] {
  const { remaining = 0, candidates = [] } = options;
  if (computed) {
    if (remaining <= 0) return [];
    const actions = computedActions[reason] ?? ["offline", "transfer"];
    return actions.filter((action) => action !== "site" || candidates.length > 0);
  }
  const action = receiptActions[reason];
  if (action === "site" && !candidates.length) return [];
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

const computedActions: Record<string, InboundRowAction[]> = {
  产品信息未匹配: ["versions", "offline"],
  产品信息站点不唯一: ["site", "offline"],
  超出允许超收量: ["allowance", "offline", "transfer"],
  超出应收货: ["allowance", "offline", "transfer"]
};
