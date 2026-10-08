import { useState } from "react";
import { App as AntApp, Form } from "antd";
import type { UploadFile, UploadProps } from "antd";
import { ApiError } from "../../api";
import { createBatchWithFiles } from "../../batchListApi";
import { beijingDateTimeParts } from "../../dateTime";
import type { BatchWorkflow } from "./batchWorkspace";

function todayBatchName(workflow: "delivery" | "self_operated_inbound"): string {
  const parts = beijingDateTimeParts();
  const suffix = workflow === "self_operated_inbound" ? "自营仓入库批次" : "交货批次";
  const name = `${parts.year}-${parts.month}-${parts.day} ${suffix}`;
  return workflow === "delivery" ? `${name} ${parts.hour}:${parts.minute}:${parts.second}` : name;
}

export function useBatchCreation(workflow: BatchWorkflow, onOpen: (id: number) => void) {
  const { message } = AntApp.useApp();
  const [creating, setCreating] = useState(false);
  const [deliveryFiles, setDeliveryFiles] = useState<UploadFile[]>([]);
  const [sourceFiles, setSourceFiles] = useState<UploadFile[]>([]);
  const [form] = Form.useForm<{ name: string }>();
  const create = async () => {
    try {
      const values = await form.validateFields();
      const selectedFiles = workflow === "self_operated_inbound" ? sourceFiles : deliveryFiles;
      const files = selectedFiles.flatMap((file) => (file.originFileObj ? [file.originFileObj] : []));
      if (!files.length) {
        message.warning(workflow === "self_operated_inbound" ? "请至少选择一份质检交货单" : "请至少选择一份交货文件");
        return;
      }
      const batch = await createBatchWithFiles(workflow, values.name, files);
      setCreating(false);
      form.resetFields();
      setDeliveryFiles([]);
      setSourceFiles([]);
      onOpen(batch.id);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        message.error(error instanceof Error ? error.message : "创建批次失败");
      }
    }
  };

  const openCreate = () => {
    form.resetFields();
    setDeliveryFiles([]);
    setSourceFiles([]);
    form.setFieldsValue({ name: todayBatchName(workflow) });
    setCreating(true);
  };

  const closeCreate = () => {
    setCreating(false);
    form.resetFields();
    setDeliveryFiles([]);
    setSourceFiles([]);
  };

  const selectSourceFiles: NonNullable<UploadProps["onChange"]> = ({ fileList }) => {
    setSourceFiles(fileList);
  };

  const selectDeliveryFiles: NonNullable<UploadProps["onChange"]> = ({ fileList }) => {
    setDeliveryFiles(fileList);
  };

  return {
    form,
    creating,
    deliveryFiles,
    sourceFiles,
    create,
    openCreate,
    closeCreate,
    selectSourceFiles,
    selectDeliveryFiles
  };
}
