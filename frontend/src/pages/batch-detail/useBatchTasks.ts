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
      if (result.workflow === "self_operated_inbound") message.info("已提交预检，通过后自动计算");
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
      message.info("已开始同步积加入库记录，完成后自动重新计算");
    });

  const retry = () => {
    const batch = data.batch;
    if (batch?.status === "failed") {
      const prepare = batch.jobs?.prepare;
      const computed = batch.jobs?.compute;
      return computed?.status === "failed" && prepare?.status !== "failed" ? compute() : preflight();
    }
    return startExport();
  };

  return {
    retry,
    preflight,
    preflightAndCompute,
    refreshSupplierVersion,
    compute,
    startExport,
    downloadResult,
    refreshHistory
  };
}
