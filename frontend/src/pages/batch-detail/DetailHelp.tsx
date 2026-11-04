import { Tooltip } from "antd";
import { QuestionCircleOutlined } from "@ant-design/icons";
import type { ReactNode } from "react";

export default function DetailHelp({ label, title }: { label: string; title: ReactNode }) {
  return (
    <Tooltip title={title} trigger={["hover", "focus"]}>
      <button type="button" className="batch-help" aria-label={label}>
        <QuestionCircleOutlined aria-hidden />
      </button>
    </Tooltip>
  );
}
