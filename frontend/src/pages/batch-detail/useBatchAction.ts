import { useCallback, useState } from "react";
import { App as AntApp } from "antd";
import { ApiError } from "../../api";

export function useBatchAction() {
  const { message } = AntApp.useApp();
  const [action, setAction] = useState<string | null>(null);
  const runAction = useCallback(
    async (name: string, operation: () => Promise<void>) => {
      setAction(name);
      try {
        await operation();
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) {
          message.error(error instanceof Error ? error.message : "操作失败");
        }
      } finally {
        setAction(null);
      }
    },
    [message]
  );
  return { action, runAction };
}

export type BatchAction = ReturnType<typeof useBatchAction>["runAction"];
