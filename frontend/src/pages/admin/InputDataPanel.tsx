import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, App as AntApp, Button, Form, Space, Tabs, Tag, Typography } from "antd";
import { CheckCircleFilled, DownloadOutlined, ToolOutlined, UploadOutlined } from "@ant-design/icons";
import type { UploadFile, UploadProps } from "antd";

import { api, ApiError, download } from "../../api";
import { formatBeijingDateTime } from "../../dateTime";
import type { InputVersion, InputVersionInspection, PositionIssue } from "../../types";
import { INPUT_KIND_BY_VALUE, INPUT_KIND_DEFINITIONS, inputUploadFormatMessage } from "./adminConstants";
import type { InputKind } from "./adminConstants";
import { InputVersionHistoryPanel } from "./InputVersionHistoryPanel";
import { InputVersionPreviewPanel } from "./InputVersionPreviewPanel";
import { InputVersionQualityPanel } from "./InputVersionQualityPanel";
import { InputVersionUploadDrawer } from "./InputVersionUploadDrawer";

interface InputDataPanelProps {
  versions: InputVersion[];
  loading: boolean;
  onVersionsChanged: () => void | boolean | Promise<void | boolean>;
  onOpenPositionDraft: () => void;
}

interface MutationState {
  kind: InputKind;
  action: "upload" | "activate";
  versionId?: number;
}

interface KindError {
  kind: InputKind;
  message: string;
}

type WorkspaceTab = "preview" | "history" | "quality";

const MAINTAINABLE_INPUT_KIND_DEFINITIONS = INPUT_KIND_DEFINITIONS.filter(
  (definition) => definition.value !== "purchase"
);

function issueCount(issues: PositionIssue[], severity: PositionIssue["severity"]): number {
  return issues.reduce(
    (total, issue) => total + (issue.severity === severity ? Math.max(1, issue.row_numbers.length) : 0),
    0
  );
}

export function InputDataPanel({ versions, loading, onVersionsChanged, onOpenPositionDraft }: InputDataPanelProps) {
  const { message } = AntApp.useApp();
  const [selectedKind, setSelectedKind] = useState<InputKind>("product");
  const [inspections, setInspections] = useState(() => new Map<number, InputVersionInspection>());
  const inspectionRequests = useRef(new Map<number, Promise<InputVersionInspection>>());
  const [inspectionLoading, setInspectionLoading] = useState(false);
  const [inspectionError, setInspectionError] = useState<{ versionId: number; message: string } | null>(null);
  const [inspectionAttempt, setInspectionAttempt] = useState(0);
  const [uploadError, setUploadError] = useState<KindError | null>(null);
  const [actionError, setActionError] = useState<KindError | null>(null);
  const [mutation, setMutation] = useState<MutationState | null>(null);
  const [pendingFiles, setPendingFiles] = useState<UploadFile[]>([]);
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("preview");
  const [contextOpen, setContextOpen] = useState(false);
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);
  const [uploadForm] = Form.useForm<{ name: string }>();

  const selectedDefinition = INPUT_KIND_BY_VALUE[selectedKind];
  const selectedVersions = useMemo(
    () =>
      versions
        .filter((version) => version.kind === selectedKind)
        .sort((left, right) => right.created_at.localeCompare(left.created_at)),
    [selectedKind, versions]
  );
  const activeVersion = selectedVersions.find((version) => version.active) ?? null;
  const activeInspection = activeVersion ? (inspections.get(activeVersion.id) ?? null) : null;
  const summary = activeInspection?.summary ?? null;
  const preview = activeInspection?.preview ?? null;
  const mutationBusy = mutation !== null;
  const uploading = mutation?.action === "upload";

  useEffect(() => {
    setPendingFiles([]);
    setWorkspaceTab("preview");
    setContextOpen(false);
    setMaintenanceOpen(false);
  }, [selectedKind, uploadForm]);

  useEffect(() => {
    setInspectionError(null);
    if (loading || !activeVersion) {
      setInspectionLoading(false);
      return undefined;
    }

    let cancelled = false;
    const versionId = activeVersion.id;
    if (inspections.has(versionId)) {
      setInspectionLoading(false);
      return undefined;
    }

    let request = inspectionRequests.current.get(versionId);
    if (!request) {
      request = api<InputVersionInspection>(`/api/input-versions/${versionId}/inspection`).then(
        (inspection) => {
          setInspections((current) => {
            const next = new Map(current);
            next.set(versionId, inspection);
            return next;
          });
          inspectionRequests.current.delete(versionId);
          return inspection;
        },
        (error: unknown) => {
          inspectionRequests.current.delete(versionId);
          throw error;
        }
      );
      inspectionRequests.current.set(versionId, request);
    }

    setInspectionLoading(true);
    void request
      .catch((error: unknown) => {
        if (cancelled || (error instanceof ApiError && error.status === 401)) return;
        setInspectionError({
          versionId,
          message: error instanceof Error ? error.message : "读取当前版本失败"
        });
      })
      .finally(() => {
        if (!cancelled) setInspectionLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeVersion?.id, inspectionAttempt, loading]);

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
    setMutation({ kind, action: "upload" });
    try {
      const formData = new FormData();
      formData.append("name", values.name);
      formData.append("activate", "true");
      formData.append("file", file);
      await api<InputVersion>(`/api/input-versions/${kind}`, {
        method: "POST",
        body: formData
      });
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

  const downloadCurrent = async () => {
    if (!activeVersion) return;
    setActionError(null);
    try {
      await download(`/api/input-versions/${activeVersion.id}/download`, activeVersion.original_name);
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
    setMutation({ kind, action: "activate", versionId: version.id });
    void (async () => {
      try {
        await api<InputVersion>(`/api/input-versions/${version.id}/activate`, { method: "POST" });
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

  const errors = summary ? issueCount(summary.issues, "error") : 0;
  const warnings = summary ? issueCount(summary.issues, "warning") : 0;
  const readyKindCount = MAINTAINABLE_INPUT_KIND_DEFINITIONS.filter((definition) =>
    versions.some((version) => version.kind === definition.value && version.active)
  ).length;

  return (
    <div className="input-data-panel">
      <section className="input-data-kind-switcher" aria-label="基础资料类型">
        <div className="input-data-kind-switcher-heading">
          <Typography.Text strong>资料类型</Typography.Text>
          <Typography.Text type="secondary">
            {readyKindCount}/{MAINTAINABLE_INPUT_KIND_DEFINITIONS.length} 已启用
          </Typography.Text>
        </div>
        <div className="input-data-kind-list">
          {MAINTAINABLE_INPUT_KIND_DEFINITIONS.map((definition) => {
            const current = versions.find((version) => version.kind === definition.value && version.active);
            const selected = definition.value === selectedKind;
            return (
              <Button
                key={definition.value}
                className={`input-data-kind-button${selected ? " is-selected" : ""}`}
                aria-label={
                  current
                    ? `${definition.label}，已就绪，当前版本 ${current.name}`
                    : `${definition.label}，未启用，等待上传`
                }
                aria-pressed={selected}
                disabled={mutationBusy}
                onClick={() => setSelectedKind(definition.value)}
              >
                <span>{definition.label}</span>
                {current ? (
                  <CheckCircleFilled aria-label="已就绪" />
                ) : (
                  <span className="input-data-kind-pending">未启用</span>
                )}
              </Button>
            );
          })}
        </div>
      </section>

      <main className="input-data-detail">
        <section
          className={`input-data-status-header${activeVersion ? " is-ready" : ""}`}
          aria-label={`${selectedDefinition.label}资料状态`}
        >
          <div className="input-data-status-copy">
            <div className="input-data-status-title">
              <Typography.Title level={3}>{selectedDefinition.label}</Typography.Title>
              {activeVersion ? <Tag color="success">已启用</Tag> : <Tag color="warning">未启用</Tag>}
            </div>
            <Typography.Paragraph>{selectedDefinition.purpose}</Typography.Paragraph>
            <div className="input-data-status-meta">
              {activeVersion ? (
                <>
                  <span className="input-data-status-version">
                    <strong>版本 {activeVersion.name}</strong>
                    <Typography.Text type="secondary" ellipsis={{ tooltip: activeVersion.original_name }}>
                      {activeVersion.original_name}
                    </Typography.Text>
                  </span>
                  <Typography.Text className="input-data-status-time" type="secondary">
                    更新于 {formatBeijingDateTime(activeVersion.created_at)}
                  </Typography.Text>
                </>
              ) : (
                <Typography.Text type="secondary">尚未上传正式文件。</Typography.Text>
              )}
            </div>
          </div>

          <div className="input-data-status-actions">
            {selectedKind === "position" && activeVersion ? (
              <Button
                type="primary"
                aria-label="开始网页维护"
                icon={<ToolOutlined />}
                disabled={mutationBusy}
                onClick={onOpenPositionDraft}
              >
                开始网页维护
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<UploadOutlined />}
                aria-label={activeVersion ? "更新资料" : "上传首个版本"}
                disabled={mutationBusy}
                onClick={() => setMaintenanceOpen(true)}
              >
                {activeVersion ? "更新资料" : "上传首个版本"}
              </Button>
            )}
            <Button
              aria-label="下载当前文件"
              icon={<DownloadOutlined />}
              disabled={!activeVersion}
              onClick={() => void downloadCurrent()}
            >
              下载当前文件
            </Button>
          </div>
        </section>

        {actionError?.kind === selectedKind && (
          <Alert type="error" showIcon closable title="操作失败" description={actionError.message} />
        )}

        <section className={`input-data-context${contextOpen ? " is-open" : ""}`} aria-label="字段说明">
          <div className="input-data-context-summary">
            <div>
              <Typography.Text strong>字段说明</Typography.Text>
            </div>
            <Button type="text" size="small" onClick={() => setContextOpen((value) => !value)}>
              {contextOpen ? "收起字段说明" : "查看字段说明"}
            </Button>
          </div>
          {contextOpen && (
            <div className="input-data-context-grid">
              <div className="input-data-required-fields">
                <Typography.Text type="secondary">必填字段</Typography.Text>
                <Space wrap size={[6, 6]}>
                  {selectedDefinition.requiredFields.map((field) => (
                    <Tag key={field}>{field}</Tag>
                  ))}
                </Space>
                {selectedDefinition.optionalFields && (
                  <>
                    <Typography.Text type="secondary">可选字段</Typography.Text>
                    <Space wrap size={[6, 6]}>
                      {selectedDefinition.optionalFields.map((field) => (
                        <Tag key={field}>{field}</Tag>
                      ))}
                    </Space>
                  </>
                )}
              </div>
              <div className="input-data-impact">
                <span>对业务的影响</span>
                <p>{selectedDefinition.impact}</p>
              </div>
            </div>
          )}
        </section>

        <section className="input-data-workspace" aria-label={`${selectedDefinition.label}资料工作区`}>
          <Tabs
            className="input-data-workspace-tabs"
            activeKey={workspaceTab}
            onChange={(key) => setWorkspaceTab(key as WorkspaceTab)}
            items={[
              {
                key: "preview",
                label: (
                  <span>
                    数据预览 <span className="input-data-tab-count">{preview?.total ?? 0}</span>
                  </span>
                ),
                children: (
                  <section aria-label="数据预览" className="input-data-tab-panel">
                    <InputVersionPreviewPanel
                      kind={selectedKind}
                      label={selectedDefinition.label}
                      activeVersion={activeVersion}
                      inspection={activeInspection}
                      loading={loading}
                      inspectionLoading={inspectionLoading}
                      inspectionError={inspectionError}
                      onRetry={() => setInspectionAttempt((value) => value + 1)}
                    />
                  </section>
                )
              },
              {
                key: "history",
                label: (
                  <span>
                    版本记录 <span className="input-data-tab-count">{selectedVersions.length}</span>
                  </span>
                ),
                children: (
                  <InputVersionHistoryPanel
                    label={selectedDefinition.label}
                    versions={selectedVersions}
                    loading={loading}
                    activationAllowed={selectedKind !== "position" || !activeVersion}
                    mutationBusy={mutationBusy}
                    activatingVersionId={mutation?.action === "activate" ? (mutation.versionId ?? null) : null}
                    onActivate={activateVersion}
                  />
                )
              },
              {
                key: "quality",
                label: (
                  <span>
                    质量检查 <span className="input-data-tab-count">{errors + warnings}</span>
                  </span>
                ),
                children: (
                  <section aria-label="质量检查" className="input-data-tab-panel input-data-quality-panel">
                    <div className="input-data-tab-heading">
                      <div>
                        <Typography.Title level={5}>质量检查</Typography.Title>
                      </div>
                    </div>
                    <InputVersionQualityPanel
                      kind={selectedKind}
                      hasActiveVersion={Boolean(activeVersion)}
                      summary={summary}
                      errors={errors}
                      warnings={warnings}
                    />
                  </section>
                )
              }
            ]}
          />
        </section>
      </main>

      <InputVersionUploadDrawer
        kind={selectedKind}
        hasActiveVersion={activeVersion !== null}
        open={maintenanceOpen}
        busy={mutationBusy}
        uploading={uploading}
        form={uploadForm}
        files={pendingFiles}
        error={uploadError?.kind === selectedKind ? uploadError.message : null}
        onFileChange={selectUploadFile}
        onSubmit={uploadVersion}
        onClose={() => setMaintenanceOpen(false)}
      />
    </div>
  );
}
