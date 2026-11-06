import { describe, expect, it } from "vitest";
import { batchStage } from "./batchStage";
import { createDetailBatch, fixtureJob } from "./pages/batch-detail/detailFixtures";
import type { Batch } from "./types";

describe("批次阶段唯一来源", () => {
  it.each(["delivery", "self_operated_inbound"] as const)("%s 准备条件与下一步", (workflow) => {
    const batch = {
      ...createDetailBatch(),
      workflow,
      status: "draft",
      inbound_file: { uploaded: true, original_name: "合成.xlsx" }
    };
    expect(batchStage(batch).next).toMatchObject({ key: "preflight", label: "预检并计算", listLabel: "去预检并计算" });
    expect(batchStage(batch).disabledReason).toBeNull();
    batch.files = [];
    expect(batchStage(batch).disabledReason).toBe(workflow === "delivery" ? "请先上传交货文件" : "请先上传质检交货单");
    expect(batchStage(batch).next.listLabel).toBe("去上传");
  });

  it("待入库与累计实收问题给出具体原因", () => {
    const batch = { ...createDetailBatch(), workflow: "self_operated_inbound" as const, status: "draft" };
    expect(batchStage(batch).disabledReason).toBe("待入库数据未就绪");
    batch.inbound_file = { uploaded: true, original_name: "合成.xlsx" };
    batch.receipt = { issue_count: 3 };
    expect(batchStage(batch)).toMatchObject({
      stage: { label: "待核对", tone: "review" },
      disabledReason: "累计实收存在 3 处待核对"
    });
  });

  it.each(["queued", "running"])("%s 任务覆盖阶段与操作", (status) => {
    for (const [kind, label] of [
      ["prepare", "核对中"],
      ["compute", "计算中"],
      ["export", "生成中"]
    ] as const) {
      const batch = { ...createDetailBatch(), jobs: { [kind]: fixtureJob({ kind, status }) } };
      expect(batchStage(batch)).toMatchObject({
        stage: { label, tone: "running" },
        next: { key: "busy", listLabel: label },
        disabledReason: "后台任务进行中"
      });
    }
  });

  it.each(["delivery", "self_operated_inbound"] as const)("%s 失败和过期仍可查看原因", (workflow) => {
    for (const status of ["failed", "expired"]) {
      expect(batchStage({ ...createDetailBatch(), workflow, status }).next.listLabel).toBe("查看原因");
    }
  });

  it.each(["delivery", "self_operated_inbound"] as const)("%s 待处理、生成与下载", (workflow) => {
    const batch = {
      ...createDetailBatch(),
      workflow,
      receipt: { requested_total: 160 },
      inbound_file: { uploaded: true, original_name: "合成.xlsx" }
    };
    const stats = { unfinishedCount: 2, unfinishedQuantity: 60 };
    expect(batchStage(batch, { reviewStats: stats }).stage.label).toBe(workflow === "delivery" ? "待审校" : "待处理");
    expect(batchStage(batch, { reviewStats: stats }).next.key).toBe(workflow === "delivery" ? "review" : "generate");
    if (workflow === "delivery")
      expect(batchStage(batch, { reviewStats: stats }).sourceResult).toMatchObject({
        key: "generate",
        disabledReason: null
      });
    for (const status of [undefined, "failed", "stale"]) {
      batch.jobs = status ? { export: fixtureJob({ kind: "export", status }) } : {};
      const result = batchStage(batch, { reviewStats: { unfinishedCount: 0, unfinishedQuantity: 0 } });
      expect(result.stage.label).toBe(status === "failed" ? "失败" : "可生成结果");
      expect(result.next.key).toBe("generate");
      expect(result.disabledReason).toBeNull();
    }
    batch.jobs = {};
    batch.download_ready = true;
    batch.merged_download_ready = true;
    expect(batchStage(batch, { reviewStats: stats }).next.key).toBe(workflow === "delivery" ? "review" : "download");
    expect(batchStage(batch, { reviewStats: { unfinishedCount: 0, unfinishedQuantity: 0 } }).stage.label).toBe(
      "已完成"
    );
  });

  it("列表缺少文件详情时使用汇总下载标志，单文件详情仍检查文件结果", () => {
    const batch: Batch = {
      ...createDetailBatch(),
      file_count: 1,
      files: undefined,
      download_ready: true,
      summary: undefined
    };
    expect(batchStage(batch).next.key).toBe("download");
    batch.files = createDetailBatch().files.slice(0, 1);
    expect(batchStage(batch).next.key).toBe("generate");
  });

  it("统计未加载时禁止交货批次生成，采购快照不阻塞主流程", () => {
    const batch = {
      ...createDetailBatch(),
      summary: undefined,
      jobs: { purchase_snapshot: fixtureJob({ kind: "purchase_snapshot" }) }
    };
    expect(batchStage(batch).disabledReason).toBe("正在读取审校统计");
    expect(
      batchStage(batch, { reviewStats: { unfinishedCount: 0, unfinishedQuantity: 0 }, action: "export" }).disabledReason
    ).toBe("操作进行中");
  });
});
