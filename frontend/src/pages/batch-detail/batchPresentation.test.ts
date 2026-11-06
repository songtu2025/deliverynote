import { describe, expect, it } from "vitest";
import { batchTaskPresentation } from "./batchPresentation";
import { batchStage } from "../../batchStage";
import type { Batch, Job } from "../../types";

const batchStagePresentation = (
  batch: Batch,
  activeJob?: Job,
  reviewStats?: { unfinishedCount: number; unfinishedQuantity: number }
) => batchStage(batch, { activeJob, reviewStats }).stage;

import { createDetailBatch, fixtureJob } from "./detailFixtures";

describe("批次真实阶段", () => {
  it.each([
    ["prepare", "正在核对累计实收（1/3，已用 9 秒）"],
    ["compute", "正在计算（2/3，已用 9 秒）"],
    ["export", "正在生成结果（3/3）"]
  ] as const)("自营仓 %s 使用步骤状态句", (kind, title) => {
    const batch = { ...createDetailBatch(), workflow: "self_operated_inbound" as const };
    expect(batchTaskPresentation(batch, fixtureJob({ kind }), undefined, 9).title).toBe(title);
    for (const position of [undefined, null, 0, 3]) {
      const job = fixtureJob({ kind, status: "queued", queue_position: position });
      expect(batchTaskPresentation(batch, job).title).toBe(
        position == null ? "排队中" : `排队中，前面还有 ${position} 个任务`
      );
    }
  });

  it("交货批次保留原来的排队和运行文案", () => {
    for (const [kind, queued, running] of [
      ["prepare", "历史核对排队中", "正在获取历史并核对累计实收"],
      ["compute", "计算排队中", "正在计算"],
      ["export", "结果排队中", "正在生成结果"]
    ] as const) {
      const job = fixtureJob({ kind, queue_position: 5 });
      expect(batchTaskPresentation(createDetailBatch(), { ...job, status: "queued" }).title).toBe(queued);
      expect(batchTaskPresentation(createDetailBatch(), job).title).toBe(running);
    }
  });

  it.each(["delivery", "self_operated_inbound"] as const)("%s 覆盖准备、计算与失败阶段", (workflow) => {
    const batch = { ...createDetailBatch(), workflow, download_ready: false, receipt: { requested_total: 160 } };
    for (const [status, label] of [
      ["draft", "准备文件"],
      ["preflight_ready", "可计算"],
      ["queued", "计算中"],
      ["running", "计算中"],
      ["failed", "失败"]
    ]) {
      expect(batchStagePresentation({ ...batch, status }).label).toBe(label);
    }
  });

  it("累计实收待核对优先于准备文件和预检失败", () => {
    const batch = {
      ...createDetailBatch(),
      workflow: "self_operated_inbound" as const,
      receipt: { issue_count: 1, requested_total: null }
    };
    for (const status of ["draft", "failed", "preflight_ready"]) {
      expect(batchStagePresentation({ ...batch, status })).toEqual({ label: "待核对", tone: "review" });
    }
  });

  it.each([
    ["prepare", "核对中"],
    ["compute", "计算中"],
    ["export", "生成中"]
  ] as const)("%s 排队与执行显示 %s", (kind, label) => {
    for (const status of ["queued", "running"]) {
      const job = fixtureJob({ kind, status });
      expect(batchStagePresentation(createDetailBatch(), job).label).toBe(label);
      expect(batchStagePresentation({ ...createDetailBatch(), jobs: { [kind]: job } }).label).toBe(label);
    }
  });

  it("整批采购取数不覆盖主流程阶段", () => {
    const batch = {
      ...createDetailBatch(),
      status: "preflight_ready",
      jobs: { purchase_snapshot: fixtureJob({ kind: "purchase_snapshot" }) }
    };
    expect(batchStagePresentation(batch).label).toBe("可计算");
  });

  it("审校进度来自全批统计，结果可下载后才完成", () => {
    const batch = createDetailBatch();
    const pending = { unfinishedCount: 2, unfinishedQuantity: 261 };
    expect(batchStagePresentation(batch, undefined, pending).label).toBe("待审校");
    const resolved = { unfinishedCount: 0, unfinishedQuantity: 0 };
    expect(batchStagePresentation(batch, undefined, resolved).label).toBe("可生成结果");
    batch.download_ready = true;
    expect(batchStagePresentation(batch, undefined, resolved).label).toBe("可生成结果");
    batch.merged_download_ready = true;
    expect(batchStagePresentation(batch, undefined, resolved).label).toBe("已完成");
    batch.jobs = { export: fixtureJob({ kind: "export", status: "stale" }) };
    batch.download_ready = false;
    expect(batchStagePresentation(batch, undefined, resolved).label).toBe("可生成结果");
  });

  it("批次未附错误文本时保留计算任务失败原因", () => {
    const batch = {
      ...createDetailBatch(),
      status: "failed",
      jobs: { compute: fixtureJob({ status: "failed", error_message: "合成计算错误" }) }
    };
    expect(batchTaskPresentation(batch).description).toBe("合成计算错误");
  });

  it("生成失败使用失败语义", () => {
    const batch = { ...createDetailBatch(), jobs: { export: fixtureJob({ kind: "export", status: "failed" }) } };
    expect(batchStagePresentation(batch)).toEqual({ label: "失败", tone: "error" });
  });

  it("自营仓统一待处理，无剩余时自动生成结果而非提示手动生成", () => {
    const batch = {
      ...createDetailBatch(),
      workflow: "self_operated_inbound" as const,
      receipt: { issue_count: 0, requested_total: 160 }
    };
    const pending = { unfinishedCount: 1, unfinishedQuantity: 5 };
    const resolved = { unfinishedCount: 0, unfinishedQuantity: 0 };
    expect(batchStagePresentation(batch, undefined, pending).label).toBe("待处理");
    // 没有导出任务（如规则上线前计算的批次）时提示可生成，而不是一直显示生成中。
    expect(batchTaskPresentation(batch, undefined, pending).title).toBe("可以生成结果 · 还有 1 条待处理");
    expect(batchStagePresentation(batch, undefined, resolved).label).toBe("可生成结果");
    batch.jobs = { export: fixtureJob({ kind: "export", status: "running" }) };
    expect(batchStagePresentation(batch, undefined, resolved).label).toBe("生成中");
    expect(batchTaskPresentation(batch, undefined, resolved).title).toBe("正在生成结果（3/3）");
    batch.jobs = {};
    batch.download_ready = true;
    batch.merged_download_ready = true;
    expect(batchTaskPresentation(batch, undefined, pending).title).toBe("结果已生成，可以下载 · 还有 1 条待处理");
    expect(batchTaskPresentation(batch, undefined, resolved).title).toBe("结果已生成，可以下载");
  });
});
