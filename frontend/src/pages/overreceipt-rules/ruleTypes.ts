import type { OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "../../types";

export type RuleScope = "delivery" | "self_operated";

export type RenameRuleTarget =
  | { scope: "delivery"; rule: OverreceiptRuleVersion }
  | { scope: "self_operated"; rule: SelfOperatedOverreceiptRuleVersion };
export type RuleForm = {
  name: string;
  short_tail_limit: number;
  medium_tail_limit: number;
  long_tail_limit: number;
  allowed_warehouses: string[];
};

export type SelfOperatedRuleForm = {
  name: string;
  allowance: number;
};

export type RenameRuleForm = {
  name: string;
};
