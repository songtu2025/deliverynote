import { useRef, useState } from "react";
import { App, Button, Space } from "antd";
import {
  saveManualAllowance,
  saveOfflineHandling,
  waitForHandlingIdle,
  type ManualAllowanceInput
} from "../../inboundExceptionApi";
import type { DeliveryException } from "../../types";

type HandlingSnapshot = { quantity: number; reason: string };

export function useInboundHandling(batchId: number, onSaved: (updated?: DeliveryException) => Promise<unknown>) {
  const { message } = App.useApp();
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);
  const run = async (save: () => Promise<DeliveryException | undefined>, title: string, undo?: () => Promise<void>) => {
    if (saving.current) return;
    saving.current = true;
    setBusy(true);
    try {
      const updated = await save();
      await onSaved(updated);
      message.success({
        content: (
          <Space>
            {title}
            {undo && (
              <Button
                type="link"
                size="small"
                onClick={() =>
                  void run(async () => {
                    const close = message.loading("正在撤销，等待后台任务完成", 0);
                    try {
                      await waitForHandlingIdle(batchId);
                    } finally {
                      close();
                    }
                    await undo();
                    return undefined;
                  }, "已撤销")
                }
              >
                撤销
              </Button>
            )}
          </Space>
        ),
        duration: undo ? 8 : 3
      });
    } catch (failure) {
      message.error(failure instanceof Error ? failure.message : "保存处理失败");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  return {
    busy,
    // previous 为一键操作前的数量与原因，撤销时恢复为该值。
    saveAllowance: (input: ManualAllowanceInput, previous?: HandlingSnapshot) =>
      run(
        async () => {
          await saveManualAllowance(batchId, input);
          return undefined;
        },
        input.quantity ? "已追加超收，正在重算" : "已撤销追加超收",
        previous
          ? async () => {
              await saveManualAllowance(batchId, { ...input, ...previous });
            }
          : undefined
      ),
    saveOffline: (record: DeliveryException, quantity: number, note: string, previous?: HandlingSnapshot) =>
      run(
        () => saveOfflineHandling(record.id, { quantity, note }),
        quantity ? "已保存线下处理" : "已撤销线下处理",
        previous
          ? async () => {
              await saveOfflineHandling(record.id, { quantity: previous.quantity, note: previous.reason });
            }
          : undefined
      )
  };
}
