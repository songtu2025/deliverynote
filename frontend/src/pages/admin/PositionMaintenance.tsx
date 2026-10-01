import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, App as AntApp, Button, Card, Modal, Popconfirm, Space, Spin, Typography, Upload } from "antd";
import { ArrowLeftOutlined, DownloadOutlined, ReloadOutlined, UploadOutlined } from "@ant-design/icons";
import type { UploadProps } from "antd";

import { formatBeijingDateTime } from "../../dateTime";
import { usePositionDraftRows } from "./usePositionDraftRows";
import { usePositionDraftSession } from "./usePositionDraftSession";
import { rowValues, usePositionRowEditor } from "./usePositionRowEditor";
import { usePositionImport } from "./usePositionImport";
import { usePositionPublish } from "./usePositionPublish";
import { RowEditorDrawer } from "./RowEditorDrawer";
import * as positionDraftApi from "./positionDraftApi";
import type { PositionRevisionResponse } from "./positionDraftApi";
import { errorMessage, isRevisionConflict } from "./positionDraftApi";
import { ImportPreviewDialog } from "./ImportPreviewDialog";
import { PublishDialog } from "./PublishDialog";
import { DraftSummary } from "./PositionFeedback";
import { PositionDraftRecords } from "./PositionDraftRecords";
import { createPositionRowColumns } from "./positionRowColumns";
import type { InputVersion, PositionDiff, PositionDraftRow } from "../../types";

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

  const runRevisionMutation = async <T extends PositionRevisionResponse>(
    action: BusyAction,
    request: () => Promise<T>,
    successMessage: string,
    afterSuccess?: (result: T) => void
  ): Promise<boolean> => {
    if (actionsDisabled) return false;
    setBusyAction(action);
    setActionError(null);
    try {
      const result = await request();
      acceptRevision(result.revision);
      afterSuccess?.(result);
      message.success(successMessage);
      return true;
    } catch (error) {
      handleActionError(error, `${successMessage}失败`);
      return false;
    } finally {
      setBusyAction(null);
    }
  };

  const saveRow = async () => {
    if (!draft) return;
    await editor.save((values, row) =>
      runRevisionMutation(
        "save",
        () => {
          const payload = { revision: getRevision(), ...values };
          return row
            ? positionDraftApi.updateRow(draft.id, row.id, payload)
            : positionDraftApi.createRow(draft.id, payload);
        },
        "记录已保存"
      )
    );
  };

  const copyRow = async (row: PositionDraftRow) => {
    if (!draft) return;
    await runRevisionMutation(
      "copy",
      () => positionDraftApi.createRow(draft.id, { revision: getRevision(), ...rowValues(row) }),
      "记录已复制到服务器草稿"
    );
  };

  const deleteRow = async (row: PositionDraftRow) => {
    if (!draft) return false;
    return runRevisionMutation(
      "delete",
      () => positionDraftApi.deleteRow(draft.id, row.id, getRevision()),
      "记录已从服务器草稿删除",
      () => setDeleteConfirmRowId(null)
    );
  };

  const bulkDelete = async () => {
    if (!draft || selectedRowIds.length === 0) return false;
    return runRevisionMutation(
      "bulk-delete",
      () => positionDraftApi.deleteRows(draft.id, getRevision(), selectedRowIds),
      `已删除 ${selectedRowIds.length} 条草稿记录`,
      () => setBulkDeleteConfirmOpen(false)
    );
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
    if (!(await bulkDelete())) keepBulkDeleteConfirmOpenRef.current = true;
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

  const rowColumns = useMemo(
    () =>
      createPositionRowColumns({
        disabled: actionsDisabled,
        copying: busyAction === "copy",
        deleting: busyAction === "delete",
        deleteConfirmRowId,
        onEdit: editor.openEditRow,
        onCopy: copyRow,
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
          if (!(await deleteRow(row))) keepDeleteConfirmOpenRef.current = row.id;
        }
      }),
    [actionsDisabled, busyAction, deleteConfirmRowId]
  );

  if (entryLoading && !draft) {
    return (
      <div>
        <Button
          autoFocus
          aria-label="返回基础资料"
          className="back-link"
          type="link"
          icon={<ArrowLeftOutlined />}
          onClick={onBack}
        >
          返回基础资料
        </Button>
        <div style={{ minHeight: 360, display: "grid", placeItems: "center" }}>
          <Spin size="large" description="正在创建或恢复服务器草稿" />
        </div>
      </div>
    );
  }

  if (entryError && !draft) {
    return (
      <div>
        <Button
          autoFocus
          aria-label="返回基础资料"
          className="back-link"
          type="link"
          icon={<ArrowLeftOutlined />}
          onClick={onBack}
        >
          返回基础资料
        </Button>
        <Card>
          <Alert
            type="error"
            showIcon
            title="无法打开库位草稿"
            description={entryError}
            action={
              <Button icon={<ReloadOutlined />} onClick={() => void loadDraft()}>
                重新尝试
              </Button>
            }
          />
        </Card>
      </div>
    );
  }

  if (!draft) return null;

  const diff = draft.diff ?? EMPTY_DIFF;
  return (
    <div className="position-maintenance">
      <div className="position-workspace-heading">
        <div className="position-workspace-title">
          <Button
            autoFocus
            aria-label="返回基础资料"
            className="back-link"
            type="link"
            icon={<ArrowLeftOutlined />}
            disabled={busyAction !== null}
            onClick={editor.requestBack}
          >
            返回基础资料
          </Button>
          <Typography.Title level={2} style={{ margin: 0 }}>
            MSKU 定位维护
          </Typography.Title>
          <Typography.Text type="secondary">
            基于 {draft.base_version_name}；修改自动保存到草稿，发布后生效。
          </Typography.Text>
        </div>
        <Space wrap className="position-workspace-actions">
          <Button aria-label="下载草稿" icon={<DownloadOutlined />} onClick={() => void downloadDraft()}>
            下载草稿
          </Button>
          <Upload accept=".xls,.xlsx" showUploadList={false} disabled={actionsDisabled} customRequest={previewImport}>
            <Button
              ref={importButtonRef}
              aria-label="Excel 整表替换"
              icon={<UploadOutlined />}
              disabled={actionsDisabled}
              loading={busyAction === "import-preview"}
            >
              Excel 整表替换
            </Button>
          </Upload>
          <Popconfirm
            fresh
            open={discardConfirmOpen}
            title="确定放弃整个服务器草稿？"
            description="草稿中的所有修改都会丢失，当前正式版本保持不变。"
            okText="确认放弃"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            cancelButtonProps={{ disabled: busyAction === "discard" }}
            onOpenChange={(open) => {
              if (!open && keepDiscardConfirmOpenRef.current) {
                keepDiscardConfirmOpenRef.current = false;
                return;
              }
              if (!open && busyAction === "discard") return;
              setDiscardConfirmOpen(open);
            }}
            onConfirm={async () => {
              keepDiscardConfirmOpenRef.current = false;
              if (!(await discardDraft())) keepDiscardConfirmOpenRef.current = true;
            }}
          >
            <Button danger disabled={discardDisabled} loading={busyAction === "discard"}>
              放弃草稿
            </Button>
          </Popconfirm>
          <Button
            type="primary"
            disabled={actionsDisabled}
            loading={busyAction === "validate"}
            ref={publishButtonRef}
            onClick={() => void publishFlow.open()}
          >
            发布新版本
          </Button>
        </Space>
      </div>

      <Alert
        className="inline-alert position-save-status"
        type="success"
        showIcon
        title="草稿已自动保存"
        description={
          <Space wrap separator={<span aria-hidden="true">·</span>}>
            <span>修订号 {draft.revision}</span>
            <span>最后更新 {formatBeijingDateTime(draft.updated_at)}</span>
            <span>最后编辑人：用户 #{draft.updated_by}</span>
          </Space>
        }
      />

      {baseVersionChanged && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          title="草稿基线已过期"
          description={`正式版本已变为 ${draft.active_version_name ?? "无启用版本"}。请放弃当前草稿后重新维护。`}
        />
      )}

      {conflictMessage && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          title="草稿已在其他位置更新"
          description={conflictMessage}
          action={
            <Button
              aria-label="刷新草稿"
              icon={<ReloadOutlined />}
              loading={entryLoading}
              onClick={() => void loadDraft()}
            >
              刷新草稿
            </Button>
          }
        />
      )}
      {actionError && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          closable
          title="操作失败"
          description={actionError}
          onClose={() => setActionError(null)}
        />
      )}
      {importFlow.error && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          closable
          title="Excel 替换未完成"
          description={importFlow.error}
          onClose={importFlow.clearError}
        />
      )}

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
        onSave={() => void saveRow()}
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
