import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { describe } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";

describe("BatchDetailReview", () => {
  const { state, pagedExceptions } = setupBatchDetailTest();

  it("shows quantity conservation and prevents an invalid split", async () => {
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    await screen.findByText("160 = 100 + 60");
    expect(screen.getByText("序号越小，越先扣减采购余额")).toBeInTheDocument();
    const task = within(screen.getByRole("region", { name: "批次任务状态" }));
    expect(await task.findByText("等待人工审校")).toBeInTheDocument();
    expect(screen.queryByText(/当前阶段/)).not.toBeInTheDocument();
    expect(task.getByText("4 条未完成 · 待处理 107 件")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "处理异常" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "规模定位" })).toBeInTheDocument();
    expect(screen.getAllByText("短尾").length).toBeGreaterThan(0);
    expect(screen.getByText("短尾超收 V1")).toBeInTheDocument();
    expect(screen.getByText("短尾 +50 / 中尾 +20 / 长尾 +10")).toBeInTheDocument();
    expect(container.querySelector(".exception-review-card .ant-table-content")).toHaveStyle({ overflowX: "auto" });
    fireEvent.click(screen.getByRole("button", { name: "收起锁定版本" }));
    expect(screen.queryByText("短尾超收 V1")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看锁定版本" }));
    expect(screen.getByText("短尾超收 V1")).toBeInTheDocument();
    expect(container.querySelector(".exception-review-card .ant-pagination")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "查看并处理" })[0]);

    await screen.findByText("审校处理 · SKU-A");
    const drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("规模定位")).toBeInTheDocument();
    expect(within(drawer).getByText("短尾")).toBeInTheDocument();
    expect(within(drawer).getByText("备货定位")).toBeInTheDocument();
    expect(within(drawer).getByText("备货")).toBeInTheDocument();
    expect(within(drawer).queryByText("已下单可售天数")).not.toBeInTheDocument();
    const saveButton = screen.getByRole("button", { name: "保存" });
    expect(saveButton).toBeEnabled();
    const quantity = screen.getByRole("spinbutton", { name: "数量" });
    fireEvent.change(quantity, { target: { value: "59" } });
    await waitFor(() => expect(saveButton).toBeDisabled());
    expect(screen.getByText("1", { selector: ".split-conservation strong" })).toBeInTheDocument();
  }, 30_000);

  it("filters pending rows by site, scale position, and stocking position", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    await screen.findByText("SKU-A");
    expect(screen.getByText("SKU-B")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "原因筛选" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "审校概览" })).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "站点筛选" }));
    fireEvent.click(await screen.findByText("AMAZON:SEEKWAY:US", { selector: ".ant-select-item-option-content" }));
    await waitFor(() => expect(screen.queryByText("SKU-B")).not.toBeInTheDocument());

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "规模定位筛选" }));
    fireEvent.click(await screen.findByText("短尾", { selector: ".ant-select-item-option-content" }));
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "备货定位筛选" }));
    fireEvent.click(await screen.findByText("备货", { selector: ".ant-select-item-option-content" }));
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "规模定位筛选" }));
    fireEvent.click(await screen.findByText("中尾", { selector: ".ant-select-item-option-content" }));
    await screen.findByText("当前没有未完成记录");
  }, 30_000);

  it("keeps review navigation working across server pages", async () => {
    state.exceptions = pagedExceptions();
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "全部 12 条" })).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("2"));
    expect(await screen.findByText("SKU-11")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "查看并处理" })[0]);
    const drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("第 11 / 12 条")).toBeInTheDocument();

    expect(within(drawer).getByRole("button", { name: "上一条" })).toBeEnabled();
    fireEvent.click(within(drawer).getByRole("button", { name: "上一条" }));
    expect(await within(drawer).findByText("审校处理 · SKU-10")).toBeInTheDocument();
    expect(within(drawer).getByText("第 10 / 12 条")).toBeInTheDocument();

    await waitFor(() => expect(within(drawer).getByRole("button", { name: "下一条" })).toBeEnabled());
    fireEvent.click(within(drawer).getByRole("button", { name: "下一条" }));
    expect(await within(drawer).findByText("审校处理 · SKU-11")).toBeInTheDocument();
    fireEvent.change(within(drawer).getByRole("spinbutton", { name: "数量" }), {
      target: { value: "2" }
    });
    await waitFor(() => expect(within(drawer).getByRole("button", { name: "上一条" })).toBeDisabled());
  }, 30_000);

  it("returns to the first review page when searching from a later page", async () => {
    state.exceptions = pagedExceptions();
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    await screen.findByRole("button", { name: "全部 12 条" });
    fireEvent.click(screen.getByTitle("2"));
    await screen.findByText("SKU-11");
    fireEvent.change(screen.getByRole("textbox", { name: "搜索待处理记录" }), {
      target: { value: "SKU-1" }
    });

    await waitFor(() => {
      const urls = vi
        .mocked(fetch)
        .mock.calls.map(([input]) => String(input))
        .filter((url) => url.includes("/exceptions?") && url.includes("search=SKU-1"));
      expect(urls.length).toBeGreaterThan(0);
      expect(new URL(urls.at(-1)!, "http://localhost").searchParams.get("offset")).toBe("0");
    });
    expect(await screen.findByText("SKU-1")).toBeInTheDocument();
  });

  it("shows complete SKU and site identifiers in the review table", async () => {
    state.exceptions[0] = {
      ...state.exceptions[0],
      sku: "SKU-EXCESS-LONG",
      full_site: "AMAZON:SEEKWAY:US"
    };
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    const sku = await screen.findByText("SKU-EXCESS-LONG");
    const row = sku.closest("tr");
    expect(row).not.toBeNull();
    const site = within(row!).getByText("AMAZON:SEEKWAY:US");

    expect(sku).toHaveClass("exception-sku-value");
    expect(site).toHaveClass("exception-site-value");
    expect(site.closest("td")).not.toHaveClass("ant-table-cell-ellipsis");
  }, 30_000);

  it("summarizes unfinished work and saves directly into the next exception", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    const overview = await screen.findByRole("region", { name: "审校概览" });
    expect(within(overview).getByRole("button", { name: "未完成 4 条，待处理 107 件" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(within(overview).getByRole("button", { name: "已处理 0 条" })).toBeInTheDocument();
    expect(within(overview).getByRole("button", { name: "全部 4 条" })).toBeInTheDocument();

    const excessRow = (await screen.findByText("SKU-A")).closest("tr");
    expect(excessRow).not.toBeNull();
    fireEvent.click(within(excessRow!).getByRole("button", { name: "查看并处理" }));

    let drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("第 1 / 4 条")).toBeInTheDocument();
    expect(within(drawer).getByRole("radio", { name: "继续保留待处理" })).toBeChecked();
    fireEvent.click(within(drawer).getByRole("radio", { name: "可正式导入" }));
    const saveAndNext = within(drawer).getByRole("button", { name: "保存并下一条" });
    await waitFor(() => expect(saveAndNext).toBeEnabled());
    fireEvent.click(saveAndNext);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith("/api/exceptions/30/split", expect.objectContaining({ method: "PUT" }));
    });
    drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("审校处理 · SKU-B")).toBeInTheDocument();
    expect(within(drawer).getByText("第 1 / 3 条")).toBeInTheDocument();
    expect(within(overview).getByRole("button", { name: "未完成 3 条，待处理 47 件" })).toBeInTheDocument();
    expect(within(overview).getByRole("button", { name: "已处理 1 条" })).toBeInTheDocument();
  }, 30_000);

  it("keeps only the necessary footer actions for a single review item", async () => {
    state.exceptions = [state.exceptions[0]];
    state.batch.summary = {
      delivery_total: 160,
      import_total: 100,
      manual_total: 60,
      conserved: true
    };
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    const row = (await screen.findByText("SKU-A")).closest("tr");
    expect(row).not.toBeNull();
    fireEvent.click(within(row!).getByRole("button", { name: "查看并处理" }));

    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).queryByRole("button", { name: "上一条" })).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "下一条" })).not.toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "保存" })).toBeInTheDocument();
  }, 30_000);
});
