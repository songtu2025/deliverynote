import { Segmented, Typography } from "antd";

import type { InputVersion } from "../../types";
import { INPUT_KIND_DEFINITIONS } from "./adminConstants";
import type { InputKind } from "./adminConstants";

interface InputDataKindSwitcherProps {
  versions: InputVersion[];
  selectedKind: InputKind;
  busy: boolean;
  onChange: (kind: InputKind) => void;
}

const MAINTAINABLE_INPUT_KIND_DEFINITIONS = INPUT_KIND_DEFINITIONS.filter(
  (definition) => definition.value !== "purchase"
);

export function InputDataKindSwitcher({ versions, selectedKind, busy, onChange }: InputDataKindSwitcherProps) {
  const readyKindCount = MAINTAINABLE_INPUT_KIND_DEFINITIONS.filter((definition) =>
    versions.some((version) => version.kind === definition.value && version.active)
  ).length;

  return (
    <section className="input-data-kind-switcher" aria-label="基础资料类型">
      <Segmented
        aria-label="基础资料类型"
        value={selectedKind}
        disabled={busy}
        onChange={onChange}
        options={MAINTAINABLE_INPUT_KIND_DEFINITIONS.map((definition) => {
          const current = versions.find((version) => version.kind === definition.value && version.active);
          return {
            value: definition.value,
            label: (
              <span
                aria-label={
                  current
                    ? `${definition.label}，已就绪，当前版本 ${current.name}`
                    : `${definition.label}，未启用，等待上传`
                }
              >
                {definition.label}
              </span>
            )
          };
        })}
      />
      <Typography.Text type="secondary">
        {readyKindCount}/{MAINTAINABLE_INPUT_KIND_DEFINITIONS.length} 已启用
      </Typography.Text>
    </section>
  );
}
