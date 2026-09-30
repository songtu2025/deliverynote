import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, App as AntApp, Button, Card, Form, Modal, Popconfirm, Space, Spin, Typography, Upload } from "antd";
import { ArrowLeftOutlined, DownloadOutlined, ReloadOutlined, UploadOutlined } from "@ant-design/icons";
import type { UploadProps } from "antd";

import { ApiError } from "../../api";
import { beijingDateTimeParts, formatBeijingDateTime } from "../../dateTime";
import { usePositionDraftRows } from "./usePositionDraftRows";
import { RowEditorDrawer } from "./RowEditorDrawer";
import * as positionDraftApi from "./positionDraftApi";
import type { PositionRevisionResponse, PositionRowValues } from "./positionDraftApi";
import { ImportPreviewDialog } from "./ImportPreviewDialog";
import { PublishDialog } from "./PublishDialog";
import { DraftSummary } from "./PositionFeedback";
import { PositionDraftRecords } from "./PositionDraftRecords";
import { createPositionRowColumns } from "./positionRowColumns";
import type {
  InputVersion,
  PositionDiff,
  PositionDraft,
  PositionDraftRow,
  PositionDraftValidation,
  PositionImportPreview
} from "../../types";

interface PositionMaintenanceProps {
  activeVersion: InputVersion;
  onPublished: (version: InputVersion) => void;
  onBack: () => void;
}

type BusyAction =
  "save" | "copy" | "delete" | "bulk-delete" | "import-preview" | "import-apply" | "validate" | "publish" | "discard";
type PendingLeave = "close" | "back" | null;

const EMPTY_DIFF: PositionDiff = { added: 0, modified: 0, deleted: 0, unchanged: 0 };
const POSITION_ERROR_CODES = {
  revisionConflict: "draft_revision_conflict",
  importPreviewExpired: "draft_import_preview_expired",
  versionNameExists: "input_version_name_exists"
} as const;

function defaultVersionName(): string {
  const parts = beijingDateTimeParts();
  return `position-${parts.year}${parts.month}${parts.day}-${parts.hour}${parts.minute}`;
}

function rowValues(row: PositionDraftRow): PositionRowValues {
  return {
    store_site: row.store_site,
    jiaji_sku: row.jiaji_sku,
    msku: row.msku,
    scale_position: row.scale_position,
    stocking_position: row.stocking_position
  };
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function hasApiCode(error: unknown, code: string): boolean {
  return error instanceof ApiError && error.status === 409 && error.code === code;
}

function isRevisionConflict(error: unknown): boolean {
  return hasApiCode(error, POSITION_ERROR_CODES.revisionConflict);
}

export function PositionMaintenance({ onPublished, onBack }: PositionMaintenanceProps) {
  const { message } = AntApp.useApp();
  const [draft, setDraft] = useState<PositionDraft | null>(null);
  const [entryLoading, setEntryLoading] = useState(true);
  const [entryError, setEntryError] = useState<string | null>(null);
  const rowsState = usePositionDraftRows(draft?.id);
  const { selectedRowIds, setSelectedRowIds, refreshRows } = rowsState;
  const [deleteConfirmRowId, setDeleteConfirmRowId] = useState<number | null>(null);
  const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false);
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  const [busyAction, setBusyAction] = useState<BusyAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerDirty, setDrawerDirty] = useState(false);
  const [editingRow, setEditingRow] = useState<PositionDraftRow | null>(null);
  const [pendingLeave, setPendingLeave] = useState<PendingLeave>(null);
  const [rowForm] = Form.useForm<PositionRowValues>();

  const [importPreview, setImportPreview] = useState<PositionImportPreview | null>(null);
  const [importFileName, setImportFileName] = useState("");
  const [importError, setImportError] = useState<string | null>(null);
  const [publishValidation, setPublishValidation] = useState<PositionDraftValidation | null>(null);
  const [publishName, setPublishName] = useState("");
  const [publishNameError, setPublishNameError] = useState<string | null>(null);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [warningsConfirmed, setWarningsConfirmed] = useState(false);

  const entryRequestRef = useRef(0);
  const metadataRequestRef = useRef(0);
  const revisionRef = useRef(0);
  const keepDeleteConfirmOpenRef = useRef<number | null>(null);
  const keepBulkDeleteConfirmOpenRef = useRef(false);
  const keepDiscardConfirmOpenRef = useRef(false);

  const draftUnavailable = busyAction !== null || conflictMessage !== null || !draft || draft.status !== "editing";
  const baseVersionChanged = Boolean(draft && draft.base_version_id !== draft.active_version_id);
  const actionsDisabled = draftUnavailable || baseVersionChanged;
  const discardDisabled = draftUnavailable;

  const invalidateLocalState = (messageText: string) => {
    setConflictMessage(messageText);
    setDrawerOpen(false);
    setDrawerDirty(false);
    setEditingRow(null);
    if (drawerOpen) rowForm.resetFields();
    setImportPreview(null);
    setPublishValidation(null);
    setPublishNameError(null);
    setPublishError(null);
    setDeleteConfirmRowId(null);
    setBulkDeleteConfirmOpen(false);
    setDiscardConfirmOpen(false);
  };

  const mergeDraftMetadata = (summary: PositionDraft, expectedRevision: number) => {
    if (revisionRef.current !== expectedRevision) return;
    if (summary.revision > expectedRevision) {
      invalidateLocalState("草稿已被其他管理员更新，请刷新后重试");
      return;
    }
    if (summary.revision !== expectedRevision) return;
    setDraft((current) =>
      current && current.id === summary.id && current.revision === expectedRevision
        ? {
            ...current,
            status: summary.status,
            row_count: summary.row_count,
            modified_count: summary.modified_count,
            diff: summary.diff,
            issues: summary.issues,
            error_count: summary.error_count,
            warning_count: summary.warning_count,
            valid: summary.valid,
            updated_by: summary.updated_by,
            updated_at: summary.updated_at,
            active_version_id: summary.active_version_id,
            active_version_name: summary.active_version_name
          }
        : current
    );
  };

  const refreshMetadata = async (expectedRevision: number) => {
    const request = ++metadataRequestRef.current;
    try {
      const summary = await positionDraftApi.getDraft();
      if (request === metadataRequestRef.current) mergeDraftMetadata(summary, expectedRevision);
    } catch {
      // A successful mutation already returned the authoritative revision. Metadata can be refreshed later.
    }
  };

  const loadDraft = async () => {
    const request = ++entryRequestRef.current;
    setEntryLoading(true);
    setEntryError(null);
    try {
      const nextDraft = await positionDraftApi.createOrResumeDraft();
      if (request !== entryRequestRef.current) return;
      revisionRef.current = nextDraft.revision;
      setDraft(nextDraft);
      setConflictMessage(null);
      setImportError(null);
      setSelectedRowIds([]);
      setDeleteConfirmRowId(null);
      setBulkDeleteConfirmOpen(false);
      setDiscardConfirmOpen(false);
      refreshRows();
    } catch (error) {
      if (request === entryRequestRef.current) setEntryError(errorMessage(error, "无法打开库位草稿"));
    } finally {
      if (request === entryRequestRef.current) setEntryLoading(false);
    }
  };

  useEffect(() => {
    void loadDraft();
    return () => {
      entryRequestRef.current += 1;
      metadataRequestRef.current += 1;
    };
    // The position endpoint owns create-or-resume semantics; the active version is informational here.
  }, []);

  const acceptRevision = (revision: number) => {
    revisionRef.current = revision;
    setDraft((current) =>
      current
        ? {
            ...current,
            revision,
            updated_at: new Date().toISOString()
          }
        : current
    );
    setSelectedRowIds([]);
    refreshRows();
    void refreshMetadata(revision);
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

  const openNewRow = () => {
    setEditingRow(null);
    rowForm.setFieldsValue({
      store_site: "",
      jiaji_sku: "",
      msku: "",
      scale_position: "",
      stocking_position: ""
    });
    setDrawerDirty(false);
    setDrawerOpen(true);
  };

  const openEditRow = (row: PositionDraftRow) => {
    setEditingRow(row);
    rowForm.setFieldsValue(rowValues(row));
    setDrawerDirty(false);
    setDrawerOpen(true);
  };

  const requestDrawerClose = () => {
    if (busyAction !== null) return;
    if (drawerDirty) {
      setPendingLeave("close");
      return;
    }
    setDrawerOpen(false);
    setEditingRow(null);
    rowForm.resetFields();
  };

  const requestBack = () => {
    if (busyAction !== null) return;
    if (drawerOpen && drawerDirty) {
      setPendingLeave("back");
      return;
    }
    onBack();
  };

  const confirmLeave = () => {
    if (busyAction !== null) return;
    const leave = pendingLeave;
    setPendingLeave(null);
    setDrawerDirty(false);
    setDrawerOpen(false);
    setEditingRow(null);
    rowForm.resetFields();
    if (leave === "back") onBack();
  };

  const saveRow = async () => {
    if (!draft) return;
    let values: PositionRowValues;
    try {
      values = await rowForm.validateFields();
    } catch {
      return;
    }
    await runRevisionMutation(
      "save",
      () => {
        const payload = { revision: revisionRef.current, ...values };
        return editingRow
          ? positionDraftApi.updateRow(draft.id, editingRow.id, payload)
          : positionDraftApi.createRow(draft.id, payload);
      },
      "记录已保存",
      () => {
        setDrawerDirty(false);
        setDrawerOpen(false);
        setEditingRow(null);
        rowForm.resetFields();
      }
    );
  };

  const copyRow = async (row: PositionDraftRow) => {
    if (!draft) return;
    await runRevisionMutation(
      "copy",
      () => positionDraftApi.createRow(draft.id, { revision: revisionRef.current, ...rowValues(row) }),
      "记录已复制到服务器草稿"
    );
  };

  const deleteRow = async (row: PositionDraftRow) => {
    if (!draft) return false;
    return runRevisionMutation(
      "delete",
      () => positionDraftApi.deleteRow(draft.id, row.id, revisionRef.current),
      "记录已从服务器草稿删除",
      () => setDeleteConfirmRowId(null)
    );
  };

  const bulkDelete = async () => {
    if (!draft || selectedRowIds.length === 0) return false;
    return runRevisionMutation(
      "bulk-delete",
      () => positionDraftApi.deleteRows(draft.id, revisionRef.current, selectedRowIds),
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
    if (!draft || actionsDisabled) {
      options.onError?.(new Error("草稿当前不可修改"));
      return;
    }
    setBusyAction("import-preview");
    setImportError(null);
    setActionError(null);
    try {
      const preview = await positionDraftApi.previewImport(draft.id, revisionRef.current, options.file as File);
      setImportPreview(preview);
      setImportFileName((options.file as File).name ?? "Excel 文件");
      options.onSuccess?.({});
    } catch (error) {
      const messageText = errorMessage(error, "Excel 预览失败");
      if (isRevisionConflict(error)) invalidateLocalState(messageText);
      else setImportError(messageText);
      options.onError?.(error instanceof Error ? error : new Error(messageText));
    } finally {
      setBusyAction(null);
    }
  };

  const applyImport = async () => {
    if (!draft || !importPreview || actionsDisabled) return;
    setBusyAction("import-apply");
    setImportError(null);
    setActionError(null);
    try {
      const result = await positionDraftApi.applyImport(draft.id, revisionRef.current, importPreview.token);
      acceptRevision(result.revision);
      setImportPreview(null);
      message.success("Excel 已完整替换服务器草稿");
    } catch (error) {
      const messageText = errorMessage(error, "应用 Excel 替换失败");
      if (isRevisionConflict(error)) {
        invalidateLocalState(messageText);
      } else {
        if (hasApiCode(error, POSITION_ERROR_CODES.importPreviewExpired)) {
          setImportPreview(null);
          setImportFileName("");
        }
        setImportError(messageText);
      }
    } finally {
      setBusyAction(null);
    }
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

  const openPublish = async () => {
    if (!draft || actionsDisabled) return;
    setBusyAction("validate");
    setActionError(null);
    try {
      const validation = await positionDraftApi.validateDraft(draft.id);
      if (validation.revision !== revisionRef.current) {
        invalidateLocalState("草稿已由其他管理员修改，请刷新后重试");
        return;
      }
      setPublishValidation(validation);
      setPublishName(defaultVersionName());
      setPublishNameError(null);
      setPublishError(null);
      setWarningsConfirmed(false);
    } catch (error) {
      handleActionError(error, "发布前校验失败");
    } finally {
      setBusyAction(null);
    }
  };

  const publishDraft = async () => {
    if (!draft || !publishValidation || !publishName.trim()) return;
    if (publishValidation.error_count > 0 || (publishValidation.warning_count > 0 && !warningsConfirmed)) return;
    setBusyAction("publish");
    setActionError(null);
    setPublishError(null);
    try {
      const published = await positionDraftApi.publishDraft(draft.id, {
        revision: revisionRef.current,
        name: publishName.trim(),
        confirm_warnings: warningsConfirmed
      });
      revisionRef.current = published.draft_revision;
      setPublishValidation(null);
      onPublished(published);
      message.success("新库位版本已发布并启用");
    } catch (error) {
      const messageText = errorMessage(error, "发布失败");
      if (isRevisionConflict(error)) {
        invalidateLocalState(messageText);
      } else if (hasApiCode(error, POSITION_ERROR_CODES.versionNameExists)) {
        setPublishNameError(messageText);
      } else {
        setPublishError(messageText);
      }
    } finally {
      setBusyAction(null);
    }
  };

  const discardDraft = async () => {
    if (!draft || discardDisabled) return false;
    setBusyAction("discard");
    setActionError(null);
    try {
      await positionDraftApi.discardDraft(draft.id, revisionRef.current);
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
        onEdit: openEditRow,
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
  const publishBlocked =
    !publishValidation ||
    publishValidation.error_count > 0 ||
    (publishValidation.warning_count > 0 && !warningsConfirmed) ||
    !publishName.trim();
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
            onClick={requestBack}
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
            onClick={() => void openPublish()}
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
      {importError && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          closable
          title="Excel 替换未完成"
          description={importError}
          onClose={() => setImportError(null)}
        />
      )}

      <DraftSummary draft={draft} diff={diff} />

      <PositionDraftRecords
        rowsState={rowsState}
        columns={rowColumns}
        disabled={actionsDisabled}
        bulkDeleting={busyAction === "bulk-delete"}
        bulkDeleteConfirmOpen={bulkDeleteConfirmOpen}
        onNewRow={openNewRow}
        onBulkDeleteOpenChange={handleBulkDeleteOpenChange}
        onBulkDeleteConfirm={handleBulkDeleteConfirm}
      />

      <RowEditorDrawer
        open={drawerOpen}
        editingRow={editingRow}
        form={rowForm}
        saving={busyAction === "save"}
        conflicted={conflictMessage !== null}
        onDirty={() => setDrawerDirty(true)}
        onClose={requestDrawerClose}
        onSave={() => void saveRow()}
      />

      <Modal
        title="放弃未保存的表单修改？"
        open={pendingLeave !== null}
        okText={pendingLeave === "back" ? "放弃并返回" : "放弃修改"}
        cancelText="继续编辑"
        okButtonProps={{ danger: true, disabled: busyAction !== null }}
        cancelButtonProps={{ disabled: busyAction !== null }}
        onOk={confirmLeave}
        onCancel={() => {
          if (busyAction === null) setPendingLeave(null);
        }}
      >
        <Typography.Paragraph>右侧编辑面板中的内容尚未保存到服务器，离开后无法恢复。</Typography.Paragraph>
      </Modal>

      <ImportPreviewDialog
        preview={importPreview}
        fileName={importFileName}
        applying={busyAction === "import-apply"}
        onApply={() => void applyImport()}
        onCancel={() => {
          if (busyAction === null) setImportPreview(null);
        }}
      />

      <PublishDialog
        validation={publishValidation}
        versionName={publishName}
        nameError={publishNameError}
        publishError={publishError}
        warningsConfirmed={warningsConfirmed}
        publishing={busyAction === "publish"}
        blocked={publishBlocked}
        onNameChange={(value) => {
          setPublishName(value);
          setPublishNameError(null);
        }}
        onWarningsChange={setWarningsConfirmed}
        onPublish={() => void publishDraft()}
        onCancel={() => {
          if (busyAction !== null) return;
          setPublishValidation(null);
          setPublishNameError(null);
          setPublishError(null);
        }}
      />
    </div>
  );
}
