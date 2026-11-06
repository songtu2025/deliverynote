import { getReasonDefinition } from "./reasonCatalog";

type InboundRowAction = "site" | "versions" | "refresh";

export function inboundRowActions(reason: string, computed: boolean, candidates: string[] = []): InboundRowAction[] {
  const [action] = getReasonDefinition(reason).actions;
  if (action === "site" && !candidates.length) return [];
  if (computed && action === "refresh") return [];
  return action ? [action] : [];
}
