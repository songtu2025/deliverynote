import { api } from "./api";
import type { OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "./types";

export type RuleScope = "delivery" | "self_operated";
export type RuleForm = {
  name: string;
  short_tail_limit: number;
  medium_tail_limit: number;
  long_tail_limit: number;
  allowed_warehouses: string[];
};
export type SelfOperatedRuleForm = { name: string; allowance: number };

type RuleVersions = { delivery: OverreceiptRuleVersion; self_operated: SelfOperatedOverreceiptRuleVersion };
type RuleForms = { delivery: RuleForm; self_operated: SelfOperatedRuleForm };

function rulePath(scope: RuleScope) {
  return scope === "delivery" ? "/api/overreceipt-rule-versions" : "/api/self-operated-overreceipt-rule-versions";
}

export function getOverreceiptRules(workflow: "delivery"): Promise<OverreceiptRuleVersion[]>;
export function getOverreceiptRules(workflow: "self_operated_inbound"): Promise<SelfOperatedOverreceiptRuleVersion[]>;
export function getOverreceiptRules(
  workflow: "delivery" | "self_operated_inbound"
): Promise<OverreceiptRuleVersion[] | SelfOperatedOverreceiptRuleVersion[]>;
export function getOverreceiptRules(workflow: "delivery" | "self_operated_inbound") {
  return workflow === "self_operated_inbound"
    ? api<SelfOperatedOverreceiptRuleVersion[]>(rulePath("self_operated"))
    : api<OverreceiptRuleVersion[]>(rulePath("delivery"));
}

export function getRuleWarehouses() {
  return api<string[]>(`${rulePath("delivery")}/warehouses`);
}

export function publishOverreceiptRule<S extends RuleScope>(scope: S, values: RuleForms[S]) {
  return api<RuleVersions[S]>(rulePath(scope), { method: "POST", body: JSON.stringify(values) });
}

export function activateOverreceiptRule(scope: RuleScope, id: number) {
  return api(`${rulePath(scope)}/${id}/activate`, { method: "POST" });
}

export function renameOverreceiptRule<S extends RuleScope>(scope: S, id: number, name: string) {
  return api<RuleVersions[S]>(`${rulePath(scope)}/${id}/name`, { method: "PUT", body: JSON.stringify({ name }) });
}
