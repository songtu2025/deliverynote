import { useRef, useState } from "react";
import { App } from "antd";
import { saveInboundAdjustments } from "../../inboundExceptionApi";

export function useSaveInboundAdjustments(batchId: number | undefined, onSaved?: () => Promise<unknown>) {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);
  const save = async (input: Parameters<typeof saveInboundAdjustments>[1]) => {
    if (!batchId || saving.current) return false;
    saving.current = true;
    setBusy(true);
    try {
      await saveInboundAdjustments(batchId, input);
      await onSaved?.();
      message.success("已保存调整，正在重算整批");
      return true;
    } catch (failure) {
      message.error(failure instanceof Error ? failure.message : "保存调整失败");
      return false;
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  return { busy, save };
}
