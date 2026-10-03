import type { OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "../../types";

export type RenameRuleTarget =
  | { scope: "delivery"; rule: OverreceiptRuleVersion }
  | { scope: "self_operated"; rule: SelfOperatedOverreceiptRuleVersion };
export type RenameRuleForm = { name: string };
