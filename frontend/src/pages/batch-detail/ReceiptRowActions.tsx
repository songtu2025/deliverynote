import { Button, Select, Space, Tooltip } from "antd";
import type { ReceiptRow } from "./ReceiptReviewDetails";
import { inboundRowActions } from "./inboundRowActions";
import ReceiptRefreshButton from "./ReceiptRefreshButton";

type ActionRow = Pick<ReceiptRow, "file_id" | "sku" | "original_site" | "issue" | "reason" | "candidates">;

export default function ReceiptRowActions({
  row,
  computed = false,
  disabledReason,
  refreshing,
  siteValue,
  onChooseSite,
  onRefresh,
  onVersions,
  onOpen
}: {
  row: ActionRow;
  computed?: boolean;
  disabledReason: string | null;
  refreshing: boolean;
  siteValue?: string;
  onChooseSite: (row: ActionRow, site: string) => Promise<void> | void;
  onRefresh?: () => Promise<void>;
  onVersions?: () => void;
  onOpen?: () => void;
}) {
  const actions = inboundRowActions(row.reason || row.issue, computed, row.candidates);
  return (
    <Space wrap size="small">
      {actions.includes("site") && (
        <ReceiptSiteSelect row={row} value={siteValue} disabledReason={disabledReason} onChooseSite={onChooseSite} />
      )}
      {actions.includes("versions") && (
        <Button type={computed ? "link" : "default"} onClick={onVersions}>
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

function ReceiptSiteSelect({
  row,
  value,
  disabledReason,
  onChooseSite
}: {
  row: ActionRow;
  value?: string;
  disabledReason: string | null;
  onChooseSite: (row: ActionRow, site: string) => Promise<void> | void;
}) {
  return (
    <Tooltip title={disabledReason} trigger={["hover", "focus"]}>
      <span tabIndex={disabledReason ? 0 : undefined}>
        <Select<string>
          aria-label="选择站点"
          value={value ?? null}
          placeholder="选择站点"
          style={{ width: 210 }}
          disabled={Boolean(disabledReason)}
          options={row.candidates.map((candidate) => ({ value: candidate, label: candidate }))}
          onChange={(site) => void onChooseSite(row, site)}
        />
      </span>
    </Tooltip>
  );
}
