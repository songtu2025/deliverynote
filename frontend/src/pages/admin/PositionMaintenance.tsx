import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
  message
} from "antd";
import {
  ArrowLeftOutlined,
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  UploadOutlined
} from "@ant-design/icons";
import type { FormInstance, TableProps, UploadProps } from "antd";

import { ApiError, api, download } from "../../api";
import type {
  InputVersion,
  PositionDiff,
  PositionDraft,
  PositionDraftRow,
  PositionDraftRowsPage,
  PositionDraftValidation,
  PositionImportPreview,
  PositionIssue
} from "../../types";

interface PositionMaintenanceProps {
  activeVersion: InputVersion;
  onPublished: (version: InputVersion) => void;
  onBack: () => void;
}

interface PositionRowValues {
  store_site: string;
  jiaji_sku: string;
  msku: string;
  scale_position: string;
  stocking_position: string;
  ordered_days: string;
}

interface RevisionResponse {
  revision: number;
}

interface PublishResponse extends InputVersion {
  draft_revision: number;
  draft_status: PositionDraft["status"];
}

type BusyAction = "save" | "copy" | "delete" | "bulk-delete" | "import-preview" | "import-apply" | "validate" | "publish" | "discard";
type PendingLeave = "close" | "back" | null;

const EMPTY_DIFF: PositionDiff = { added: 0, modified: 0, deleted: 0, unchanged: 0 };
const ROW_PAGE_SIZE = 20;
const SCALE_OPTIONS = ["短尾", "中尾", "长尾"].map((value) => ({ value }));
const REVISION_CONFLICT_DETAILS = [
  "草稿已被其他管理员更新，请刷新后重试",
  "草稿写入发生并发冲突，请刷新后重试"
];

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN");
}

function defaultVersionName(): string {
  const date = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `position-${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}`;
}

function rowValues(row: PositionDraftRow): PositionRowValues {
  return {
    store_site: row.store_site,
    jiaji_sku: row.jiaji_sku,
    msku: row.msku,
    scale_position: row.scale_position,
    stocking_position: row.stocking_position,
    ordered_days: row.ordered_days
  };
}

function rowActionLabel(action: string, row: PositionDraftRow): string {
  return `${action} ${row.store_site} / ${row.jiaji_sku} / ${row.msku || "无 MSKU"}`;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function hasApiDetail(error: unknown, detail: string): boolean {
  return error instanceof ApiError && error.status === 409 && error.message.includes(detail);
}

function isRevisionConflict(error: unknown): boolean {
  return error instanceof ApiError
    && error.status === 409
    && REVISION_CONFLICT_DETAILS.some((detail) => error.message.includes(detail));
}

function issueRows(issue: PositionIssue): string {
  return issue.row_numbers.length > 0 ? `第 ${issue.row_numbers.join("、")} 行` : "全表";
}

function DiffTags({ diff }: { diff: PositionDiff }) {
  return (
    <Space wrap size={[6, 6]}>
      <Tag color="green">新增 {diff.added}</Tag>
      <Tag color="blue">修改 {diff.modified}</Tag>
      <Tag color="red">删除 {diff.deleted}</Tag>
      <Tag>未变化 {diff.unchanged}</Tag>
    </Space>
  );
}

function IssueList({ issues }: { issues: PositionIssue[] }) {
  if (issues.length === 0) return <Typography.Text type="secondary">没有发现问题</Typography.Text>;
  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      {issues.map((issue, index) => (
        <Alert
          key={`${issue.code}-${index}-${issue.row_numbers.join("-")}`}
          type={issue.severity}
          showIcon
          title={issue.message}
          description={issueRows(issue)}
        />
      ))}
    </Space>
  );
}

function RowEditorDrawer({
  open,
  editingRow,
  form,
  saving,
  conflicted,
  onDirty,
  onClose,
  onSave
}: {
  open: boolean;
  editingRow: PositionDraftRow | null;
  form: FormInstance<PositionRowValues>;
  saving: boolean;
  conflicted: boolean;
  onDirty: () => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <Drawer
      title={editingRow ? `编辑库位记录：${editingRow.jiaji_sku}` : "新增库位记录"}
      size="large"
      open={open}
      destroyOnHidden
      closable={!saving}
      keyboard={!saving}
      maskClosable={false}
      onClose={() => {
        if (!saving) onClose();
      }}
      footer={(
        <div className="drawer-footer">
          <Button disabled={saving} onClick={onClose}>取消</Button>
          <Button type="primary" loading={saving} disabled={conflicted} onClick={onSave}>保存到草稿</Button>
        </div>
      )}
    >
      <Alert
        className="inline-alert"
        type="info"
        showIcon
        title="保存后立即写入服务器草稿"
        description="店铺-站点和积加 SKU 为必填；其他字段保留现有自定义文本。"
      />
      <Form<PositionRowValues> form={form} layout="vertical" requiredMark="optional" onValuesChange={onDirty}>
        <Form.Item
          label="店铺-站点"
          name="store_site"
          extra="用于与待处理数据的站点精确匹配，例如 SEEKWAY:US。"
          rules={[{ required: true, whitespace: true, message: "请输入店铺-站点" }]}
        >
          <Input aria-label="店铺-站点" placeholder="例如：SEEKWAY:US" />
        </Form.Item>
        <Form.Item
          label="积加 SKU"
          name="jiaji_sku"
          extra="与店铺-站点共同组成主要匹配键。"
          rules={[{ required: true, whitespace: true, message: "请输入积加 SKU" }]}
        >
          <Input aria-label="积加 SKU" placeholder="例如：SKU-A" />
        </Form.Item>
        <Form.Item label="MSKU" name="msku" extra="同一站点和积加 SKU 有多行时，MSKU 必须填写且唯一。">
          <Input aria-label="MSKU" placeholder="可留空" />
        </Form.Item>
        <Form.Item label="规模定位" name="scale_position" extra="常用值为短尾、中尾、长尾；已有自定义值可以继续保留。">
          <AutoComplete aria-label="规模定位" options={SCALE_OPTIONS} placeholder="选择常用值或输入自定义值" />
        </Form.Item>
        <Form.Item label="备货定位" name="stocking_position" extra="用于补充待处理导出中的备货定位。">
          <Input aria-label="备货定位" placeholder="例如：备货" />
        </Form.Item>
        <Form.Item label="已下单可售天数" name="ordered_days" extra="保留源资料文本，常见值为数字天数。">
          <Input aria-label="已下单可售天数" placeholder="例如：90" />
        </Form.Item>
      </Form>
    </Drawer>
  );
}

function ImportPreviewDialog({
  preview,
  fileName,
  applying,
  onApply,
  onCancel
}: {
  preview: PositionImportPreview | null;
  fileName: string;
  applying: boolean;
  onApply: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      title="Excel 整表替换预览"
      open={preview !== null}
      okText="应用整表替换"
      cancelText="取消"
      okButtonProps={{ danger: true }}
      cancelButtonProps={{ disabled: applying }}
      confirmLoading={applying}
      closable={!applying}
      keyboard={!applying}
      mask={{ closable: !applying }}
      onOk={onApply}
      onCancel={() => {
        if (!applying) onCancel();
      }}
    >
      {preview && (
        <Space orientation="vertical" size={14} style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            title={`即将用 ${fileName} 的 ${preview.row_count} 行完整替换当前草稿`}
            description="只有确认应用后才会修改服务器草稿；当前正式版本不会改变。"
          />
          <DiffTags diff={preview.diff} />
          <Typography.Text>错误 {preview.error_count} · 警告 {preview.warning_count}</Typography.Text>
          <IssueList issues={preview.issues} />
        </Space>
      )}
    </Modal>
  );
}

function PublishDialog({
  validation,
  versionName,
  nameError,
  publishError,
  warningsConfirmed,
  publishing,
  blocked,
  onNameChange,
  onWarningsChange,
  onPublish,
  onCancel
}: {
  validation: PositionDraftValidation | null;
  versionName: string;
  nameError: string | null;
  publishError: string | null;
  warningsConfirmed: boolean;
  publishing: boolean;
  blocked: boolean;
  onNameChange: (value: string) => void;
  onWarningsChange: (checked: boolean) => void;
  onPublish: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      title="发布新的库位/排仓版本"
      open={validation !== null}
      styles={{ body: { maxHeight: "calc(100vh - 300px)", overflowY: "auto" } }}
      okText="确认发布"
      cancelText="继续修改草稿"
      okButtonProps={{ disabled: blocked }}
      cancelButtonProps={{ disabled: publishing }}
      confirmLoading={publishing}
      closable={!publishing}
      keyboard={!publishing}
      mask={{ closable: !publishing }}
      onOk={onPublish}
      onCancel={() => {
        if (!publishing) onCancel();
      }}
    >
      {validation && (
        <Space orientation="vertical" size={14} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            title="只影响之后批次，历史批次不变"
            description="发布会创建并启用新的正式版本；已有批次继续使用创建时锁定的旧版本。"
          />
          <Form layout="vertical">
            <Form.Item label="新版本名称" required validateStatus={nameError ? "error" : undefined} help={nameError}>
              <Input aria-label="新版本名称" value={versionName} maxLength={200} onChange={(event) => onNameChange(event.target.value)} />
            </Form.Item>
          </Form>
          {publishError && <Alert type="error" showIcon title="发布未完成" description={publishError} />}
          <DiffTags diff={validation.diff} />
          {validation.error_count > 0 && <Alert type="error" showIcon title={`存在 ${validation.error_count} 个错误，修正后才能发布`} />}
          {validation.warning_count > 0 && <Alert type="warning" showIcon title={`存在 ${validation.warning_count} 个警告，请确认后发布`} />}
          <IssueList issues={validation.issues} />
          {validation.warning_count > 0 && (
            <Checkbox checked={warningsConfirmed} onChange={(event) => onWarningsChange(event.target.checked)}>
              我已检查并确认发布这些警告
            </Checkbox>
          )}
        </Space>
      )}
    </Modal>
  );
}

export function PositionMaintenance({ activeVersion, onPublished, onBack }: PositionMaintenanceProps) {
  const [draft, setDraft] = useState<PositionDraft | null>(null);
  const [entryLoading, setEntryLoading] = useState(true);
  const [entryError, setEntryError] = useState<string | null>(null);
  const [rows, setRows] = useState<PositionDraftRow[]>([]);
  const [rowsTotal, setRowsTotal] = useState(0);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [rowsError, setRowsError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [site, setSite] = useState("");
  const [scale, setScale] = useState("");
  const [issueFilter, setIssueFilter] = useState<"all" | "errors">("all");
  const [onlyModified, setOnlyModified] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(ROW_PAGE_SIZE);
  const [refreshRowsKey, setRefreshRowsKey] = useState(0);
  const [selectedRowIds, setSelectedRowIds] = useState<number[]>([]);
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
  const rowsRequestRef = useRef(0);
  const metadataRequestRef = useRef(0);
  const revisionRef = useRef(0);
  const keepDeleteConfirmOpenRef = useRef<number | null>(null);
  const keepBulkDeleteConfirmOpenRef = useRef(false);
  const keepDiscardConfirmOpenRef = useRef(false);

  const draftUnavailable = busyAction !== null || conflictMessage !== null || !draft || draft.status !== "editing";
  const baseVersionChanged = Boolean(draft && draft.base_version_id !== activeVersion.id);
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
    setDraft((current) => current && current.id === summary.id && current.revision === expectedRevision ? {
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
      updated_at: summary.updated_at
    } : current);
  };

  const refreshMetadata = async (expectedRevision: number) => {
    const request = ++metadataRequestRef.current;
    try {
      const summary = await api<PositionDraft>("/api/input-drafts/position");
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
      const nextDraft = await api<PositionDraft>("/api/input-drafts/position", { method: "POST" });
      if (request !== entryRequestRef.current) return;
      revisionRef.current = nextDraft.revision;
      setDraft(nextDraft);
      setConflictMessage(null);
      setImportError(null);
      setSelectedRowIds([]);
      setDeleteConfirmRowId(null);
      setBulkDeleteConfirmOpen(false);
      setDiscardConfirmOpen(false);
      setRefreshRowsKey((value) => value + 1);
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
      rowsRequestRef.current += 1;
      metadataRequestRef.current += 1;
    };
    // The position endpoint owns create-or-resume semantics; the active version is informational here.
  }, []);

  useEffect(() => {
    if (!draft) return undefined;
    const request = ++rowsRequestRef.current;
    const params = new URLSearchParams({
      offset: String((page - 1) * pageSize),
      limit: String(pageSize)
    });
    if (search.trim()) params.set("search", search.trim());
    if (site.trim()) params.set("site", site.trim());
    if (scale.trim()) params.set("scale_position", scale.trim());
    if (issueFilter === "errors") params.set("only_errors", "true");
    if (onlyModified) params.set("only_modified", "true");
    setRowsLoading(true);
    setRowsError(null);
    void api<PositionDraftRowsPage>(`/api/input-drafts/${draft.id}/rows?${params.toString()}`)
      .then((result) => {
        if (request !== rowsRequestRef.current) return;
        setRows(result.rows);
        setRowsTotal(result.total);
        setSelectedRowIds((current) => current.filter((id) => result.rows.some((row) => row.id === id)));
      })
      .catch((error: unknown) => {
        if (request !== rowsRequestRef.current) return;
        setRows([]);
        setRowsTotal(0);
        setRowsError(errorMessage(error, "读取草稿记录失败"));
      })
      .finally(() => {
        if (request === rowsRequestRef.current) setRowsLoading(false);
      });
    return undefined;
  }, [draft?.id, issueFilter, onlyModified, page, pageSize, refreshRowsKey, scale, search, site]);

  const acceptRevision = (revision: number) => {
    revisionRef.current = revision;
    setDraft((current) => current ? {
      ...current,
      revision,
      updated_at: new Date().toISOString()
    } : current);
    setSelectedRowIds([]);
    setRefreshRowsKey((value) => value + 1);
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

  const runRevisionMutation = async <T extends RevisionResponse>(
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
      stocking_position: "",
      ordered_days: ""
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
    const path = editingRow
      ? `/api/input-drafts/${draft.id}/rows/${editingRow.id}`
      : `/api/input-drafts/${draft.id}/rows`;
    await runRevisionMutation(
      "save",
      () => api<RevisionResponse>(path, {
        method: editingRow ? "PUT" : "POST",
        body: JSON.stringify({ revision: revisionRef.current, ...values })
      }),
      "记录已保存到服务器草稿",
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
      () => api<RevisionResponse>(`/api/input-drafts/${draft.id}/rows`, {
        method: "POST",
        body: JSON.stringify({ revision: revisionRef.current, ...rowValues(row) })
      }),
      "记录已复制到服务器草稿"
    );
  };

  const deleteRow = async (row: PositionDraftRow) => {
    if (!draft) return false;
    return runRevisionMutation(
      "delete",
      () => api<RevisionResponse>(`/api/input-drafts/${draft.id}/rows/${row.id}`, {
        method: "DELETE",
        body: JSON.stringify({ revision: revisionRef.current })
      }),
      "记录已从服务器草稿删除",
      () => setDeleteConfirmRowId(null)
    );
  };

  const bulkDelete = async () => {
    if (!draft || selectedRowIds.length === 0) return false;
    return runRevisionMutation(
      "bulk-delete",
      () => api<RevisionResponse>(`/api/input-drafts/${draft.id}/rows/bulk-delete`, {
        method: "POST",
        body: JSON.stringify({ revision: revisionRef.current, row_ids: selectedRowIds })
      }),
      `已删除 ${selectedRowIds.length} 条草稿记录`,
      () => setBulkDeleteConfirmOpen(false)
    );
  };

  const previewImport: NonNullable<UploadProps["customRequest"]> = async (options) => {
    if (!draft || actionsDisabled) {
      options.onError?.(new Error("草稿当前不可修改"));
      return;
    }
    setBusyAction("import-preview");
    setImportError(null);
    setActionError(null);
    const formData = new FormData();
    formData.append("revision", String(revisionRef.current));
    formData.append("file", options.file as File);
    try {
      const preview = await api<PositionImportPreview>(`/api/input-drafts/${draft.id}/import-preview`, {
        method: "POST",
        body: formData
      });
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
      const result = await api<RevisionResponse>(`/api/input-drafts/${draft.id}/import-apply`, {
        method: "POST",
        body: JSON.stringify({ revision: revisionRef.current, token: importPreview.token })
      });
      acceptRevision(result.revision);
      setImportPreview(null);
      message.success("Excel 已完整替换服务器草稿");
    } catch (error) {
      const messageText = errorMessage(error, "应用 Excel 替换失败");
      if (isRevisionConflict(error)) {
        invalidateLocalState(messageText);
      } else {
        if (hasApiDetail(error, "导入预览已失效，请重新预览")) {
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
      await download(`/api/input-drafts/${draft.id}/download`, `position-draft-r${draft.revision}.xlsx`);
    } catch (error) {
      setActionError(errorMessage(error, "下载草稿失败"));
    }
  };

  const openPublish = async () => {
    if (!draft || actionsDisabled) return;
    setBusyAction("validate");
    setActionError(null);
    try {
      const validation = await api<PositionDraftValidation>(`/api/input-drafts/${draft.id}/validate`, { method: "POST" });
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
      const published = await api<PublishResponse>(`/api/input-drafts/${draft.id}/publish`, {
        method: "POST",
        body: JSON.stringify({
          revision: revisionRef.current,
          name: publishName.trim(),
          confirm_warnings: warningsConfirmed
        })
      });
      revisionRef.current = published.draft_revision;
      setPublishValidation(null);
      onPublished(published);
      message.success("新库位版本已发布并启用");
    } catch (error) {
      const messageText = errorMessage(error, "发布失败");
      if (isRevisionConflict(error)) {
        invalidateLocalState(messageText);
      } else if (hasApiDetail(error, "版本名称已存在")) {
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
      await api<PositionDraft>(`/api/input-drafts/${draft.id}/discard`, {
        method: "POST",
        body: JSON.stringify({ revision: revisionRef.current })
      });
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

  const rowColumns = useMemo<NonNullable<TableProps<PositionDraftRow>["columns"]>>(() => [
    { title: "店铺-站点", dataIndex: "store_site", width: 170, fixed: "left" },
    { title: "积加 SKU", dataIndex: "jiaji_sku", width: 150 },
    { title: "MSKU", dataIndex: "msku", width: 150, render: (value: string) => value || "—" },
    { title: "规模定位", dataIndex: "scale_position", width: 110, render: (value: string) => value || "—" },
    { title: "备货定位", dataIndex: "stocking_position", width: 120, render: (value: string) => value || "—" },
    { title: "已下单可售天数", dataIndex: "ordered_days", width: 150, render: (value: string) => value || "—" },
    {
      title: "修改状态",
      dataIndex: "change_type",
      width: 110,
      render: (value: PositionDraftRow["change_type"]) => {
        const definitions = {
          unchanged: { color: "default", label: "未变化" },
          added: { color: "green", label: "新增" },
          modified: { color: "blue", label: "已修改" },
          deleted: { color: "red", label: "已删除" }
        } as const;
        const definition = definitions[value];
        return <Tag color={definition.color}>{definition.label}</Tag>;
      }
    },
    {
      title: "问题",
      dataIndex: "issues",
      width: 100,
      render: (issues: PositionIssue[]) => issues.length === 0
        ? <Typography.Text type="secondary">无</Typography.Text>
        : <Tag color={issues.some((issue) => issue.severity === "error") ? "error" : "warning"}>{issues.length} 项</Tag>
    },
    {
      title: "操作",
      key: "actions",
      width: 210,
      fixed: "right",
      render: (_, row) => (
        <Space size={2}>
          <Button
            type="link"
            aria-label={rowActionLabel("编辑", row)}
            icon={<EditOutlined />}
            disabled={actionsDisabled}
            onClick={() => openEditRow(row)}
          >
            编辑
          </Button>
          <Button
            type="link"
            aria-label={rowActionLabel("复制", row)}
            icon={<CopyOutlined />}
            disabled={actionsDisabled}
            loading={busyAction === "copy"}
            onClick={() => void copyRow(row)}
          >
            复制
          </Button>
          <Popconfirm
            fresh
            open={deleteConfirmRowId === row.id}
            title={`删除 ${row.jiaji_sku}？`}
            description="删除会立即保存到服务器草稿，发布前不会影响正式版本。"
            okText="确认删除"
            cancelText="取消"
            cancelButtonProps={{ disabled: busyAction === "delete" && deleteConfirmRowId === row.id }}
            onOpenChange={(open) => {
              if (!open && keepDeleteConfirmOpenRef.current === row.id) {
                keepDeleteConfirmOpenRef.current = null;
                return;
              }
              if (!open && busyAction === "delete") return;
              setDeleteConfirmRowId(open ? row.id : null);
            }}
            onConfirm={async () => {
              keepDeleteConfirmOpenRef.current = null;
              if (!await deleteRow(row)) keepDeleteConfirmOpenRef.current = row.id;
            }}
          >
            <Button
              type="link"
              danger
              aria-label={rowActionLabel("删除", row)}
              icon={<DeleteOutlined />}
              disabled={actionsDisabled}
              loading={busyAction === "delete"}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      )
    }
  ], [actionsDisabled, busyAction, deleteConfirmRowId]);

  if (entryLoading && !draft) {
    return (
      <div>
        <Button aria-label="返回基础资料" className="back-link" type="link" icon={<ArrowLeftOutlined />} onClick={onBack}>
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
        <Button aria-label="返回基础资料" className="back-link" type="link" icon={<ArrowLeftOutlined />} onClick={onBack}>
          返回基础资料
        </Button>
        <Card>
          <Alert
            type="error"
            showIcon
            title="无法打开库位草稿"
            description={entryError}
            action={<Button icon={<ReloadOutlined />} onClick={() => void loadDraft()}>重新尝试</Button>}
          />
        </Card>
      </div>
    );
  }

  if (!draft) return null;

  const diff = draft.diff ?? EMPTY_DIFF;
  const publishBlocked = !publishValidation
    || publishValidation.error_count > 0
    || (publishValidation.warning_count > 0 && !warningsConfirmed)
    || !publishName.trim();

  return (
    <div className="position-maintenance">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 20, marginBottom: 18 }}>
        <div>
          <Button aria-label="返回基础资料" className="back-link" type="link" icon={<ArrowLeftOutlined />} disabled={busyAction !== null} onClick={requestBack}>
            返回基础资料
          </Button>
          <Typography.Title level={2} style={{ margin: 0 }}>库位/排仓网页维护</Typography.Title>
          <Typography.Text type="secondary">草稿基线：{draft.base_version_name}。网页修改只保存在服务器草稿，发布前不影响正式数据。</Typography.Text>
        </div>
        <Space wrap style={{ justifyContent: "flex-end" }}>
          <Button aria-label="下载草稿" icon={<DownloadOutlined />} onClick={() => void downloadDraft()}>下载草稿</Button>
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
              if (!await discardDraft()) keepDiscardConfirmOpenRef.current = true;
            }}
          >
            <Button danger disabled={discardDisabled} loading={busyAction === "discard"}>放弃草稿</Button>
          </Popconfirm>
          <Button type="primary" disabled={actionsDisabled} loading={busyAction === "validate"} onClick={() => void openPublish()}>
            发布新版本
          </Button>
        </Space>
      </div>

      <Alert
        className="inline-alert"
        type="success"
        showIcon
        title="草稿已自动保存"
        description={(
          <Space wrap separator={<span aria-hidden="true">·</span>}>
            <span>已保存到服务器</span>
            <span>修订号 {draft.revision}</span>
            <span>最后更新 {formatDate(draft.updated_at)}</span>
            <span>最后编辑人：用户 #{draft.updated_by}</span>
          </Space>
        )}
      />

      {baseVersionChanged && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          title="草稿基线已过期"
          description={`当前正式版本已变为 ${activeVersion.name}。为避免覆盖新版本，请放弃当前草稿后重新开始维护。`}
        />
      )}

      {conflictMessage && (
        <Alert
          className="inline-alert"
          type="error"
          showIcon
          title="草稿已在其他位置更新"
          description={conflictMessage}
          action={<Button aria-label="刷新草稿" icon={<ReloadOutlined />} loading={entryLoading} onClick={() => void loadDraft()}>刷新草稿</Button>}
        />
      )}
      {actionError && <Alert className="inline-alert" type="error" showIcon closable title="操作失败" description={actionError} onClose={() => setActionError(null)} />}
      {importError && <Alert className="inline-alert" type="error" showIcon closable title="Excel 替换未完成" description={importError} onClose={() => setImportError(null)} />}

      <Card style={{ marginBottom: 16 }}>
        <Descriptions
          size="small"
          column={2}
          items={[
            { key: "rows", label: "草稿行数", children: draft.row_count },
            { key: "modified", label: "变更记录", children: draft.modified_count },
            { key: "errors", label: "错误", children: <Tag color={draft.error_count > 0 ? "error" : "default"}>{draft.error_count}</Tag> },
            { key: "warnings", label: "警告", children: <Tag color={draft.warning_count > 0 ? "warning" : "default"}>{draft.warning_count}</Tag> },
            { key: "diff", label: "相对正式版", span: 2, children: <DiffTags diff={diff} /> }
          ]}
        />
      </Card>

      <Card
        title="草稿记录"
        extra={<Button aria-label="新增记录" type="primary" icon={<PlusOutlined />} disabled={actionsDisabled} onClick={openNewRow}>新增记录</Button>}
      >
        <div className="table-toolbar">
          <Input.Search
            aria-label="搜索草稿"
            allowClear
            value={search}
            placeholder="搜索站点、SKU、MSKU 或定位"
            style={{ width: 280 }}
            onChange={(event) => { setPage(1); setSearch(event.target.value); }}
          />
          <Input
            aria-label="站点筛选"
            allowClear
            value={site}
            placeholder="站点精确筛选"
            style={{ width: 180 }}
            onChange={(event) => { setPage(1); setSite(event.target.value); }}
          />
          <Input
            aria-label="规模定位筛选"
            allowClear
            value={scale}
            placeholder="规模定位精确筛选"
            style={{ width: 180 }}
            onChange={(event) => { setPage(1); setScale(event.target.value); }}
          />
          <Select
            aria-label="问题筛选"
            value={issueFilter}
            style={{ width: 130 }}
            options={[{ value: "all", label: "全部问题" }, { value: "errors", label: "仅错误" }]}
            onChange={(value) => { setPage(1); setIssueFilter(value); }}
          />
          <Checkbox checked={onlyModified} onChange={(event) => { setPage(1); setOnlyModified(event.target.checked); }}>
            仅看已修改
          </Checkbox>
          <Popconfirm
            fresh
            open={bulkDeleteConfirmOpen}
            title={`删除选中的 ${selectedRowIds.length} 条记录？`}
            description="删除会立即保存到服务器草稿，发布前不影响正式版本。"
            okText="确认删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            cancelButtonProps={{ disabled: busyAction === "bulk-delete" }}
            disabled={selectedRowIds.length === 0 || actionsDisabled}
            onOpenChange={(open) => {
              if (!open && keepBulkDeleteConfirmOpenRef.current) {
                keepBulkDeleteConfirmOpenRef.current = false;
                return;
              }
              if (!open && busyAction === "bulk-delete") return;
              setBulkDeleteConfirmOpen(open);
            }}
            onConfirm={async () => {
              keepBulkDeleteConfirmOpenRef.current = false;
              if (!await bulkDelete()) keepBulkDeleteConfirmOpenRef.current = true;
            }}
          >
            <Button danger disabled={selectedRowIds.length === 0 || actionsDisabled} loading={busyAction === "bulk-delete"}>
              批量删除（{selectedRowIds.length}）
            </Button>
          </Popconfirm>
        </div>

        {rowsError && (
          <Alert
            className="inline-alert"
            type="error"
            showIcon
            title="无法读取草稿记录"
            description={rowsError}
            action={<Button size="small" onClick={() => setRefreshRowsKey((value) => value + 1)}>重新加载</Button>}
          />
        )}
        <Table<PositionDraftRow>
          rowKey="id"
          size="small"
          loading={rowsLoading}
          columns={rowColumns}
          dataSource={rows}
          rowSelection={{
            selectedRowKeys: selectedRowIds,
            preserveSelectedRowKeys: false,
            getCheckboxProps: () => ({ disabled: actionsDisabled }),
            onChange: (keys) => setSelectedRowIds(keys.map(Number))
          }}
          scroll={{ x: 1400 }}
          locale={{ emptyText: rowsError ? "读取失败" : "草稿中没有符合条件的记录" }}
          pagination={{
            current: page,
            pageSize,
            total: rowsTotal,
            showSizeChanger: true,
            pageSizeOptions: [20, 50, 100],
            showTotal: (total) => `共 ${total} 条`,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPageSize !== pageSize ? 1 : nextPage);
              setPageSize(nextPageSize);
            }
          }}
        />
      </Card>

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
