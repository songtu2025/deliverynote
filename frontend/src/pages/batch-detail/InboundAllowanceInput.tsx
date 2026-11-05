import { InputNumber, Tooltip } from "antd";
import type { AllowanceRecord } from "./inboundHandling";
import type { InboundAdjustments } from "./useInboundAdjustments";

export default function InboundAllowanceInput({
  record,
  supplierCode,
  adjustments
}: {
  record: AllowanceRecord;
  supplierCode: string;
  adjustments: InboundAdjustments;
}) {
  const disabledReason = adjustments.busy ? "正在保存调整" : adjustments.disabledReason;
  return (
    <Tooltip title={disabledReason} trigger={["hover", "focus"]}>
      <span tabIndex={disabledReason ? 0 : undefined}>
        <InputNumber<number>
          aria-label="本批追加"
          min={0}
          precision={0}
          step={1}
          value={adjustments.allowanceValue(record, supplierCode)}
          placeholder="填写数量"
          disabled={Boolean(disabledReason)}
          onChange={(quantity) => adjustments.setAllowance(record, supplierCode, quantity)}
        />
      </span>
    </Tooltip>
  );
}
