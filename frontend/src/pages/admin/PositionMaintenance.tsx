import { useEffect, useRef, useState } from "react";
import { App as AntApp } from "antd";
import type { UploadProps } from "antd";

import { ApiError } from "../../api";
import { usePositionDraftRows } from "./usePositionDraftRows";
import { usePositionDraftSession } from "./usePositionDraftSession";
import { usePositionRowEditor } from "./usePositionRowEditor";
import { usePositionRowMutations } from "./usePositionRowMutations";
import { usePositionDeleteConfirmation } from "./usePositionDeleteConfirmation";
import { usePositionDraftActions } from "./usePositionDraftActions";
import { usePositionImport } from "./usePositionImport";
import { usePositionPublish } from "./usePositionPublish";
import { RowEditorDrawer } from "./RowEditorDrawer";
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
  onPublished: (version: InputVersion) => void | Promise<boolean>;
  onBack: () => void;
}

type BusyAction =
  "save" | "copy" | "delete" | "bulk-delete" | "import-preview" | "import-apply" | "validate" | "publish" | "discard";

const EMPTY_DIFF: PositionDiff = { added: 0, modified: 0, deleted: 0, unchanged: 0 };

export function PositionMaintenance({ onPublished, onBack }: PositionMaintenanceProps) {
  const { message } = AntApp.useApp();
  const [busyAction, setBusyAction] = useState<BusyAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const editor = usePositionRowEditor(busyAction !== null, onBack);

  const importButtonRef = useRef<HTMLButtonElement>(null);
  const publishButtonRef = useRef<HTMLButtonElement>(null);

  const clearLocalState = () => {
    rowMutations.reset();
    editor.reset();
    importFlow.reset();
    publishFlow.reset();
    deleteConfirmation.reset();
    draftActions.reset();
  };

  const session = usePositionDraftSession(clearLocalState);
  const {
    draft,
    entryLoading,
    entryError,
    conflictMessage,
    getRevision,
    recordRevision,
    loadDraft: loadSessionDraft,
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
    if (!(await loadSessionDraft())) return;
    importFlow.reset();
    publishFlow.reset();
    setSelectedRowIds([]);
    deleteConfirmation.reset();
    draftActions.reset();
    refreshRows();
  };

  useEffect(() => {
    void loadSessionDraft();
    // 创建或恢复由草稿接口决定，目录中的启用版本不触发重复加载。
  }, [loadSessionDraft]);

  const acceptRevision = (revision: number) => {
    session.acceptRevision(revision);
    setSelectedRowIds([]);
    refreshRows();
  };

  const changeBusyAction = (action: BusyAction | null) => {
    setBusyAction(action);
    if (action !== null) setActionError(null);
  };

  const rowMutations = usePositionRowMutations({
    draftId: draft?.id,
    disabled: actionsDisabled,
    getRevision,
    onBusyChange: changeBusyAction,
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
    onBusyChange: changeBusyAction,
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
    onBusyChange: changeBusyAction,
    onValidationError: setActionError,
    onPublished: async (published) => {
      recordRevision(published.draft_revision);
      try {
        if ((await onPublished(published)) !== false) message.success("新库位版本已发布并启用");
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) message.warning("版本已发布，但读取基础资料目录失败");
      }
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

  const deleteConfirmation = usePositionDeleteConfirmation({
    deleting: busyAction === "delete",
    bulkDeleting: busyAction === "bulk-delete",
    selectedRowIds,
    mutations: rowMutations
  });
  const draftActions = usePositionDraftActions({
    draft,
    disabled: discardDisabled,
    getRevision,
    onBusyChange: changeBusyAction,
    onError: setActionError,
    onConflict: invalidateLocalState,
    onDiscarded: () => {
      message.success("服务器草稿已放弃，当前正式版本未改变");
      onBack();
    }
  });

  const previewImport: NonNullable<UploadProps["customRequest"]> = async (options) => {
    const failure = await importFlow.previewFile(options.file as File);
    if (failure === false) return;
    if (failure) options.onError?.(failure);
    else options.onSuccess?.({});
  };

  const rowColumns = createPositionRowColumns({
    disabled: actionsDisabled,
    copying: busyAction === "copy",
    deleting: busyAction === "delete",
    deleteConfirmRowId: deleteConfirmation.rowId,
    onEdit: editor.openEditRow,
    onCopy: async (row) => {
      await rowMutations.copy(row);
    },
    onDeleteOpenChange: deleteConfirmation.changeRowOpen,
    onDeleteConfirm: deleteConfirmation.confirmRow
  });

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
        discardConfirmOpen={draftActions.confirmOpen}
        importButtonRef={importButtonRef}
        publishButtonRef={publishButtonRef}
        onBack={editor.requestBack}
        onDownload={draftActions.download}
        onImport={previewImport}
        onDiscardOpenChange={draftActions.changeConfirmOpen}
        onDiscardConfirm={draftActions.confirmDiscard}
        onPublish={() => void publishFlow.open()}
      />

      <PositionDraftStatus
        draft={draft}
        baseVersionChanged={baseVersionChanged}
        conflictMessage={conflictMessage}
        refreshing={entryLoading}
        actionError={actionError}
        importError={importFlow.error}
        metadata={session}
        onRefresh={loadDraft}
        onClearActionError={() => setActionError(null)}
        onClearImportError={importFlow.clearError}
      />

      <DraftSummary draft={draft} diff={diff} stale={session.metadataStale} />

      <PositionDraftRecords
        rowsState={rowsState}
        columns={rowColumns}
        disabled={actionsDisabled}
        bulkDeleting={busyAction === "bulk-delete"}
        bulkDeleteConfirmOpen={deleteConfirmation.bulkOpen}
        onNewRow={editor.openNewRow}
        onBulkDeleteOpenChange={deleteConfirmation.changeBulkOpen}
        onBulkDeleteConfirm={deleteConfirmation.confirmBulk}
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
        leaveConfirmation={editor}
        busy={busyAction !== null}
      />

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
