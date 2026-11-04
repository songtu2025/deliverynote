import { Button, Select, Space, Tooltip } from "antd";
import type { ReceiptRow } from "./ReceiptReviewDetails";
import { inboundRowActions } from "./inboundRowActions";
import ReceiptRefreshButton from "./ReceiptRefreshButton";

export default function ReceiptRowActions({
  row,
  disabledReason,
  refreshing,
  onChooseSite,
  onRefresh,
  onVersions,
  onOpen
}: {
  row: ReceiptRow;
  disabledReason: string | null;
  refreshing: boolean;
  onChooseSite: (row: ReceiptRow, site: string) => Promise<void>;
  onRefresh?: () => Promise<void>;
  onVersions?: () => void;
  onOpen: () => void;
}) {
  const actions = inboundRowActions(row.issue, false, { candidates: row.candidates });
  return (
    <Space wrap size="small">
      {actions.includes("site") && (
        <Tooltip title={disabledReason} trigger={["hover", "focus"]}>
          <span tabIndex={disabledReason ? 0 : undefined}>
            <Select
              aria-label="选择站点"
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
      <Button type="text" onClick={onOpen}>
        {actions.length ? "查看并处理" : "查看明细"}
      </Button>
    </Space>
  );
}
