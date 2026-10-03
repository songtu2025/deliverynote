import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Space, Tabs, Tag, Typography } from "antd";
import { DownloadOutlined, ToolOutlined, UploadOutlined } from "@ant-design/icons";

import { formatBeijingDateTime } from "../../dateTime";
import type { InputVersion } from "../../types";
import { INPUT_KIND_BY_VALUE } from "./adminConstants";
import type { InputKind } from "./adminConstants";
import { InputDataKindSwitcher } from "./InputDataKindSwitcher";
import { InputVersionHistoryPanel } from "./InputVersionHistoryPanel";
import { InputVersionPreviewPanel } from "./InputVersionPreviewPanel";
import { InputVersionQualityPanel } from "./InputVersionQualityPanel";
import { InputVersionUploadDrawer } from "./InputVersionUploadDrawer";
import { useInputVersionActions } from "./useInputVersionActions";
import { useInputVersionInspection } from "./useInputVersionInspection";

interface InputDataPanelProps {
  versions: InputVersion[];
  loading: boolean;
  onVersionsChanged: () => void | boolean | Promise<void | boolean>;
  onOpenPositionDraft: () => void;
}

type WorkspaceTab = "preview" | "history" | "quality";

export function InputDataPanel({ versions, loading, onVersionsChanged, onOpenPositionDraft }: InputDataPanelProps) {
  const [selectedKind, setSelectedKind] = useState<InputKind>("product");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("preview");
  const [contextOpen, setContextOpen] = useState(false);
  const {
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
  } = useInputVersionActions(selectedKind, onVersionsChanged);

  const selectedDefinition = INPUT_KIND_BY_VALUE[selectedKind];
  const selectedVersions = useMemo(
    () =>
      versions
        .filter((version) => version.kind === selectedKind)
        .sort((left, right) => right.created_at.localeCompare(left.created_at)),
    [selectedKind, versions]
  );
  const activeVersion = selectedVersions.find((version) => version.active) ?? null;
  const {
    inspection: activeInspection,
    inspectionLoading,
    inspectionError,
    retryInspection,
    errors,
    warnings
  } = useInputVersionInspection(activeVersion?.id, loading);
  const summary = activeInspection?.summary ?? null;
  const preview = activeInspection?.preview ?? null;

  useEffect(() => {
    setWorkspaceTab("preview");
    setContextOpen(false);
  }, [selectedKind]);

  return (
    <div className="input-data-panel">
      <InputDataKindSwitcher
        versions={versions}
        selectedKind={selectedKind}
        busy={mutationBusy}
        onChange={setSelectedKind}
      />

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
              onClick={() => void downloadCurrent(activeVersion)}
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
                      onRetry={retryInspection}
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
