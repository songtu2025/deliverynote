import { App as AntApp } from "antd";
import type { UploadProps } from "antd";
import type { BatchFile } from "../../types";
import { uploadBatchFile, deleteBatchFile, reorderBatchFiles } from "../../batchDetailApi";
import type { BatchAction } from "./useBatchAction";

export function useBatchFiles({
  batchId,
  files,
  selfOperated,
  runAction,
  load
}: {
  batchId: number;
  files: BatchFile[];
  selfOperated: boolean;
  runAction: BatchAction;
  load: (silent?: boolean) => Promise<unknown>;
}) {
  const { message } = AntApp.useApp();
  const uploadFile: NonNullable<UploadProps["customRequest"]> = async (options) => {
    await runAction("upload", async () => {
      await uploadBatchFile(batchId, options.file as File);
      options.onSuccess?.({});
      await load(true);
      message.success(`${selfOperated ? "质检交货单" : "交货文件"}已上传，预检状态已更新`);
    });
  };

  const uploadInboundFile: NonNullable<UploadProps["customRequest"]> = async (options) => {
    await runAction("upload-inbound", async () => {
      await uploadBatchFile(batchId, options.file as File, "inbound");
      options.onSuccess?.({});
      await load(true);
      message.success("自营仓入库单已上传，预检状态已更新");
    });
  };

  const removeFile = async (file: BatchFile) => {
    await runAction("delete", async () => {
      await deleteBatchFile(batchId, file.id);
      await load(true);
      message.success(`${file.original_name} 已删除，其余文件已自动重排`);
    });
  };

  const move = async (fileId: number, offset: number) => {
    const ids = files.map((file) => file.id);
    const index = ids.indexOf(fileId);
    const next = index + offset;
    if (index < 0 || next < 0 || next >= ids.length) return;
    [ids[index], ids[next]] = [ids[next], ids[index]];
    await runAction("order", async () => {
      await reorderBatchFiles(batchId, ids);
      await load(true);
      message.info("处理顺序已更新，需要重新预检");
    });
  };

  return { uploadFile, uploadInboundFile, removeFile, move };
}
export type BatchFiles = ReturnType<typeof useBatchFiles>;
