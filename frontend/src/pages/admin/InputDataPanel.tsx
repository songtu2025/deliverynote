import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
  message
} from "antd";
import {
  CheckCircleFilled,
  DownloadOutlined,
  InboxOutlined,
  ToolOutlined,
  UploadOutlined
} from "@ant-design/icons";
import type { TableProps, UploadFile, UploadProps } from "antd";

import { api, download } from "../../api";
import { formatBeijingDateTime } from "../../dateTime";
import type {
  InputVersion,
  InputVersionInspection,
  InputVersionPreviewValue,
  PositionIssue
} from "../../types";
import { INPUT_KIND_BY_VALUE, INPUT_KIND_DEFINITIONS } from "./adminConstants";
import type { InputKind } from "./adminConstants";

interface InputDataPanelProps {
  versions: InputVersion[];
  loading: boolean;
  onVersionsChanged: () => void | Promise<void>;
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

type PreviewRow = Record<string, InputVersionPreviewValue>;
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

function formatPreviewValue(value: InputVersionPreviewValue): string | number {
  if (typeof value === "boolean") return value ? "是" : "否";
  return value ?? "—";
}

export function InputDataPanel({
  versions,
  loading,
  onVersionsChanged,
  onOpenPositionDraft
}: InputDataPanelProps) {
  const [selectedKind, setSelectedKind] = useState<InputKind>("product");
  const [inspections, setInspections] = useState(
    () => new Map<number, InputVersionInspection>()
  );
  const inspectionRequests = useRef(
    new Map<number, Promise<InputVersionInspection>>()
  );
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
    () => versions
      .filter((version) => version.kind === selectedKind)
      .sort((left, right) => right.created_at.localeCompare(left.created_at)),
    [selectedKind, versions]
  );
  const activeVersion = selectedVersions.find((version) => version.active) ?? null;
  const activeInspection = activeVersion
    ? inspections.get(activeVersion.id) ?? null
    : null;
  const summary = activeInspection?.summary ?? null;
  const preview = activeInspection?.preview ?? null;
  const mutationBusy = mutation !== null;
  const uploading = mutation?.action === "upload";
  const previewTableComponents = useMemo<NonNullable<TableProps<PreviewRow>["components"]>>(
    () => ({
      table: (props) => <table {...props} aria-label={`${selectedDefinition.label}数据预览`} />
    }),
    [selectedDefinition.label]
  );
  const historyTableComponents = useMemo<NonNullable<TableProps<InputVersion>["components"]>>(
    () => ({
      table: (props) => <table {...props} aria-label={`${selectedDefinition.label}版本记录`} />
    }),
    [selectedDefinition.label]
  );

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
      request = api<InputVersionInspection>(
        `/api/input-versions/${versionId}/inspection`
      ).then(
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
    void request.catch((error: unknown) => {
      if (cancelled) return;
      setInspectionError({
        versionId,
        message: error instanceof Error ? error.message : "读取当前版本失败"
      });
    }).finally(() => {
      if (!cancelled) setInspectionLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [activeVersion?.id, inspectionAttempt, loading]);

  const previewColumns = useMemo<NonNullable<TableProps<PreviewRow>["columns"]>>(
    () => [
      {
        title: "Excel 行",
        dataIndex: "__excelRow",
        key: "__excelRow",
        width: 84,
        fixed: "left",
        render: (value: InputVersionPreviewValue) => formatPreviewValue(value)
      },
      ...(preview?.columns ?? []).map((column) => ({
        title: column,
        dataIndex: column,
        key: column,
        ellipsis: true,
        width: Math.max(140, Math.min(240, column.length * 18 + 48)),
        render: (value: InputVersionPreviewValue) => formatPreviewValue(value)
      }))
    ],
    [preview]
  );

  const previewRows = useMemo(
    () => (preview?.rows ?? []).map((row, index) => ({
      ...row,
      __excelRow: (preview?.offset ?? 0) + index + 2,
      __previewKey: String((preview?.offset ?? 0) + index)
    })),
    [preview]
  );

  const selectUploadFile: NonNullable<UploadProps["onChange"]> = ({ fileList }) => {
    setPendingFiles(fileList.slice(-1));
    setUploadError(null);
  };

  const uploadVersion = async () => {
    if (mutationBusy) return;
    const kind = selectedKind;
    setUploadError(null);
    try {
      const values = await uploadForm.validateFields();
      const file = pendingFiles[0]?.originFileObj;
      if (!file) {
        setUploadError({ kind, message: "请选择要上传的 Excel 文件" });
        return;
      }
      setMutation({ kind, action: "upload" });
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
      await onVersionsChanged();
      setMaintenanceOpen(false);
      message.success(`${INPUT_KIND_BY_VALUE[kind].label}已上传并启用，将用于新批次`);
    } catch (error) {
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
        await onVersionsChanged();
        message.success(`${version.name} 已启用，将用于新批次`);
      } catch (error) {
        setActionError({
          kind,
          message: error instanceof Error ? error.message : "启用失败"
        });
      } finally {
        setMutation(null);
      }
    })();
  };

  const inspectionReady = Boolean(activeVersion && activeInspection);
  const errors = summary ? issueCount(summary.issues, "error") : 0;
  const warnings = summary ? issueCount(summary.issues, "warning") : 0;
  const readyKindCount = MAINTAINABLE_INPUT_KIND_DEFINITIONS.filter((definition) =>
    versions.some((version) => version.kind === definition.value && version.active)
  ).length;
  const renderCurrentData = () => {
    if (loading) {
      return <div className="input-data-loading"><Spin description="读取资料状态" /></div>;
    }
    if (!activeVersion) {
      return (
        <Alert
          type="warning"
          showIcon
          title={`${selectedDefinition.label}尚无启用版本`}
          description="上传并启用通过校验的 Excel 文件。"
        />
      );
    }
    if (inspectionLoading || (!inspectionReady && !inspectionError)) {
      return <div className="input-data-loading"><Spin description="读取摘要与预览" /></div>;
    }
    if (inspectionError?.versionId === activeVersion.id) {
      return (
        <Alert
          type="error"
          showIcon
          title="无法读取当前版本内容"
          description={inspectionError.message}
          action={<Button size="small" onClick={() => setInspectionAttempt((value) => value + 1)}>重新加载</Button>}
        />
      );
    }
    if (!inspectionReady || !summary || !preview) return null;

    const metricItems = selectedKind === "position"
      ? [
          `${summary.metrics.sites ?? 0} 个站点`,
          `${summary.metrics.skus ?? 0} 个积加 SKU`,
          `${summary.metrics.mskus ?? 0} 个 MSKU`
        ]
      : [];

    return (
      <>
        <div className="input-data-preview-heading">
          <div>
            <Typography.Title level={5}>数据预览</Typography.Title>
            <Typography.Text type="secondary">预览不会修改原文件。</Typography.Text>
          </div>
          <Typography.Text className="input-data-preview-summary" type="secondary">
            <span>当前展示前 {preview.rows.length} 行，共 {preview.total} 行 · {summary.columns.length} 个字段</span>
            {metricItems.map((item) => (
              <span className="input-data-preview-metric" key={item}>{item}</span>
            ))}
          </Typography.Text>
        </div>
        <Table<PreviewRow>
          className="input-data-preview-table"
          rowKey="__previewKey"
          size="small"
          columns={previewColumns}
          dataSource={previewRows}
          components={previewTableComponents}
          pagination={false}
          scroll={{ x: "max-content" }}
          locale={{ emptyText: "当前版本没有可预览的数据" }}
        />
      </>
    );
  };

  const renderQuality = () => {
    if (!activeVersion) {
      return <Typography.Text type="secondary">启用资料后显示检查结果。</Typography.Text>;
    }
    if (!inspectionReady || !summary) {
      return <Typography.Text type="secondary">等待检查结果。</Typography.Text>;
    }
    if (selectedKind !== "position") {
      return <Alert type="info" showIcon title="文件结构已通过校验，当前未执行内容质量诊断" />;
    }
    if (summary.issues.length === 0) {
      return <Alert type="success" showIcon title="未发现资料质量问题" />;
    }
    return (
      <Space orientation="vertical" size={8} className="input-data-quality-list">
        <Space wrap size={[6, 6]}>
          <Tag color={errors > 0 ? "error" : "default"}>{errors} 个错误</Tag>
          <Tag color={warnings > 0 ? "warning" : "default"}>{warnings} 个警告</Tag>
        </Space>
        {summary.issues.map((issue) => (
          <Alert
            key={`${issue.code}-${issue.row_numbers.join("-")}`}
            type={issue.severity}
            showIcon
            title={issue.message}
            description={issue.row_numbers.length > 0 ? `涉及 Excel 行：${issue.row_numbers.join("、")}` : undefined}
          />
        ))}
      </Space>
    );
  };

  const renderHistory = () => (
    <section aria-label="版本记录" className="input-data-tab-panel">
      <div className="input-data-tab-heading">
        <div>
          <Typography.Title level={5}>版本记录</Typography.Title>
          <Typography.Text type="secondary">查看历次上传，并决定以后新建批次使用的版本。</Typography.Text>
        </div>
        <Typography.Text type="secondary">共 {selectedVersions.length} 个版本</Typography.Text>
      </div>
      <Table<InputVersion>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={selectedVersions}
        components={historyTableComponents}
        pagination={selectedVersions.length > 8 ? { pageSize: 8, showSizeChanger: false } : false}
        scroll={{ x: 720 }}
        rowClassName={(version) => version.active ? "input-data-active-version-row" : ""}
        locale={{ emptyText: `暂无${selectedDefinition.label}版本` }}
        columns={[
          {
            title: "资料版本",
            key: "version",
            width: 300,
            render: (_, version) => (
              <div className="input-data-version-cell">
                <strong>{version.name}</strong>
                <Typography.Text type="secondary" ellipsis={{ tooltip: version.original_name }}>
                  {version.original_name}
                </Typography.Text>
              </div>
            )
          },
          {
            title: "上传信息",
            key: "created",
            width: 230,
            render: (_, version) => (
              <div className="input-data-version-cell">
                <span>{formatBeijingDateTime(version.created_at)}</span>
                <Typography.Text type="secondary">用户 #{version.created_by}</Typography.Text>
              </div>
            )
          },
          {
            title: "状态",
            dataIndex: "active",
            width: 120,
            render: (active: boolean) => active ? <Tag color="success">当前启用</Tag> : <Tag>历史版本</Tag>
          },
          {
            title: "操作",
            width: 100,
            render: (_, version) => version.active || (selectedKind === "position" && activeVersion) ? null : (
              <Popconfirm
                title={`启用 ${version.name}？`}
                description="仅用于新批次；已有批次不变。"
                okText="确认启用"
                cancelText="取消"
                onConfirm={() => activateVersion(version)}
              >
                <Button
                  type="link"
                  aria-busy={mutation?.action === "activate" && mutation.versionId === version.id}
                  disabled={mutationBusy}
                  loading={mutation?.action === "activate" && mutation.versionId === version.id}
                >
                  启用
                </Button>
              </Popconfirm>
            )
          }
        ]}
      />
    </section>
  );

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
            const current = versions.find((version) =>
              version.kind === definition.value && version.active
            );
            const selected = definition.value === selectedKind;
            return (
              <Button
                key={definition.value}
                className={`input-data-kind-button${selected ? " is-selected" : ""}`}
                aria-label={current
                  ? `${definition.label}，已就绪，当前版本 ${current.name}`
                  : `${definition.label}，未启用，等待上传`}
                aria-pressed={selected}
                disabled={mutationBusy}
                onClick={() => setSelectedKind(definition.value)}
              >
                <span>{definition.label}</span>
                {current
                  ? <CheckCircleFilled aria-label="已就绪" />
                  : <span className="input-data-kind-pending">未启用</span>}
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
                    <Typography.Text
                      type="secondary"
                      ellipsis={{ tooltip: activeVersion.original_name }}
                    >
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
                  {selectedDefinition.requiredFields.map((field) => <Tag key={field}>{field}</Tag>)}
                </Space>
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
                  <span>数据预览 <span className="input-data-tab-count">{preview?.total ?? 0}</span></span>
                ),
                children: (
                  <section aria-label="数据预览" className="input-data-tab-panel">
                    {renderCurrentData()}
                  </section>
                )
              },
              {
                key: "history",
                label: (
                  <span>版本记录 <span className="input-data-tab-count">{selectedVersions.length}</span></span>
                ),
                children: renderHistory()
              },
              {
                key: "quality",
                label: (
                  <span>质量检查 <span className="input-data-tab-count">{errors + warnings}</span></span>
                ),
                children: (
                  <section aria-label="质量检查" className="input-data-tab-panel input-data-quality-panel">
                    <div className="input-data-tab-heading">
                      <div>
                        <Typography.Title level={5}>质量检查</Typography.Title>
                      </div>
                    </div>
                    {renderQuality()}
                  </section>
                )
              }
            ]}
          />
        </section>
      </main>

      <Drawer
        rootClassName="input-data-maintenance-drawer"
        title={activeVersion ? `更新${selectedDefinition.label}` : `上传${selectedDefinition.label}`}
        size={520}
        open={maintenanceOpen}
        getContainer={false}
        destroyOnHidden
        motion={import.meta.env.MODE === "test" ? {
          motionAppear: false,
          motionEnter: false,
          motionLeave: false
        } : undefined}
        maskMotion={import.meta.env.MODE === "test" ? {
          motionAppear: false,
          motionEnter: false,
          motionLeave: false
        } : undefined}
        closable={!mutationBusy}
        maskClosable={!mutationBusy}
        keyboard={!mutationBusy}
        onClose={() => {
          if (!mutationBusy) setMaintenanceOpen(false);
        }}
      >
        <div className="input-data-maintenance-form">
          <Typography.Title level={5}>
            {activeVersion ? "上传替换当前版本" : "上传首个版本"}
          </Typography.Title>
          <Typography.Paragraph type="secondary">
            选择文件并确认版本名称；校验通过后立即启用。
          </Typography.Paragraph>
          {uploadError?.kind === selectedKind && (
            <Alert className="inline-alert" type="error" showIcon title="上传失败" description={uploadError.message} />
          )}
          <Form form={uploadForm} layout="vertical" clearOnDestroy>
            <Form.Item
              label="新版本名称"
              name="name"
              rules={[{ required: true, message: "请输入版本名称" }]}
            >
              <Input disabled={mutationBusy} placeholder={`例如：${selectedKind}-20260721`} />
            </Form.Item>
            <Upload.Dragger
              className="input-data-uploader"
              disabled={mutationBusy}
              accept=".xls,.xlsx"
              maxCount={1}
              multiple={false}
              beforeUpload={() => false}
              fileList={pendingFiles}
              onChange={selectUploadFile}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">拖放 Excel 到这里，或点击选择</p>
              <p className="ant-upload-hint">支持 .xls、.xlsx；选择后不会立即生效</p>
            </Upload.Dragger>
            <Button
              className="input-data-upload-submit"
              block
              type="primary"
              icon={<UploadOutlined />}
              aria-label="校验并启用新版本"
              aria-busy={uploading}
              disabled={mutationBusy}
              loading={uploading}
              onClick={() => void uploadVersion()}
            >
              校验并启用新版本
            </Button>
          </Form>
          <Typography.Paragraph className="input-data-upload-impact" type="secondary">
            仅用于新批次；已有批次不变。
          </Typography.Paragraph>
        </div>
      </Drawer>
    </div>
  );
}
