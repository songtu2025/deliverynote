import { Tooltip } from "antd";
import { candidateSites } from "./reviewDraft";

export function EvidenceMetrics({ metrics, state }: { metrics: [string, number][]; state?: string }) {
  return (
    <div className="exception-evidence-cell">
      {metrics.map(([label, value]) => (
        <span className="exception-evidence-metric" aria-label={`${label} ${value}`} key={label}>
          <span>{label} </span>
          <strong>{value}</strong>
        </span>
      ))}
      {state && <span className="exception-evidence-state">{state}</span>}
    </div>
  );
}

export function CandidateEvidence({ fullSite }: { fullSite: string }) {
  return (
    <div className="exception-evidence-cell">
      <strong className="exception-evidence-label">候选站点</strong>
      <div className="exception-evidence-sites">
        {candidateSites(fullSite).map((site) => (
          <span className="exception-evidence-site" key={site}>
            {site}
          </span>
        ))}
      </div>
    </div>
  );
}

export function DocumentEvidence({ documentNote = "" }: { documentNote?: string }) {
  if (!documentNote.trim())
    return <div className="exception-evidence-cell">来源文件未提供交货单号，请核对交货单号、SKU 和站点</div>;
  const text = `交货单号 ${documentNote} 下无此 SKU、站点的入库单`;
  if (documentNote.length <= 32) return <div className="exception-evidence-cell">{text}</div>;
  return (
    <Tooltip title={text} trigger={["hover", "focus"]}>
      <span className="exception-evidence-cell" tabIndex={0}>
        交货单号 {documentNote.slice(0, 32)}… 下无此 SKU、站点的入库单
      </span>
    </Tooltip>
  );
}
