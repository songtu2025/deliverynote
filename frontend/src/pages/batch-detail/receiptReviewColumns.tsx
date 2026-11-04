import { Button, Typography } from "antd";
import type { TableColumnsType } from "antd";
import DetailHelp from "./DetailHelp";
import ReceiptRowActions from "./ReceiptRowActions";
import type { ReceiptRow } from "./ReceiptReviewDetails";

export function receiptReviewColumns({
  inline,
  siteDisabledReason,
  refreshing,
  chooseSite,
  onRefresh,
  onVersions,
  onOpen
}: {
  inline: boolean;
  siteDisabledReason: string | null;
  refreshing: boolean;
  chooseSite: (row: ReceiptRow, site: string) => Promise<void>;
  onRefresh?: () => Promise<void>;
  onVersions?: () => void;
  onOpen: (row: ReceiptRow) => void;
}): TableColumnsType<ReceiptRow> {
  return [
    { title: "文件", dataIndex: "filename", ellipsis: true, width: 200 },
    { title: "SKU", dataIndex: "sku", width: 170 },
    { title: "完整站点", dataIndex: "full_site", width: 200, ellipsis: true },
    {
      title: (
        <span>
          累计实收
          <DetailHelp
            label="累计实收口径"
            title="表格「实收数量」按单份 Excel 内的累计实收解释，不跨文件累计。重复计算复用此快照；已完结单据只核算历史。"
          />
        </span>
      ),
      dataIndex: "cumulative",
      width: 115
    },
    { title: "历史已入库", dataIndex: "history", width: 100, render: (value) => value ?? "未确认" },
    { title: "本次申请", dataIndex: "requested", width: 100, render: (value) => value ?? "待核对" },
    {
      title: "核对结果",
      dataIndex: "issue",
      width: 240,
      render: (value, row) => (
        <Typography.Text type={value ? "danger" : row.notice ? "warning" : "secondary"}>
          {value || row.notice || "已核对"}
        </Typography.Text>
      )
    },
    {
      title: "操作",
      width: inline ? 350 : 100,
      fixed: inline ? "right" : undefined,
      render: (_, row) =>
        inline ? (
          <ReceiptRowActions
            row={row}
            disabledReason={siteDisabledReason}
            refreshing={refreshing}
            onChooseSite={(_, site) => chooseSite(row, site)}
            onRefresh={onRefresh}
            onVersions={onVersions}
            onOpen={() => onOpen(row)}
          />
        ) : (
          <Button size="small" onClick={() => onOpen(row)}>
            查看明细
          </Button>
        )
    }
  ];
}
