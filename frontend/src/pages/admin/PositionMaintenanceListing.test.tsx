import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { baseRow, deferred, jsonResponse } from "./positionDraftTestSupport";
import { createPositionMaintenanceTestEnvironment } from "./positionMaintenanceTestEnvironment";
import { renderMaintenance } from "./positionMaintenancePageTestSupport";

let environment: ReturnType<typeof createPositionMaintenanceTestEnvironment>;

describe("PositionMaintenance row listing", () => {
  beforeEach(() => {
    environment = createPositionMaintenanceTestEnvironment();
    environment.install();
  });

  afterEach(() => {
    environment.dispose();
  });

  it("sends server filters and pagination, and a late response cannot replace newer rows", async () => {
    const slow = deferred<Response>();
    environment.state.rowRequestHandler = (url) => {
      if (url.includes("search=old")) return slow.promise;
      if (url.includes("search=new")) {
        return jsonResponse({
          rows: [{ ...baseRow, id: 202, jiaji_sku: "LATEST-SKU" }],
          total: 45,
          offset: 0,
          limit: 20
        });
      }
      return jsonResponse({ ...environment.state.rowsResponse, total: 45 });
    };
    renderMaintenance();
    await screen.findByText("SKU-A");

    fireEvent.click(within(screen.getByText("SKU-A").closest("tr")!).getByRole("checkbox"));
    expect(screen.getByText("已选择 1 条")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("搜索草稿"), { target: { value: "old" } });
    await waitFor(() => {
      expect(
        environment
          .requests("GET", "/api/input-drafts/7/rows?")
          .some(([input]) => new URL(String(input), "http://test").searchParams.get("search") === "old")
      ).toBe(true);
    });
    fireEvent.change(screen.getByLabelText("搜索草稿"), { target: { value: "new" } });
    expect(await screen.findByText("LATEST-SKU")).toBeInTheDocument();
    expect(screen.getByText("已选择 0 条")).toBeInTheDocument();
    slow.resolve(
      jsonResponse({ rows: [{ ...baseRow, id: 201, jiaji_sku: "STALE-SKU" }], total: 1, offset: 0, limit: 20 })
    );
    await waitFor(() => expect(screen.queryByText("STALE-SKU")).not.toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("站点筛选"), { target: { value: "SEEKWAY:US" } });
    fireEvent.change(screen.getByLabelText("规模定位筛选"), { target: { value: "短尾" } });
    fireEvent.mouseDown(screen.getByLabelText("问题筛选"));
    fireEvent.click(await screen.findByText("仅错误"));
    fireEvent.click(screen.getByRole("checkbox", { name: "仅看已修改" }));
    fireEvent.click(await screen.findByTitle("2"));

    await waitFor(() => {
      const urls = environment.requests("GET", "/api/input-drafts/7/rows?").map(([input]) => String(input));
      expect(
        urls.some(
          (url) =>
            url.includes("search=new") &&
            url.includes("site=SEEKWAY%3AUS") &&
            url.includes("scale_position=%E7%9F%AD%E5%B0%BE") &&
            url.includes("only_errors=true") &&
            url.includes("only_modified=true") &&
            url.includes("offset=20")
        )
      ).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "重置筛选" }));
    await waitFor(() => {
      const calls = environment.requests("GET", "/api/input-drafts/7/rows?");
      const params = new URL(String(calls.at(-1)![0]), "http://test").searchParams;
      expect(Object.fromEntries(params)).toEqual({ offset: "0", limit: "20" });
    });
    expect(screen.getByLabelText("搜索草稿")).toHaveValue("");
    expect(screen.getByLabelText("站点筛选")).toHaveValue("");
    expect(screen.getByLabelText("规模定位筛选")).toHaveValue("");
    expect(screen.getByRole("checkbox", { name: "仅看已修改" })).not.toBeChecked();
    expect(screen.queryByRole("button", { name: "重置筛选" })).not.toBeInTheDocument();
  });

  it("retries a failed row read without reopening the draft", async () => {
    environment.state.rowRequestHandler = () => jsonResponse({ detail: "草稿记录暂时不可用" }, 500);
    renderMaintenance();
    expect(await screen.findByText("草稿记录暂时不可用")).toBeInTheDocument();
    expect(screen.queryByText("SKU-A")).not.toBeInTheDocument();

    environment.state.rowRequestHandler = () => jsonResponse(environment.state.rowsResponse);
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();
    expect(screen.queryByText("无法读取草稿记录")).not.toBeInTheDocument();
    expect(environment.requests("GET", "/api/input-drafts/7/rows?")).toHaveLength(2);
    expect(environment.requests("POST", "/api/input-drafts/position")).toHaveLength(1);
  });

  it("debounces rapid text filters before requesting rows", async () => {
    renderMaintenance();
    await screen.findByText("SKU-A");

    const search = screen.getByLabelText("搜索草稿");
    fireEvent.change(search, { target: { value: "s" } });
    fireEvent.change(search, { target: { value: "sk" } });
    fireEvent.change(search, { target: { value: "sku" } });

    await waitFor(() => {
      const values = environment
        .requests("GET", "/api/input-drafts/7/rows?")
        .map(([input]) => new URL(String(input), "http://test").searchParams.get("search"))
        .filter(Boolean);
      expect(values).toEqual(["sku"]);
    });
  });
});
