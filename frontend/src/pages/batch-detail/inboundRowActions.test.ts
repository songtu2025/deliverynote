import { describe, expect, it } from "vitest";
import { inboundRowActions } from "./inboundRowActions";

describe("自营仓原因与行内操作", () => {
  it("计算前按原因映射，站点必须有候选", () => {
    expect(inboundRowActions("产品信息站点不唯一", false, ["Store:US"])).toEqual(["site"]);
    expect(inboundRowActions("产品信息站点不唯一", false)).toEqual([]);
    expect(inboundRowActions("产品信息未匹配", false)).toEqual(["versions"]);
    for (const reason of ["未找到自营仓入库单", "供应商不一致", "PO名称为空", "应收货无效"]) {
      expect(inboundRowActions(reason, false)).toEqual(["refresh"]);
    }
    expect(inboundRowActions("其他", false)).toEqual([]);
  });
  it("计算后资料控件只保留候选站点和锁定资料，不提供收尾操作", () => {
    for (const reason of ["超出允许超收量", "超出应收货"]) {
      expect(inboundRowActions(reason, true)).toEqual([]);
    }
    expect(inboundRowActions("其他", true)).toEqual([]);
    expect(inboundRowActions("产品信息未匹配", true)).toEqual(["versions"]);
    expect(inboundRowActions("产品信息站点不唯一", true, ["Store:US"])).toEqual(["site"]);
    expect(inboundRowActions("供应商不一致", true)).toEqual([]);
  });
});
