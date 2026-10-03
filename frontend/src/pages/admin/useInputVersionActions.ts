import { useEffect, useState } from "react";
import { App as AntApp, Form } from "antd";
import type { UploadFile, UploadProps } from "antd";

import { ApiError } from "../../api";
import { activateInputVersion, downloadInputVersion, uploadInputVersion } from "../../inputVersionApi";
import type { InputVersion } from "../../types";
import { INPUT_KIND_BY_VALUE, inputUploadFormatMessage } from "./adminConstants";
import type { InputKind } from "./adminConstants";

interface MutationState {
  action: "upload" | "activate";
  versionId?: number;
}

interface KindError {
  kind: InputKind;
  message: string;
}

export function useInputVersionActions(
  selectedKind: InputKind,
  onVersionsChanged: () => void | boolean | Promise<void | boolean>
) {
  const { message } = AntApp.useApp();
  const [uploadError, setUploadError] = useState<KindError | null>(null);
  const [actionError, setActionError] = useState<KindError | null>(null);
  const [mutation, setMutation] = useState<MutationState | null>(null);
  const [pendingFiles, setPendingFiles] = useState<UploadFile[]>([]);
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);
  const [uploadForm] = Form.useForm<{ name: string }>();
  const mutationBusy = mutation !== null;
  const uploading = mutation?.action === "upload";

  useEffect(() => {
    setPendingFiles([]);
    setMaintenanceOpen(false);
  }, [selectedKind, uploadForm]);

  const selectUploadFile: NonNullable<UploadProps["onChange"]> = ({ fileList }) => {
    setPendingFiles(fileList.slice(-1));
    setUploadError(null);
  };

  const uploadVersion = async () => {
    if (mutationBusy) return;
    const kind = selectedKind;
    setUploadError(null);
    let values: { name: string };
    try {
      values = await uploadForm.validateFields();
    } catch {
      return;
    }
    const file = pendingFiles[0]?.originFileObj;
    if (!file) {
      setUploadError({ kind, message: "请选择要上传的 Excel 文件" });
      return;
    }
    const dotIndex = file.name.lastIndexOf(".");
    const extension = dotIndex > 0 ? file.name.slice(dotIndex).toLowerCase() : "";
    if (!INPUT_KIND_BY_VALUE[kind].uploadExtensions.includes(extension)) {
      setUploadError({ kind, message: inputUploadFormatMessage(kind) });
      return;
    }
    setMutation({ action: "upload" });
    try {
      await uploadInputVersion(kind, values.name, file);
      uploadForm.resetFields();
      setPendingFiles([]);
      setMaintenanceOpen(false);
      if ((await onVersionsChanged()) !== false) {
        message.success(`${INPUT_KIND_BY_VALUE[kind].label}已上传并启用，将用于新批次`);
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return;
      const errorMessage = error instanceof Error ? error.message : "上传失败";
      setUploadError({ kind, message: errorMessage });
      message.error("上传失败，请检查页面提示");
    } finally {
      setMutation(null);
    }
  };

  const downloadCurrent = async (activeVersion: InputVersion | null) => {
    if (!activeVersion) return;
    setActionError(null);
    try {
      await downloadInputVersion(activeVersion);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return;
      setActionError({
        kind: selectedKind,
        message: error instanceof Error ? error.message : "下载失败"
      });
    }
  };

  const activateVersion = (version: InputVersion) => {
    if (mutationBusy) return;
    const kind = selectedKind;
    setActionError(null);
    setMutation({ action: "activate", versionId: version.id });
    void (async () => {
      try {
        await activateInputVersion(version.id);
        if ((await onVersionsChanged()) !== false) {
          message.success(`${version.name} 已启用，将用于新批次`);
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return;
        setActionError({
          kind,
          message: error instanceof Error ? error.message : "启用失败"
        });
      } finally {
        setMutation(null);
      }
    })();
  };

  return {
    uploadError,
    actionError,
    mutation,
    mutationBusy,
    uploading,
    pendingFiles,
    maintenanceOpen,
    setMaintenanceOpen,
    uploadForm,
    selectUploadFile,
    uploadVersion,
    downloadCurrent,
    activateVersion
  };
}
