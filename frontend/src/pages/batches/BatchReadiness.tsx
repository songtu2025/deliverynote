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
  return (
    <section className="batch-status-strip" aria-label="运行状态">
      <div className={`batch-status-item${ready ? " is-ready" : " is-warning"}`}>
        <span>基础资料</span>
        <strong>
          {versionKinds.length - missingKinds.length} / {versionKinds.length} {ready ? "已就绪" : "待补齐"}
        </strong>
        <small>{ready ? "可创建新批次" : `缺少：${missingKinds.map((kind) => kind.label).join("、")}`}</small>
      </div>
      <div className="batch-status-item">
        <span>{workflow === "self_operated_inbound" ? "待入库数据" : "采购数据"}</span>
        <strong>
          {activeVersions[workflow === "self_operated_inbound" ? "self_operated_inbound" : "purchase"]
            ? "已启用"
            : "待同步"}
        </strong>
        <small>
          {activeVersions[workflow === "self_operated_inbound" ? "self_operated_inbound" : "purchase"]?.name ??
            "暂无启用版本"}
        </small>
      </div>
      <div className="batch-status-item">
        <span>超收规则</span>
        <strong>
          {(workflow === "self_operated_inbound" ? activeSelfOperatedRule : activeOverreceiptRule)
            ? "已启用"
            : "未启用"}
        </strong>
        <small>
          {workflow === "self_operated_inbound"
            ? activeSelfOperatedRule
              ? `${activeSelfOperatedRule.name} · ${activeSelfOperatedRule.allowance} 件`
              : "新批次超收数量为 0"
            : (activeOverreceiptRule?.name ?? "新批次不会自动超收")}
        </small>
      </div>
    </section>
  );
}
