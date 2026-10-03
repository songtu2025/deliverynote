import { Alert } from "antd";
import type { DeliveryException } from "../../types";

function GuidanceMetric({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="review-guidance-metric">
      <span>{label}</span>
      <strong>{value ?? "—"}</strong>
    </div>
  );
}

export default function ReasonGuidance({
  exception,
  hasOverreceiptRule,
  selfOperated = false
}: {
  exception: DeliveryException;
  hasOverreceiptRule: boolean;
  selfOperated?: boolean;
}) {
  if (exception.reason_code === "purchase_not_found") {
    return (
      <div className="review-guidance">
        <Alert
          showIcon
          type="warning"
          title="核对锁定采购版本"
          description="请核对本批次锁定采购版本中的供应商、SKU、站点和目的仓，并确认对应采购需求仍有可交货未交量。"
        />
      </div>
    );
  }

  if (exception.reason_code === "purchase_balance_exceeded") {
    return (
      <section className="review-guidance" aria-label="原因指导">
        <strong className="review-guidance-title">采购量与超出量</strong>
        <div className="review-guidance-metrics">
          <GuidanceMetric label="已分配量" value={exception.allocated_quantity} />
          <GuidanceMetric label="超出量" value={exception.manual_quantity} />
        </div>
        <Alert
          showIcon
          type={hasOverreceiptRule ? "warning" : "info"}
          title={hasOverreceiptRule ? "未命中本批次超收规则" : "本批次未启用超收规则"}
          description={
            hasOverreceiptRule
              ? "请核对该 SKU 的规模定位、规则额度和允许超收仓库；未命中的数量继续保留为待处理。"
              : "本批次按正常采购未交量分配，超出部分继续保留为待处理。"
          }
        />
      </section>
    );
  }

  if (exception.reason_code === "ambiguous_product_site") {
    return (
      <div className="review-guidance">
        <Alert
          showIcon
          type="warning"
          title="选择候选站点"
          description={
            selfOperated
              ? "请在下方候选项中选择正确的完整站点。保存后系统会按所选站点重新计算整个批次。"
              : "请在下方候选项中选择正确的完整站点，再将需要导入的处理明细选择为“可正式导入”。"
          }
        />
      </div>
    );
  }

  if (exception.reason_code === "overreceipt_limit_exceeded") {
    return <OverreceiptGuidance exception={exception} />;
  }

  return null;
}

function OverreceiptGuidance({ exception }: { exception: DeliveryException }) {
  const hasExactBreakdown =
    exception.purchase_allocated_quantity !== null &&
    exception.overreceipt_allocated_quantity !== null &&
    exception.overreceipt_remaining_quantity !== null;
  return (
    <section className="review-guidance" aria-label="原因指导">
      <strong className="review-guidance-title">超收额度使用情况</strong>
      <div className="review-guidance-metrics review-guidance-metrics-three">
        <GuidanceMetric label="正常采购分配" value={exception.purchase_allocated_quantity} />
        <GuidanceMetric label="本条使用超收额度" value={exception.overreceipt_allocated_quantity} />
        <GuidanceMetric label="剩余额度" value={exception.overreceipt_remaining_quantity} />
      </div>
      <Alert
        showIcon
        type="warning"
        title={hasExactBreakdown ? "本批次共享超收额度已用尽" : "历史批次暂无额度明细"}
        description={
          hasExactBreakdown
            ? "超收额度按供应商 + SKU + 站点在本批次内共享，前序文件可能已使用部分额度；超过剩余额度的数量继续保留为待处理。"
            : "该记录生成时尚未保存正常采购与超收额度的分配构成，页面不会用规则上限倒推。"
        }
      />
    </section>
  );
}
