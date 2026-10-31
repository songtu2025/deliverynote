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
      const result = await preflightBatch(batchId);
      await load(true);
      if (result.workflow === "self_operated_inbound") message.info("已提交后台预检，正在获取历史并核对累计实收");
      else message.success("预检通过");
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
      message.info("已开始计算");
    });

  const startExport = () =>
    runAction("export", async () => {
      await startBatchJob(batchId, "export");
      await load(true);
      message.info("正在生成结果");
    });

  const downloadResult = (path: string, filename: string) => runAction("download", () => download(path, filename));

  return { preflight, refreshSupplierVersion, compute, startExport, downloadResult };
}
