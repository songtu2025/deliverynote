import { api } from "./api";
import type { DeliveryException, Job, SplitPart } from "./types";

export const REVIEW_PAGE_SIZE = 10;

export function saveExceptionSplit(exceptionId: number, parts: SplitPart[]) {
  return api<DeliveryException>(`/api/exceptions/${exceptionId}/split`, {
    method: "PUT",
    body: JSON.stringify({ parts })
  });
}

export function resolveSelfOperatedSite(exceptionId: number, site: string) {
  return api<Job>(`/api/exceptions/${exceptionId}/self-operated-site`, {
    method: "PUT",
    body: JSON.stringify({ full_site: site })
  });
}
