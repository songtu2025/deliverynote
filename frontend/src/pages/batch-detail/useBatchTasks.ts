import { App as AntApp } from "antd";
import { api, download } from "../../api";
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

  const preflightAndCompute = () =>
    runAction("preflight-compute", async () => {
      const result = await preflightBatch(batchId);
      if (result.status !== "preflight_ready") {
        await load(true);
        return;
      }
      try {
        await startBatchJob(batchId, "compute");
      } catch (error) {
        // 刷新失败时仍向用户提示原始的计算启动错误。
        await load(true).catch(() => undefined);
        throw error;
      }
      await load(true);
      message.info("预检通过，已开始计算");
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

  const refreshHistory = () =>
    runAction("refresh-history", async () => {
      await api(`/api/batches/${batchId}/receipts/refresh`, { method: "POST" });
      await load(true);
      message.info("已重新排队获取历史，原计算与导出已失效");
    });

  return {
    preflight,
    preflightAndCompute,
    refreshSupplierVersion,
    compute,
    startExport,
    downloadResult,
    refreshHistory
  };
}
