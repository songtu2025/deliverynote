import { fireEvent, render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { expect, vi } from "vitest";

import type { InputVersion } from "../../types";
import { PositionMaintenance } from "./PositionMaintenance";
import { basePositionVersion as version } from "./positionDraftTestSupport";

export function renderMaintenance(
  overrides: Partial<{
    onPublished: (published: InputVersion) => void;
    onBack: () => void;
  }> = {}
) {
  return render(
    <AntApp>
      <PositionMaintenance
        activeVersion={version}
        onPublished={overrides.onPublished ?? vi.fn()}
        onBack={overrides.onBack ?? vi.fn()}
      />
    </AntApp>
  );
}

export async function dialogByTitle(title: string): Promise<HTMLElement> {
  const heading = await screen.findByText(title);
  const dialog = heading.closest('[role="dialog"]');
  expect(dialog).not.toBeNull();
  return dialog as HTMLElement;
}

export function fillNewRow() {
  fireEvent.change(screen.getByLabelText("店铺-站点"), { target: { value: "SEEKWAY:UK" } });
  fireEvent.change(screen.getByLabelText("积加 SKU"), { target: { value: "SKU-B" } });
}

export async function startRowSave() {
  renderMaintenance();
  await screen.findByText("SKU-A");
  fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
  fillNewRow();
  fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));
}
