import { useEffect, useState } from "react";
import type { Batch } from "../../types";
import { getBatchImportRows } from "../../batchDetailApi";

// 标签与「待处理」一致按记录条数计数，件数见数量条。
export function useImportRowCount(batch: Batch, computed: boolean) {
  const [count, setCount] = useState<number>();
  useEffect(() => {
    if (!computed) return;
    let active = true;
    getBatchImportRows(batch.id, new URLSearchParams({ offset: "0", limit: "1" })).then(
      (result) => {
        if (active) setCount(result.total);
      },
      () => {
        if (active) setCount(undefined);
      }
    );
    return () => {
      active = false;
    };
  }, [batch.id, batch.updated_at, computed]);
  return count;
}
