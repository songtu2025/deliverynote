import { Button, Typography } from "antd";
import { CheckCircleFilled } from "@ant-design/icons";

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
      <div className="input-data-kind-switcher-heading">
        <Typography.Text strong>资料类型</Typography.Text>
        <Typography.Text type="secondary">
          {readyKindCount}/{MAINTAINABLE_INPUT_KIND_DEFINITIONS.length} 已启用
        </Typography.Text>
      </div>
      <div className="input-data-kind-list">
        {MAINTAINABLE_INPUT_KIND_DEFINITIONS.map((definition) => {
          const current = versions.find((version) => version.kind === definition.value && version.active);
          const selected = definition.value === selectedKind;
          return (
            <Button
              key={definition.value}
              className={`input-data-kind-button${selected ? " is-selected" : ""}`}
              aria-label={
                current
                  ? `${definition.label}，已就绪，当前版本 ${current.name}`
                  : `${definition.label}，未启用，等待上传`
              }
              aria-pressed={selected}
              disabled={busy}
              onClick={() => onChange(definition.value)}
            >
              <span>{definition.label}</span>
              {current ? (
                <CheckCircleFilled aria-label="已就绪" />
              ) : (
                <span className="input-data-kind-pending">未启用</span>
              )}
            </Button>
          );
        })}
      </div>
    </section>
  );
}
