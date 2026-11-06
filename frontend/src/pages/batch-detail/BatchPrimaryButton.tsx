import { Button, Tooltip } from "antd";
import type { ButtonProps } from "antd";

export default function BatchPrimaryButton({ reason, ...props }: ButtonProps & { reason: string | null }) {
  return (
    <Tooltip title={reason} trigger={["hover", "focus"]}>
      <span tabIndex={reason ? 0 : undefined} aria-label={reason ?? undefined}>
        <Button
          aria-label={typeof props.children === "string" ? props.children : undefined}
          {...props}
          type="primary"
          disabled={Boolean(reason)}
        />
      </span>
    </Tooltip>
  );
}
