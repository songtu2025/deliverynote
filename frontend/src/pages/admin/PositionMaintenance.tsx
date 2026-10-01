import { useEffect, useMemo, useRef, useState } from "react";
import { App as AntApp, Modal, Typography } from "antd";
import type { UploadProps } from "antd";

import { usePositionDraftRows } from "./usePositionDraftRows";
import { usePositionDraftSession } from "./usePositionDraftSession";
import { usePositionRowEditor } from "./usePositionRowEditor";
import { usePositionRowMutations } from "./usePositionRowMutations";
import { usePositionImport } from "./usePositionImport";
import { usePositionPublish } from "./usePositionPublish";
import { RowEditorDrawer } from "./RowEditorDrawer";
import * as positionDraftApi from "./positionDraftApi";
import { errorMessage, isRevisionConflict } from "./positionDraftApi";
import { ImportPreviewDialog } from "./ImportPreviewDialog";
import { PublishDialog } from "./PublishDialog";
import { DraftSummary, PositionDraftStatus } from "./PositionFeedback";
import { PositionDraftEntry } from "./PositionDraftEntry";
import { PositionMaintenanceHeader } from "./PositionMaintenanceHeader";
import { PositionDraftRecords } from "./PositionDraftRecords";
import { createPositionRowColumns } from "./positionRowColumns";
import type { InputVersion, PositionDiff } from "../../types";

interface PositionMaintenanceProps {
  activeVersion: InputVersion;
  onPublished: (version: InputVersion) => void;
  onBack: () => void;
}

type BusyAction =
  "save" | "copy" | "delete" | "bulk-delete" | "import-preview" | "import-apply" | "validate" | "publish" | "discard";

const EMPTY_DIFF: PositionDiff = { added: 0, modified: 0, deleted: 0, unchanged: 0 };

export function PositionMaintenance({ onPublished, onBack }: PositionMaintenanceProps) {
  const { message } = AntApp.useApp();
  const [deleteConfirmRowId, setDeleteConfirmRowId] = useState<number | null>(null);
  const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false);
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  const [busyAction, setBusyAction] = useState<BusyAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const editor = usePositionRowEditor(busyAction !== null, onBack);

  const keepDeleteConfirmOpenRef = useRef<number | null>(null);
  const keepBulkDeleteConfirmOpenRef = useRef(false);
  const keepDiscardConfirmOpenRef = useRef(false);
  const importButtonRef = useRef<HTMLButtonElement>(null);
  const publishButtonRef = useRef<HTMLButtonElement>(null);

  const clearLocalState = () => {
    rowMutations.reset();
    editor.reset();
    importFlow.reset();
    publishFlow.reset();
    setDeleteConfirmRowId(null);
    setBulkDeleteConfirmOpen(false);
    setDiscardConfirmOpen(false);
  };

  const session = usePositionDraftSession(clearLocalState);
  const {
    draft,
    entryLoading,
    entryError,
    conflictMessage,
    getRevision,
    recordRevision,
    markConflict: invalidateLocalState
  } = session;
  const rowsState = usePositionDraftRows(draft?.id);
  const { selectedRowIds, setSelectedRowIds, refreshRows } = rowsState;

  const draftUnavailable = busyAction !== null || conflictMessage !== null || !draft || draft.status !== "editing";
  const baseVersionChanged = Boolean(draft && draft.base_version_id !== draft.active_version_id);
  const actionsDisabled = draftUnavailable || baseVersionChanged;
  const discardDisabled = draftUnavailable;

  const loadDraft = async () => {
    rowMutations.reset();
    if (!(await session.loadDraft())) return;
    importFlow.reset();
    publishFlow.reset();
    setSelectedRowIds([]);
    setDeleteConfirmRowId(null);
    setBulkDeleteConfirmOpen(false);
    setDiscardConfirmOpen(false);
    refreshRows();
  };

  useEffect(() => {
    void loadDraft();
    // 创建或恢复由草稿接口决定，目录中的启用版本不触发重复加载。
  }, []);

  const acceptRevision = (revision: number) => {
    session.acceptRevision(revision);
    setSelectedRowIds([]);
    refreshRows();
  };

  const rowMutations = usePositionRowMutations({
    draftId: draft?.id,
    disabled: actionsDisabled,
    getRevision,
    onBusyChange: (action) => {
      setBusyAction(action);
      if (action !== null) setActionError(null);
    },
    onApplied: (revision, messageText) => {
      acceptRevision(revision);
      message.success(messageText);
    },
    onError: setActionError,
    onConflict: invalidateLocalState
  });

  const importFlow = usePositionImport({
    draftId: draft?.id,
    disabled: actionsDisabled,
    getRevision,
    onBusyChange: (action) => {
      setBusyAction(action);
      if (action !== null) setActionError(null);
    },
    onApplied: (revision) => {
      acceptRevision(revision);
      message.success("Excel 已完整替换服务器草稿");
    },
    onConflict: invalidateLocalState
  });

  const restoreImportFocus = () => {
    if (!actionsDisabled) importButtonRef.current?.focus();
  };

  const publishFlow = usePositionPublish({
    draftId: draft?.id,
    disabled: actionsDisabled,
    getRevision,
    onBusyChange: (action) => {
      setBusyAction(action);
      if (action !== null) setActionError(null);
    },
    onValidationError: setActionError,
    onPublished: (published) => {
      recordRevision(published.draft_revision);
      onPublished(published);
      message.success("新库位版本已发布并启用");
    },
    onConflict: (messageText, kind) => {
      if (kind === "revision") invalidateLocalState(messageText);
      else {
        setActionError(messageText);
        void loadDraft();
      }
    }
  });

  const restorePublishFocus = () => {
    if (!actionsDisabled) publishButtonRef.current?.focus();
  };

  const handleActionError = (error: unknown, fallback: string) => {
    const messageText = errorMessage(error, fallback);
    if (isRevisionConflict(error)) {
      invalidateLocalState(messageText);
    } else {
      setActionError(messageText);
    }
  };

  const handleBulkDeleteOpenChange = (open: boolean) => {
    if (!open && keepBulkDeleteConfirmOpenRef.current) {
      keepBulkDeleteConfirmOpenRef.current = false;
      return;
    }
    if (!open && busyAction === "bulk-delete") return;
    setBulkDeleteConfirmOpen(open);
  };

  const handleBulkDeleteConfirm = async () => {
    keepBulkDeleteConfirmOpenRef.current = false;
    if (await rowMutations.bulkDelete(selectedRowIds)) setBulkDeleteConfirmOpen(false);
    else keepBulkDeleteConfirmOpenRef.current = true;
  };

  const previewImport: NonNullable<UploadProps["customRequest"]> = async (options) => {
    const failure = await importFlow.previewFile(options.file as File);
    if (failure) options.onError?.(failure);
    else options.onSuccess?.({});
  };

  const downloadDraft = async () => {
    if (!draft) return;
    setActionError(null);
    try {
      await positionDraftApi.downloadDraft(draft.id, draft.revision);
    } catch (error) {
      setActionError(errorMessage(error, "下载草稿失败"));
    }
  };

  const discardDraft = async () => {
    if (!draft || discardDisabled) return false;
    setBusyAction("discard");
    setActionError(null);
    try {
      await positionDraftApi.discardDraft(draft.id, getRevision());
      setDiscardConfirmOpen(false);
      message.success("服务器草稿已放弃，当前正式版本未改变");
      onBack();
      return true;
    } catch (error) {
      handleActionError(error, "放弃草稿失败");
      return false;
    } finally {
      setBusyAction(null);
    }
  };

  const handleDiscardOpenChange = (open: boolean) => {
    if (!open && keepDiscardConfirmOpenRef.current) {
      keepDiscardConfirmOpenRef.current = false;
      return;
    }
    if (!open && busyAction === "discard") return;
    setDiscardConfirmOpen(open);
  };

  const handleDiscardConfirm = async () => {
    keepDiscardConfirmOpenRef.current = false;
    if (!(await discardDraft())) keepDiscardConfirmOpenRef.current = true;
  };

  const rowColumns = useMemo(
    () =>
      createPositionRowColumns({
        disabled: actionsDisabled,
        copying: busyAction === "copy",
        deleting: busyAction === "delete",
        deleteConfirmRowId,
        onEdit: editor.openEditRow,
        onCopy: async (row) => {
          await rowMutations.copy(row);
        },
        onDeleteOpenChange: (row, open) => {
          if (!open && keepDeleteConfirmOpenRef.current === row.id) {
            keepDeleteConfirmOpenRef.current = null;
            return;
          }
          if (!open && busyAction === "delete") return;
          setDeleteConfirmRowId(open ? row.id : null);
        },
        onDeleteConfirm: async (row) => {
          keepDeleteConfirmOpenRef.current = null;
          if (await rowMutations.deleteRow(row)) setDeleteConfirmRowId(null);
          else keepDeleteConfirmOpenRef.current = row.id;
        }
      }),
    [actionsDisabled, busyAction, deleteConfirmRowId]
  );

  if (!draft) {
    return <PositionDraftEntry loading={entryLoading} error={entryError} onBack={onBack} onRetry={loadDraft} />;
  }

  const diff = draft.diff ?? EMPTY_DIFF;
  return (
    <div className="position-maintenance">
      <PositionMaintenanceHeader
        baseVersionName={draft.base_version_name}
        busy={busyAction !== null}
        actionsDisabled={actionsDisabled}
        importing={busyAction === "import-preview"}
        validating={busyAction === "validate"}
        discarding={busyAction === "discard"}
        discardDisabled={discardDisabled}
        discardConfirmOpen={discardConfirmOpen}
        importButtonRef={importButtonRef}
        publishButtonRef={publishButtonRef}
        onBack={editor.requestBack}
        onDownload={downloadDraft}
        onImport={previewImport}
        onDiscardOpenChange={handleDiscardOpenChange}
        onDiscardConfirm={handleDiscardConfirm}
        onPublish={() => void publishFlow.open()}
      />

      <PositionDraftStatus
        draft={draft}
        baseVersionChanged={baseVersionChanged}
        conflictMessage={conflictMessage}
        refreshing={entryLoading}
        actionError={actionError}
        importError={importFlow.error}
        onRefresh={loadDraft}
        onClearActionError={() => setActionError(null)}
        onClearImportError={importFlow.clearError}
      />

      <DraftSummary draft={draft} diff={diff} />

      <PositionDraftRecords
        rowsState={rowsState}
        columns={rowColumns}
        disabled={actionsDisabled}
        bulkDeleting={busyAction === "bulk-delete"}
        bulkDeleteConfirmOpen={bulkDeleteConfirmOpen}
        onNewRow={editor.openNewRow}
        onBulkDeleteOpenChange={handleBulkDeleteOpenChange}
        onBulkDeleteConfirm={handleBulkDeleteConfirm}
      />

      <RowEditorDrawer
        open={editor.open}
        editingRow={editor.editingRow}
        form={editor.form}
        saving={busyAction === "save"}
        conflicted={conflictMessage !== null}
        onDirty={editor.markDirty}
        onClose={editor.requestClose}
        onSave={() => void editor.save(rowMutations.save)}
      />

      {/* 抽屉一起关闭时由抽屉恢复外部焦点，避免弹窗抢回已销毁的表单控件。 */}
      <Modal
        title="放弃未保存的表单修改？"
        destroyOnHidden
        focusable={{ focusTriggerAfterClose: editor.open }}
        open={editor.pendingLeave !== null}
        okText={editor.pendingLeave === "back" ? "放弃并返回" : "放弃修改"}
        cancelText="继续编辑"
        okButtonProps={{ danger: true, disabled: busyAction !== null }}
        cancelButtonProps={{ disabled: busyAction !== null }}
        onOk={editor.confirmLeave}
        onCancel={editor.cancelLeave}
      >
        <Typography.Paragraph>右侧编辑面板中的内容尚未保存到服务器，离开后无法恢复。</Typography.Paragraph>
      </Modal>

      <ImportPreviewDialog
        preview={importFlow.preview}
        fileName={importFlow.fileName}
        applying={busyAction === "import-apply"}
        onApply={() => void importFlow.apply()}
        onCancel={() => {
          importFlow.cancel();
          restoreImportFocus();
        }}
        onClosed={restoreImportFocus}
      />

      <PublishDialog
        validation={publishFlow.validation}
        versionName={publishFlow.name}
        nameError={publishFlow.nameError}
        publishError={publishFlow.error}
        warningsConfirmed={publishFlow.warningsConfirmed}
        publishing={busyAction === "publish"}
        blocked={publishFlow.blocked}
        onNameChange={publishFlow.changeName}
        onWarningsChange={publishFlow.confirmWarnings}
        onPublish={() => void publishFlow.publish()}
        onCancel={() => {
          publishFlow.cancel();
          restorePublishFocus();
        }}
        onClosed={restorePublishFocus}
      />
    </div>
  );
}
