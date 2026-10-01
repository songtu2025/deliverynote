import { render, screen } from "@testing-library/react";
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
