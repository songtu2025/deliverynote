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
const PURCHASE_ENTRY_KINDS = new Set<InputKind>(["sku_warehouse", "purchase_template"]);

export function InputDataKindSwitcher({ versions, selectedKind, busy, onChange }: InputDataKindSwitcherProps) {
  const purchaseEntry = PURCHASE_ENTRY_KINDS.has(selectedKind);
  const definitions = MAINTAINABLE_INPUT_KIND_DEFINITIONS.filter(
    (definition) => PURCHASE_ENTRY_KINDS.has(definition.value) === purchaseEntry
  );
  const readyKindCount = definitions.filter((definition) =>
    versions.some((version) => version.kind === definition.value && version.active)
  ).length;

  return (
    <div className="input-data-kind-groups">
      <Segmented
        name="input-data-group"
        aria-label="资料类别"
        value={purchaseEntry ? "purchase-entry" : "common"}
        disabled={busy}
        onChange={(group) => onChange(group === "purchase-entry" ? "sku_warehouse" : "product")}
        options={[
          { value: "common", label: "基础资料" },
          { value: "purchase-entry", label: "采购单录入资料" }
        ]}
      />
      <section className="input-data-kind-switcher" aria-label="基础资料类型">
        <Segmented
          name="input-data-kind"
          aria-label="基础资料类型"
          value={selectedKind}
          disabled={busy}
          onChange={onChange}
          options={definitions.map((definition) => {
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
          {readyKindCount}/{definitions.length} 已启用
        </Typography.Text>
      </section>
    </div>
  );
}
