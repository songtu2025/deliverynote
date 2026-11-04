import { App } from "antd";
import { chooseReceiptSite } from "../../batchDetailApi";
import type { ReceiptRow } from "./ReceiptReviewDetails";
import type { BatchAction } from "./useBatchAction";

export function useReceiptSite(
  batchId: number,
  runAction: BatchAction,
  load: (silent?: boolean) => Promise<unknown>,
  onSaved: () => void
) {
  const { message } = App.useApp();
  return (row: ReceiptRow, site: string) =>
    runAction("receipt-site", async () => {
      await chooseReceiptSite(batchId, row, site);
      onSaved();
      await load(true);
      message.info("已保存该文件的站点选择，正在重新核对");
    });
}
