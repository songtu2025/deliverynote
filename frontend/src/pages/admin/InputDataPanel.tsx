import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Popconfirm,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
  message
} from "antd";
import {
  CheckCircleFilled,
  DatabaseOutlined,
  DownloadOutlined,
  InboxOutlined,
  ToolOutlined,
  UploadOutlined
} from "@ant-design/icons";
import type { TableProps, UploadFile, UploadProps } from "antd";

import { api, download } from "../../api";
import type {
  InputVersion,
  InputVersionPreview,
  InputVersionPreviewValue,
  InputVersionSummary,
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

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN");
}

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
  const [selectedKind, setSelectedKind] = useState<InputKind>("purchase");
  const [summary, setSummary] = useState<InputVersionSummary | null>(null);
  const [preview, setPreview] = useState<InputVersionPreview | null>(null);
  const [inspectionVersionId, setInspectionVersionId] = useState<number | null>(null);
  const [inspectionLoading, setInspectionLoading] = useState(false);
  const [inspectionError, setInspectionError] = useState<{ versionId: number; message: string } | null>(null);
  const [inspectionAttempt, setInspectionAttempt] = useState(0);
  const [uploadError, setUploadError] = useState<KindError | null>(null);
  const [actionError, setActionError] = useState<KindError | null>(null);
  const [mutation, setMutation] = useState<MutationState | null>(null);
  const [pendingFiles, setPendingFiles] = useState<UploadFile[]>([]);
  const [uploadForm] = Form.useForm<{ name: string }>();

  const selectedDefinition = INPUT_KIND_BY_VALUE[selectedKind];
  const selectedVersions = useMemo(
    () => versions
      .filter((version) => version.kind === selectedKind)
      .sort((left, right) => right.created_at.localeCompare(left.created_at)),
    [selectedKind, versions]
  );
  const activeVersion = selectedVersions.find((version) => version.active) ?? null;
  const mutationBusy = mutation !== null;
  const uploading = mutation?.action === "upload";

  useEffect(() => {
    uploadForm.resetFields();
    setPendingFiles([]);
  }, [selectedKind, uploadForm]);

  useEffect(() => {
    setSummary(null);
    setPreview(null);
    setInspectionVersionId(null);
    setInspectionError(null);
    if (loading || !activeVersion) {
      setInspectionLoading(false);
      return undefined;
    }

    let cancelled = false;
    const versionId = activeVersion.id;
    setInspectionLoading(true);
    void Promise.all([
      api<InputVersionSummary>(`/api/input-versions/${versionId}/summary`),
      api<InputVersionPreview>(`/api/input-versions/${versionId}/preview`)
    ]).then(([nextSummary, nextPreview]) => {
      if (cancelled) return;
      setSummary(nextSummary);
      setPreview(nextPreview);
      setInspectionVersionId(versionId);
    }).catch((error: unknown) => {
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
    () => (preview?.columns ?? []).map((column) => ({
      title: column,
      dataIndex: column,
      key: column,
      ellipsis: true,
      width: Math.max(140, Math.min(240, column.length * 18 + 48)),
      render: (value: InputVersionPreviewValue) => formatPreviewValue(value)
    })),
    [preview]
  );

  const previewRows = useMemo(
    () => (preview?.rows ?? []).map((row, index) => ({
      ...row,
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
      message.success(`${INPUT_KIND_BY_VALUE[kind].label}已上传并启用，仅影响以后创建的批次`);
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

  const activateVersion = async (version: InputVersion) => {
    if (mutationBusy) return;
    const kind = selectedKind;
    setActionError(null);
    setMutation({ kind, action: "activate", versionId: version.id });
    try {
      await api<InputVersion>(`/api/input-versions/${version.id}/activate`, { method: "POST" });
      await onVersionsChanged();
      message.success(`${version.name} 已启用，仅影响以后创建的批次`);
    } catch (error) {
      setActionError({
        kind,
        message: error instanceof Error ? error.message : "启用失败"
      });
    } finally {
      setMutation(null);
    }
  };

  const inspectionReady = Boolean(
    activeVersion
    && inspectionVersionId === activeVersion.id
    && summary
    && preview
  );
  const errors = summary ? issueCount(summary.issues, "error") : 0;
  const warnings = summary ? issueCount(summary.issues, "warning") : 0;
  const readyKindCount = INPUT_KIND_DEFINITIONS.filter((definition) =>
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
          description="请在维护操作中上传并启用一个通过校验的 Excel 版本。"
        />
      );
    }
    if (inspectionLoading || (inspectionVersionId !== activeVersion.id && !inspectionError)) {
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
          `${summary.row_count} 行`,
          `${summary.metrics.sites ?? 0} 个站点`,
          `${summary.metrics.skus ?? 0} 个积加 SKU`,
          `${summary.metrics.mskus ?? 0} 个 MSKU`
        ]
      : [`${summary.row_count} 行`, `${summary.columns.length} 个字段`];

    return (
      <>
        <div className="input-data-metric-grid">
          {metricItems.map((item) => (
            <div className="input-data-metric" key={item}>
              <strong>{item}</strong>
              <span>当前版本</span>
            </div>
          ))}
        </div>
        <div className="input-data-preview-heading">
          <div>
            <Typography.Title level={5}>数据预览</Typography.Title>
            <Typography.Text type="secondary">用于快速确认字段和内容，不会修改原始文件。</Typography.Text>
          </div>
          <Typography.Text type="secondary">
            当前展示前 {preview.rows.length} 行，共 {preview.total} 行。
          </Typography.Text>
        </div>
        <Table<PreviewRow>
          className="input-data-preview-table"
          rowKey="__previewKey"
          size="small"
          columns={previewColumns}
          dataSource={previewRows}
          pagination={false}
          scroll={{ x: "max-content" }}
          locale={{ emptyText: "当前版本没有可预览的数据" }}
        />
      </>
    );
  };

  const renderQuality = () => {
    if (!activeVersion) {
      return <Typography.Text type="secondary">启用资料后，这里会显示结构校验与质量提示。</Typography.Text>;
    }
    if (!inspectionReady || !summary) {
      return <Typography.Text type="secondary">正在等待当前版本的检查结果。</Typography.Text>;
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

  return (
    <div className="input-data-panel">
      <Card
        className="input-data-catalog"
        title={(
          <div className="input-data-catalog-title">
            <Space><DatabaseOutlined />基础资料</Space>
            <Typography.Text type="secondary">{readyKindCount}/{INPUT_KIND_DEFINITIONS.length} 已启用</Typography.Text>
          </div>
        )}
      >
        <div className="input-data-kind-list">
          {INPUT_KIND_DEFINITIONS.map((definition) => {
            const current = versions.find((version) => version.kind === definition.value && version.active);
            const selected = definition.value === selectedKind;
            return (
              <Button
                key={definition.value}
                className={`input-data-kind-button${selected ? " is-selected" : ""}`}
                aria-label={current
                  ? `${definition.label}，已就绪，当前版本 ${current.name}`
                  : `${definition.label}，未启用，等待上传`}
                aria-pressed={selected}
                block
                disabled={mutationBusy}
                onClick={() => setSelectedKind(definition.value)}
              >
                <span className="input-data-kind-content">
                  <span className="input-data-kind-heading">
                    <strong>{definition.label}</strong>
                    {current ? <CheckCircleFilled aria-label="已就绪" /> : <Tag color="warning">未启用</Tag>}
                  </span>
                  <span className="input-data-kind-version">{current?.name ?? "等待上传"}</span>
                  <small>{current ? formatDate(current.created_at) : "尚无启用版本"}</small>
                </span>
              </Button>
            );
          })}
        </div>
      </Card>

      <main className="input-data-detail">
        <Card className="input-data-overview-card">
          <div className="input-data-overview-grid">
            <div className="input-data-overview-copy">
              <Typography.Text className="input-data-eyebrow">资料用途</Typography.Text>
              <Typography.Title level={3}>{selectedDefinition.label}</Typography.Title>
              <Typography.Paragraph>{selectedDefinition.purpose}</Typography.Paragraph>
              <div className="input-data-impact">
                <span>对业务的影响</span>
                <p>{selectedDefinition.impact}</p>
              </div>
              <div className="input-data-required-fields">
                <Typography.Text type="secondary">必填字段</Typography.Text>
                <Space wrap size={[6, 6]}>
                  {selectedDefinition.requiredFields.map((field) => <Tag key={field}>{field}</Tag>)}
                </Space>
              </div>
            </div>

            <div className={`input-data-current-version${activeVersion ? " is-ready" : ""}`}>
              <div className="input-data-current-heading">
                <span>当前生效版本</span>
                {activeVersion ? <Tag color="success">已启用</Tag> : <Tag color="warning">未启用</Tag>}
              </div>
              {activeVersion ? (
                <>
                  <strong className="input-data-current-name">{activeVersion.name}</strong>
                  <Typography.Text className="input-data-current-file" title={activeVersion.original_name}>
                    {activeVersion.original_name}
                  </Typography.Text>
                  <dl className="input-data-current-meta">
                    <div><dt>上传时间</dt><dd>{formatDate(activeVersion.created_at)}</dd></div>
                    <div><dt>创建人</dt><dd>用户 #{activeVersion.created_by}</dd></div>
                  </dl>
                  <Button
                    block
                    aria-label="下载当前文件"
                    icon={<DownloadOutlined />}
                    onClick={() => void downloadCurrent()}
                  >
                    下载当前文件
                  </Button>
                </>
              ) : (
                <>
                  <strong className="input-data-current-name">等待上传首个版本</strong>
                  <Typography.Text type="secondary">新建批次前请先完成资料启用。</Typography.Text>
                </>
              )}
            </div>
          </div>
          {actionError?.kind === selectedKind && (
            <Alert className="input-data-overview-error" type="error" showIcon closable title="操作失败" description={actionError.message} />
          )}
        </Card>

        <div className="input-data-content-grid">
          <section aria-label="当前数据" className="input-data-main-column">
            <Card title="当前数据" className="input-data-section-card">
              {renderCurrentData()}
            </Card>
          </section>

          <aside className="input-data-side-column">
            <section aria-label="维护操作">
              <Card title="维护操作" className="input-data-section-card input-data-maintenance-card">
                {selectedKind === "position" && activeVersion ? (
                  <div className="input-data-draft-entry">
                    <Tag color="processing">推荐流程</Tag>
                    <Typography.Title level={5}>库位资料已有正式版本</Typography.Title>
                    <Typography.Paragraph type="secondary">
                      请使用“开始网页维护”进入草稿流程，检查差异与质量问题后发布新版本。
                    </Typography.Paragraph>
                    <ol>
                      <li>网页修改自动保存草稿</li>
                      <li>发布前检查差异和质量问题</li>
                      <li>确认后生成新的正式版本</li>
                    </ol>
                    <Button
                      block
                      aria-label="开始网页维护"
                      type="primary"
                      icon={<ToolOutlined />}
                      disabled={mutationBusy}
                      onClick={onOpenPositionDraft}
                    >
                      开始网页维护
                    </Button>
                  </div>
                ) : (
                  <>
                    <Typography.Title level={5}>
                      {activeVersion ? "上传替换当前版本" : "上传首个版本"}
                    </Typography.Title>
                    <Typography.Paragraph type="secondary">
                      先选择文件并核对名称，再手动确认。校验通过后立即启用，仅影响以后创建的批次。
                    </Typography.Paragraph>
                    {uploadError?.kind === selectedKind && (
                      <Alert className="inline-alert" type="error" showIcon title="上传失败" description={uploadError.message} />
                    )}
                    <Form form={uploadForm} layout="vertical">
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
                      已有批次继续使用创建时锁定的旧版本，不会被替换。
                    </Typography.Paragraph>
                  </>
                )}
              </Card>
            </section>

            <section aria-label="质量检查">
              <Card
                title="质量检查"
                className="input-data-section-card input-data-quality-card"
                extra={inspectionReady && selectedKind === "position" ? <Tag>{errors + warnings} 项提示</Tag> : undefined}
              >
                {renderQuality()}
              </Card>
            </section>
          </aside>
        </div>

        <section aria-label="版本记录">
          <Card
            title="版本记录"
            className="input-data-section-card input-data-history-card"
            extra={<Typography.Text type="secondary">共 {selectedVersions.length} 个版本</Typography.Text>}
          >
            <Table<InputVersion>
              rowKey="id"
              size="small"
              loading={loading}
              dataSource={selectedVersions}
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
                      <span>{formatDate(version.created_at)}</span>
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
                      description="仅影响以后创建的批次，已有批次继续使用锁定版本。"
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
          </Card>
        </section>
      </main>
    </div>
  );
}
