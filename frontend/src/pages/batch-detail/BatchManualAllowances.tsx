import { Collapse, Flex, Typography } from "antd";
import type { Batch } from "../../types";
import { allowanceKey } from "./inboundHandling";
import type { InboundAdjustments } from "./useInboundAdjustments";
import InboundAllowanceInput from "./InboundAllowanceInput";

export default function BatchManualAllowances({
  batch,
  adjustments,
  visibleKeys
}: {
  batch: Batch;
  adjustments: InboundAdjustments;
  visibleKeys: Set<string>;
}) {
  const entries = batch.manual_allowances?.filter(
    (entry) => !visibleKeys.has(allowanceKey(entry.supplier_code, entry))
  );
  if (!entries?.length) return null;
  return (
    <Collapse
      size="small"
      items={[
        {
          key: "allowances",
          label: "已追加额度",
          children: (
            <Flex vertical gap="small">
              <Typography.Text type="secondary">
                当前表格未显示的已追加额度，也可填写 0 后按调整重算撤销。
              </Typography.Text>
              {entries.map((entry) => (
                <Flex key={allowanceKey(entry.supplier_code, entry)} align="center" gap="small" wrap>
                  <Typography.Text>
                    {entry.supplier_name} / {entry.sku} / {entry.full_site}
                  </Typography.Text>
                  <InboundAllowanceInput record={entry} supplierCode={entry.supplier_code} adjustments={adjustments} />
                </Flex>
              ))}
            </Flex>
          )
        }
      ]}
    />
  );
}
