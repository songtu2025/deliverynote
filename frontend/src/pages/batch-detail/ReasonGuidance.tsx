import DetailHelp from "./DetailHelp";
import { getReasonDefinition } from "./reasonCatalog";
import type { DeliveryException } from "../../types";

export default function ReasonGuidance({
  exception,
  hasOverreceiptRule,
  selfOperated = false
}: {
  exception: DeliveryException;
  hasOverreceiptRule: boolean;
  selfOperated?: boolean;
}) {
  const guidance = getReasonDefinition(exception.reason_code).guidance(exception, { hasOverreceiptRule, selfOperated });
  const content = (
    <>
      {guidance.title && <strong className="review-guidance-title">{guidance.title}</strong>}
      {guidance.metrics && (
        <div
          className={`review-guidance-metrics${guidance.metrics.length === 3 ? " review-guidance-metrics-three" : ""}`}
        >
          {guidance.metrics.map(([label, value]) => (
            <div className="review-guidance-metric" key={label}>
              <span>{label}</span>
              <strong>{value ?? "—"}</strong>
            </div>
          ))}
        </div>
      )}
      <p className="pending-value">
        {guidance.message}
        {guidance.help && <DetailHelp {...guidance.help} />}
      </p>
    </>
  );
  return guidance.title ? (
    <section className="review-guidance" aria-label="原因指导">
      {content}
    </section>
  ) : (
    <div className="review-guidance">{content}</div>
  );
}
