import { Button, Space, Tooltip } from "antd";
import type { InboundAdjustments } from "./useInboundAdjustments";

export default function InboundAdjustmentActions({ adjustments }: { adjustments: InboundAdjustments }) {
  if (!adjustments.count) return null;
  return (
    <Space wrap>
      <Tooltip title={adjustments.disabledReason} trigger={["hover", "focus"]}>
        <span tabIndex={adjustments.disabledReason ? 0 : undefined}>
          <Button
            type="primary"
            loading={adjustments.busy}
            disabled={Boolean(adjustments.disabledReason)}
            onClick={() => void adjustments.submit()}
          >
            按调整重算（{adjustments.count} 处）
          </Button>
        </span>
      </Tooltip>
      <Button disabled={adjustments.busy} onClick={adjustments.discard}>
        放弃修改
      </Button>
    </Space>
  );
}
