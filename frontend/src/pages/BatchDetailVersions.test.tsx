import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { message } from "antd";
import { expect, it, vi } from "vitest";
import { describe } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";

describe("BatchDetailVersions", () => {
  const { state } = setupBatchDetailTest();

  it("uses context feedback for successful operations instead of static messages", async () => {
    state.batch.status = "draft";
    const staticSuccess = vi.spyOn(message, "success");
    renderDetail(<BatchDetail batchId={7} canRefreshSupplierVersion onBack={vi.fn()} />);
    fireEvent.click(await screen.findByText("锁定资料", { selector: '[role="tab"]' }));
    const lockedData = within(screen.getByText("批次锁定版本").closest(".locked-data-card") as HTMLElement);
    fireEvent.click(await lockedData.findByRole("button", { name: "采用当前供应商资料" }));
    await screen.findByText("批次已采用当前供应商资料");
    expect(staticSuccess).not.toHaveBeenCalled();
  });

  it("lets an admin draft adopt the current supplier version", async () => {
    state.batch.status = "draft";
    renderDetail(<BatchDetail batchId={7} canRefreshSupplierVersion onBack={vi.fn()} />);

    fireEvent.click(await screen.findByText("锁定资料", { selector: '[role="tab"]' }));
    const lockedData = within(screen.getByText("批次锁定版本").closest(".locked-data-card") as HTMLElement);
    const refreshButton = await lockedData.findByRole("button", {
      name: "采用当前供应商资料"
    });
    fireEvent.click(refreshButton);

    await waitFor(() =>
      expect(
        vi
          .mocked(fetch)
          .mock.calls.some(
            ([input, init]) =>
              String(input).endsWith("/api/batches/7/refresh-supplier-version") && init?.method === "POST"
          )
      ).toBe(true)
    );
    await screen.findByText("supplier-v2");
    expect(lockedData.queryByRole("button", { name: "采用当前供应商资料" })).not.toBeInTheDocument();
  });

  it("does not show supplier refresh outside an admin draft", async () => {
    state.batch.status = "draft";
    const { rerender } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    fireEvent.click(await screen.findByText("锁定资料", { selector: '[role="tab"]' }));
    const lockedData = within(screen.getByText("批次锁定版本").closest(".locked-data-card") as HTMLElement);
    await screen.findByText("批次锁定版本");
    expect(lockedData.queryByRole("button", { name: "采用当前供应商资料" })).not.toBeInTheDocument();

    state.batch.status = "failed";
    rerender(<BatchDetail batchId={7} canRefreshSupplierVersion onBack={vi.fn()} />);
    await waitFor(() =>
      expect(
        lockedData.queryByRole("button", {
          name: "采用当前供应商资料"
        })
      ).not.toBeInTheDocument()
    );
  });
});
