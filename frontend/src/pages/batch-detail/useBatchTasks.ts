import { App as AntApp } from "antd";
import { download } from "../../api";
import { adoptSupplierVersion, preflightBatch, startBatchJob } from "../../batchDetailApi";
import type { BatchDetailData } from "./useBatchDetailData";
import type { BatchAction } from "./useBatchAction";

export function useBatchTasks(batchId: number, data: BatchDetailData, runAction: BatchAction) {
  const { message } = AntApp.useApp();
  const { load, setBatch } = data;
  const preflight = () =>
    runAction("preflight", async () => {
      await preflightBatch(batchId);
      await load(true);
      message.success("所有基础资料和交货文件均已通过预检");
    });

  const refreshSupplierVersion = () =>
    runAction("refresh-supplier-version", async () => {
      const updated = await adoptSupplierVersion(batchId);
      setBatch(updated);
      await load(true);
      message.success("批次已采用当前供应商资料");
    });

  const compute = () =>
    runAction("compute", async () => {
      await startBatchJob(batchId, "compute");
      await load(true);
      message.info("计算任务已提交，可以离开页面，返回后状态会自动恢复");
    });

  const startExport = () =>
    runAction("export", async () => {
      await startBatchJob(batchId, "export");
      await load(true);
      message.info("正在生成导出文件");
    });

  const downloadResult = (path: string, filename: string) => runAction("download", () => download(path, filename));

  return { preflight, refreshSupplierVersion, compute, startExport, downloadResult };
}
