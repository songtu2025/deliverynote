import { Button, Collapse, Flex, Tooltip, Typography } from "antd";
import type { Batch } from "../../types";
import { allowanceDisabledReason, allowanceKey } from "./inboundHandling";
import { useSaveInboundAdjustments } from "./useSaveInboundAdjustments";

export default function BatchManualAllowances({ batch, onSaved }: { batch: Batch; onSaved?: () => Promise<unknown> }) {
  const { busy, save } = useSaveInboundAdjustments(batch.id, onSaved);
  const disabledReason = allowanceDisabledReason(batch);
  const entries = batch.manual_allowances;
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
              {entries.map((entry) => (
                <Flex
                  key={JSON.stringify([allowanceKey(entry.supplier_code, entry), entry.inbound_no, entry.po_code])}
                  align="center"
                  gap="small"
                  wrap
                >
                  <Typography.Text>
                    {entry.supplier_name} / {entry.sku} / {entry.full_site}
                    {entry.po_code && " / " + entry.po_code + " / " + entry.inbound_no}：{entry.quantity}
                  </Typography.Text>
                  <Tooltip title={disabledReason} trigger={["hover", "focus"]}>
                    <span tabIndex={disabledReason ? 0 : undefined}>
                      <Button
                        disabled={Boolean(disabledReason)}
                        loading={busy}
                        onClick={() => void save({ allowances: [{ ...entry, quantity: 0 }], sites: [] })}
                      >
                        撤销追加
                      </Button>
                    </span>
                  </Tooltip>
                </Flex>
              ))}
            </Flex>
          )
        }
      ]}
    />
  );
}
