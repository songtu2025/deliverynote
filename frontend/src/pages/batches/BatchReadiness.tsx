import type { InputVersion, OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "../../types";
import type { BatchWorkflow } from "./batchWorkspace";
type Props = {
  workflow: BatchWorkflow;
  activeVersions: Record<string, InputVersion>;
  versionKinds: Array<{ value: string; label: string }>;
  missingKinds: Array<{ value: string; label: string }>;
  activeSelfOperatedRule?: SelfOperatedOverreceiptRuleVersion;
  activeOverreceiptRule?: OverreceiptRuleVersion;
};
export default function BatchReadiness({
  workflow,
  activeVersions,
  versionKinds,
  missingKinds,
  activeSelfOperatedRule,
  activeOverreceiptRule
}: Props) {
  const ready = missingKinds.length === 0;
  const dataVersion = activeVersions[workflow === "self_operated_inbound" ? "self_operated_inbound" : "purchase"];
  const rule = workflow === "self_operated_inbound" ? activeSelfOperatedRule : activeOverreceiptRule;
  return (
    <div className="batch-readiness">
      <div className={`batch-material-item${ready ? "" : " is-warning"}`}>
        <span>基础资料</span>
        <span>
          {versionKinds.length - missingKinds.length}/{versionKinds.length}
        </span>
        {!ready && <span>缺少：{missingKinds.map((kind) => kind.label).join("、")}</span>}
      </div>
      <div className={`batch-material-item${dataVersion ? "" : " is-warning"}`}>
        <span>{workflow === "self_operated_inbound" ? "待入库数据" : "采购数据"}</span>
        <span>{dataVersion?.name ?? "暂无启用版本"}</span>
      </div>
      <div className={`batch-material-item${rule ? "" : " is-warning"}`}>
        <span>超收规则</span>
        <span>
          {workflow === "self_operated_inbound"
            ? activeSelfOperatedRule
              ? `${activeSelfOperatedRule.name} / ${activeSelfOperatedRule.allowance} 件`
              : "新批次超收数量为 0"
            : (activeOverreceiptRule?.name ?? "新批次不会自动超收")}
        </span>
      </div>
    </div>
  );
}
