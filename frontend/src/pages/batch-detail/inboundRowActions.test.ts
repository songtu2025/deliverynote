import { describe, expect, it } from "vitest";
import { inboundRowActions } from "./inboundRowActions";

describe("自营仓原因与行内操作", () => {
  it("计算前按原因映射，站点必须有候选", () => {
    expect(inboundRowActions("产品信息站点不唯一", false, { candidates: ["Store:US"] })).toEqual(["site"]);
    expect(inboundRowActions("产品信息站点不唯一", false)).toEqual([]);
    expect(inboundRowActions("产品信息未匹配", false)).toEqual(["versions"]);
    for (const reason of ["未找到自营仓入库单", "供应商不一致", "PO名称为空", "应收货无效"]) {
      expect(inboundRowActions(reason, false)).toEqual(["refresh"]);
    }
    expect(inboundRowActions("其他", false)).toEqual([]);
  });
  it("计算后超量允许追加，其他原因只线下处理或转交，零剩余没有操作", () => {
    for (const reason of ["超出允许超收量", "超出应收货"]) {
      expect(inboundRowActions(reason, true, { remaining: 2 })).toEqual(["allowance", "offline", "transfer"]);
      expect(inboundRowActions(reason, true, { remaining: 0 })).toEqual([]);
    }
    expect(inboundRowActions("其他", true, { remaining: 2 })).toEqual(["offline", "transfer"]);
    expect(inboundRowActions("产品信息未匹配", true, { remaining: 2 })).toEqual(["versions", "offline"]);
    expect(inboundRowActions("产品信息站点不唯一", true, { remaining: 2, candidates: ["Store:US"] })).toEqual([
      "site",
      "offline"
    ]);
  });
});
