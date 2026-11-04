import { Button, Select, Space, Tooltip } from "antd";
import type { ReceiptRow } from "./ReceiptReviewDetails";
import { inboundRowActions } from "./inboundRowActions";
import ReceiptRefreshButton from "./ReceiptRefreshButton";

type ActionRow = Pick<ReceiptRow, "file_id" | "sku" | "original_site" | "issue" | "reason" | "candidates">;

export default function ReceiptRowActions({
  row,
  computed = false,
  remaining,
  disabledReason,
  refreshing,
  onChooseSite,
  onRefresh,
  onVersions,
  onOpen
}: {
  row: ActionRow;
  computed?: boolean;
  remaining?: number;
  disabledReason: string | null;
  refreshing: boolean;
  onChooseSite: (row: ActionRow, site: string) => Promise<void>;
  onRefresh?: () => Promise<void>;
  onVersions?: () => void;
  onOpen?: () => void;
}) {
  const actions = inboundRowActions(row.reason || row.issue, computed, { candidates: row.candidates, remaining });
  return (
    <Space wrap size="small">
      {actions.includes("site") && (
        <Tooltip title={disabledReason} trigger={["hover", "focus"]}>
          <span tabIndex={disabledReason ? 0 : undefined}>
            <Select<string>
              aria-label="选择站点"
              value={null}
              placeholder="选择站点"
              style={{ width: 210 }}
              disabled={Boolean(disabledReason)}
              options={row.candidates.map((value) => ({ value, label: value }))}
              onChange={(site) => void onChooseSite(row, site)}
            />
          </span>
        </Tooltip>
      )}
      {actions.includes("versions") && (
        <Button color="primary" variant="outlined" onClick={onVersions}>
          查看锁定资料
        </Button>
      )}
      {actions.includes("refresh") && onRefresh && (
        <ReceiptRefreshButton inline disabled={refreshing} onConfirm={onRefresh} />
      )}
      {onOpen && (
        <Button type="text" onClick={onOpen}>
          {actions.length ? "查看并处理" : "查看明细"}
        </Button>
      )}
    </Space>
  );
}
