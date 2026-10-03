import type { DeliveryException, SplitPart } from "../../types";
import { REVIEW_PAGE_SIZE } from "../../batchDetailApi";

export function candidateSites(fullSite: string): string[] {
  return Array.from(
    new Set(
      fullSite
        .split("、")
        .map((site) => site.trim())
        .filter(Boolean)
    )
  );
}

export function initialSplitPart(exception: DeliveryException, quantity = exception.manual_quantity): SplitPart {
  return {
    quantity,
    destination: exception.destination,
    site: exception.full_site.includes("、") ? "" : exception.full_site,
    supplier_code: "",
    sku: exception.sku,
    delivery_note: exception.reason,
    resolved: false
  };
}

export function summarizeSplit(target: DeliveryException | null, parts: SplitPart[]) {
  const total = parts.reduce((sum, part) => sum + Number(part?.quantity ?? 0), 0);
  const remaining = (target?.manual_quantity ?? 0) - total;
  const valid = Boolean(
    target && parts.length && remaining === 0 && parts.every((part) => Number(part?.quantity ?? 0) > 0)
  );
  return { total, remaining, valid };
}

export function reviewNeighbors(
  target: DeliveryException | null,
  items: DeliveryException[],
  page: number,
  total: number
) {
  const index = target ? items.findIndex((item) => item.id === target.id) : -1;
  const previous = index > 0 ? items[index - 1] : undefined;
  const next = index >= 0 ? items[index + 1] : undefined;
  return {
    index,
    previous,
    next,
    canPrevious: Boolean(previous || page > 1),
    canNext: Boolean(next || page * REVIEW_PAGE_SIZE < total)
  };
}
