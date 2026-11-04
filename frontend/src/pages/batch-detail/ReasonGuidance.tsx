import DetailHelp from "./DetailHelp";
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
  hasOverreceiptRule
}: {
  exception: DeliveryException;
  hasOverreceiptRule: boolean;
}) {
  if (exception.reason_code === "purchase_not_found") {
    return (
      <div className="review-guidance">
        <p className="pending-value">
          核对锁定采购版本
          <DetailHelp
            label="采购核对说明"
            title="锁定的采购数据里没有这个 SKU 的未交量，请核对供应商、站点和目的仓。"
          />
        </p>
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
        <p className="pending-value">
          {hasOverreceiptRule ? "未命中本批次超收规则" : "本批次未启用超收规则"}
          <DetailHelp
            label="超收规则说明"
            title={
              hasOverreceiptRule
                ? "请核对该 SKU 的规模定位、规则额度和允许超收仓库；未命中的数量继续保留为待处理。"
                : "本批次按正常采购未交量分配，超出部分继续保留为待处理。"
            }
          />
        </p>
      </section>
    );
  }

  if (exception.reason_code === "ambiguous_product_site") {
    return (
      <div className="review-guidance">
        <p className="pending-value">
          选择候选站点
          <DetailHelp label="站点选择说明" title="选择正确的站点后即可导入。" />
        </p>
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
      <p className="pending-value">
        {hasExactBreakdown ? "本批次共享超收额度已用尽" : "历史批次暂无额度明细"}
        <DetailHelp
          label="超收额度说明"
          title={
            hasExactBreakdown
              ? "超收额度已被前面的文件用完，超出部分保留待处理。"
              : "该记录生成时尚未保存正常采购与超收额度的分配构成，页面不会用规则上限倒推。"
          }
        />
      </p>
    </section>
  );
}
