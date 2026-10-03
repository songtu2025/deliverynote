import type { OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "../../types";

export type RuleScope = "delivery" | "self_operated";

export type RenameRuleTarget =
  | { scope: "delivery"; rule: OverreceiptRuleVersion }
  | { scope: "self_operated"; rule: SelfOperatedOverreceiptRuleVersion };
