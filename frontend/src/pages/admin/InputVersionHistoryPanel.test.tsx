import type { ComponentProps } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InputVersionHistoryPanel } from "./InputVersionHistoryPanel";

type HistoryProps = ComponentProps<typeof InputVersionHistoryPanel>;

function historyProps(count = 2): HistoryProps {
  return {
    label: "商品信息",
    versions: Array.from({ length: count }, (_, index) => ({
      id: index + 1,
      kind: "product",
      name: `version-${index + 1}`,
      original_name: `version-${index + 1}.xlsx`,
      active: index === 0,
      created_by: 1,
      created_at: `2026-07-${20 + index}T09:00:00Z`
    })),
    loading: false,
    activationAllowed: true,
    mutationBusy: false,
    activatingVersionId: null,
    onActivate: vi.fn()
  };
}

function historyView(props: HistoryProps) {
  return (
    <ConfigProvider locale={zhCN} theme={{ token: { motion: false } }}>
      <InputVersionHistoryPanel {...props} />
    </ConfigProvider>
  );
}

describe("InputVersionHistoryPanel", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("preserves the supplied order, metadata, current status and accessible table name", () => {
    const props = historyProps();
    props.versions.reverse();
    render(historyView(props));

    const table = screen.getByRole("table", { name: "商品信息版本记录" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.querySelector("strong")?.textContent)).toEqual(["version-2", "version-1"]);
    expect(screen.getByText("共 2 个版本")).toBeInTheDocument();
    expect(within(rows[0]).getByText("version-2.xlsx")).toBeInTheDocument();
    expect(within(rows[0]).getByText("2026/7/21 17:00:00")).toBeInTheDocument();
    expect(within(rows[0]).getByText("用户 #1")).toBeInTheDocument();
    expect(within(rows[1]).getByText("当前启用")).toBeInTheDocument();
    expect(rows[1]).toHaveClass("input-data-active-version-row");
    expect(within(rows[1]).queryByRole("button", { name: "启用" })).not.toBeInTheDocument();
  });

  it.each([8, 9])("paginates only above eight versions: %s", async (count) => {
    render(historyView(historyProps(count)));
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    if (count === 8) {
      expect(screen.queryByTitle("2")).not.toBeInTheDocument();
      expect(screen.getByText("version-8")).toBeInTheDocument();
    } else {
      expect(screen.queryByText("version-9")).not.toBeInTheDocument();
      fireEvent.click(screen.getByTitle("2"));
      expect(await screen.findByText("version-9")).toBeInTheDocument();
      expect(screen.queryByText("version-8")).not.toBeInTheDocument();
      expect(screen.getByText("共 9 个版本")).toBeInTheDocument();
    }
  });

  it("delegates activation only after confirmation and never changes version state locally", async () => {
    const props = historyProps();
    render(historyView(props));
    fireEvent.click(screen.getByRole("button", { name: "启用" }));
    expect(await screen.findByText("启用 version-2？")).toBeInTheDocument();
    expect(screen.getByText("仅用于新批次；已有批次不变。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /取\s*消/ }));
    expect(props.onActivate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "启用" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认启用" }));
    expect(props.onActivate).toHaveBeenCalledExactlyOnceWith(props.versions[1]);
    expect(screen.getByText("历史版本")).toBeInTheDocument();
    expect(props.versions[1].active).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("honors the parent's history activation restriction", () => {
    const props = historyProps();
    props.label = "MSKU定位";
    props.activationAllowed = false;
    render(historyView(props));
    expect(screen.getByRole("table", { name: "MSKU定位版本记录" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "启用" })).not.toBeInTheDocument();
  });

  it("renders controlled mutation locking and restores actions when the parent finishes", () => {
    const props = historyProps(3);
    props.mutationBusy = true;
    props.activatingVersionId = 2;
    const { rerender } = render(historyView(props));
    const buttons = screen.getAllByRole("button", { name: /启\s*用/ });
    expect(buttons).toHaveLength(2);
    for (const button of buttons) expect(button).toBeDisabled();
    expect(buttons[0]).toHaveAttribute("aria-busy", "true");
    expect(buttons[1]).toHaveAttribute("aria-busy", "false");
    fireEvent.click(buttons[1]);
    expect(props.onActivate).not.toHaveBeenCalled();

    props.mutationBusy = false;
    props.activatingVersionId = null;
    rerender(historyView(props));
    for (const button of screen.getAllByRole("button", { name: "启用" })) {
      expect(button).toBeEnabled();
      expect(button).toHaveAttribute("aria-busy", "false");
    }
  });

  it.each([false, true])("renders empty and loading data without fetching: %s", (loading) => {
    const props = historyProps(0);
    props.loading = loading;
    render(historyView(props));
    expect(screen.getByText("共 0 个版本")).toBeInTheDocument();
    expect(screen.getByText("暂无商品信息版本")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("renders version names and filenames as text rather than HTML", () => {
    const props = historyProps();
    props.versions[1].name = '<img src=x onerror="window.__uiInjected=true">';
    props.versions[1].original_name = "<b>合成文件</b>.xlsx";
    const { container } = render(historyView(props));
    expect(screen.getByText(props.versions[1].name)).toBeInTheDocument();
    expect(screen.getByText(props.versions[1].original_name)).toBeInTheDocument();
    expect(container.querySelector("img, b")).toBeNull();
  });
});
