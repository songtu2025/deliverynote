import { App } from "antd";
import { chooseReceiptSite } from "../../batchDetailApi";
import type { BatchAction } from "./useBatchAction";

export function useReceiptSite(
  batchId: number,
  runAction: BatchAction,
  load: (silent?: boolean) => Promise<unknown>,
  onSaved: () => void,
  confirmRecompute = false
) {
  const { message, modal } = App.useApp();
  return async (row: Parameters<typeof chooseReceiptSite>[1], site: string) => {
    const save = () =>
      runAction("receipt-site", async () => {
        await chooseReceiptSite(batchId, row, site);
        onSaved();
        await load(true);
        message.info("已保存该文件的站点选择，正在重新核对并计算");
      });
    if (confirmRecompute) {
      modal.confirm({
        title: "选择站点并重新核对整批？",
        content: "将重新核对并计算整批",
        okText: "重新核对",
        cancelText: "取消",
        onOk: save
      });
    } else {
      await save();
    }
  };
}
