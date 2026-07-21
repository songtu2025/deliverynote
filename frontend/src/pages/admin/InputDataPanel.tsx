import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Divider,
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
  ToolOutlined,
  UploadOutlined
} from "@ant-design/icons";
import type { TableProps, UploadProps } from "antd";

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

  const uploadVersion: NonNullable<UploadProps["customRequest"]> = async (options) => {
    if (mutationBusy) {
      options.onError?.(new Error("已有资料操作正在进行"));
      return;
    }
    const kind = selectedKind;
    setUploadError(null);
    setMutation({ kind, action: "upload" });
    try {
      const values = await uploadForm.validateFields();
      const formData = new FormData();
      formData.append("name", values.name);
      formData.append("activate", "true");
      formData.append("file", options.file as File);
      await api<InputVersion>(`/api/input-versions/${kind}`, {
        method: "POST",
        body: formData
      });
      options.onSuccess?.({});
      uploadForm.resetFields();
      await onVersionsChanged();
      message.success(`${INPUT_KIND_BY_VALUE[kind].label}已上传并启用，仅影响以后创建的批次`);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "上传失败";
      setUploadError({ kind, message: errorMessage });
      options.onError?.(error instanceof Error ? error : new Error(errorMessage));
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

  const renderSummary = () => {
    if (!activeVersion || inspectionVersionId !== activeVersion.id || !summary || !preview) return null;
    const errors = issueCount(summary.issues, "error");
    const warnings = issueCount(summary.issues, "warning");
    const metricItems = selectedKind === "position"
      ? [
          `${summary.row_count} 行`,
          `${summary.metrics.sites ?? 0} 个站点`,
          `${summary.metrics.skus ?? 0} 个积加 SKU`,
          `${summary.metrics.mskus ?? 0} 个 MSKU`,
          `${errors} 个错误`,
          `${warnings} 个警告`
        ]
      : [`${summary.row_count} 行`, `${summary.columns.length} 个字段`];

    return (
      <>
        <Divider titlePlacement="start">摘要指标</Divider>
        <Space wrap size={[8, 8]}>
          {metricItems.map((item) => <Tag key={item} color="blue">{item}</Tag>)}
        </Space>

        <Divider titlePlacement="start">质量问题</Divider>
        {selectedKind !== "position" ? (
          <Alert type="info" showIcon title="文件结构已通过校验，当前未执行内容质量诊断" />
        ) : summary.issues.length === 0 ? (
          <Alert type="success" showIcon title="未发现资料质量问题" />
        ) : (
          <Space orientation="vertical" size={8} style={{ width: "100%" }}>
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
        )}

        <Divider titlePlacement="start">内容预览</Divider>
        <Table<PreviewRow>
          rowKey="__previewKey"
          size="small"
          columns={previewColumns}
          dataSource={previewRows}
          pagination={false}
          scroll={{ x: "max-content" }}
          locale={{ emptyText: "当前版本没有可预览的数据" }}
        />
        {preview.total > preview.rows.length && (
          <Typography.Text type="secondary">当前展示前 {preview.rows.length} 行，共 {preview.total} 行。</Typography.Text>
        )}
      </>
    );
  };

  return (
    <div className="input-data-panel" style={{ display: "flex", alignItems: "flex-start", gap: 18 }}>
      <Card
        className="input-data-catalog"
        title={<Space><DatabaseOutlined />基础资料</Space>}
        style={{ flex: "0 0 280px", width: 280 }}
        styles={{ body: { padding: 8 } }}
      >
        <Space orientation="vertical" size={8} style={{ width: "100%" }}>
          {INPUT_KIND_DEFINITIONS.map((definition) => {
            const current = versions.find((version) => version.kind === definition.value && version.active);
            const selected = definition.value === selectedKind;
            return (
              <Button
                key={definition.value}
                aria-label={current
                  ? `${definition.label}，已就绪，当前版本 ${current.name}`
                  : `${definition.label}，未启用，等待上传`}
                aria-pressed={selected}
                block
                disabled={mutationBusy}
                type={selected ? "primary" : "default"}
                onClick={() => setSelectedKind(definition.value)}
                style={{ height: "auto", padding: "11px 12px", whiteSpace: "normal", textAlign: "left" }}
              >
                <span style={{ display: "flex", width: "100%", flexDirection: "column", alignItems: "stretch", gap: 4 }}>
                  <span style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                    <strong>{definition.label}</strong>
                    {current ? <CheckCircleFilled aria-label="已就绪" /> : <Tag color="warning">未启用</Tag>}
                  </span>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{current?.name ?? "等待上传"}</span>
                  <small>{current ? formatDate(current.created_at) : "尚无启用版本"}</small>
                </span>
              </Button>
            );
          })}
        </Space>
      </Card>

      <Card
        className="input-data-detail"
        title={selectedDefinition.label}
        style={{ flex: "1 1 auto", minWidth: 0 }}
        extra={(
          <Space wrap>
            {activeVersion && (
              <Button aria-label="下载当前文件" icon={<DownloadOutlined />} onClick={() => void downloadCurrent()}>
                下载当前文件
              </Button>
            )}
            {selectedKind === "position" && (
              <Button
                aria-label="开始网页维护"
                type="primary"
                icon={<ToolOutlined />}
                disabled={!activeVersion || mutationBusy}
                onClick={onOpenPositionDraft}
              >
                开始网页维护
              </Button>
            )}
          </Space>
        )}
      >
        <Typography.Paragraph strong>{selectedDefinition.purpose}</Typography.Paragraph>
        <Descriptions
          size="small"
          column={1}
          items={[
            { key: "impact", label: "影响范围", children: selectedDefinition.impact },
            { key: "fields", label: "必填字段", children: selectedDefinition.requiredFields.join("、") }
          ]}
        />

        {actionError?.kind === selectedKind && (
          <Alert type="error" showIcon closable title="操作失败" description={actionError.message} />
        )}

        <Divider titlePlacement="start">当前启用版本</Divider>
        {loading ? (
          <div style={{ minHeight: 120, display: "grid", placeItems: "center" }}><Spin description="读取资料状态" /></div>
        ) : !activeVersion ? (
          <Alert
            type="warning"
            showIcon
            title={`${selectedDefinition.label}尚无启用版本`}
            description="请在下方上传并启用一个通过校验的 Excel 版本。"
          />
        ) : (
          <>
            <Descriptions
              size="small"
              bordered
              column={2}
              items={[
                { key: "name", label: "版本", children: activeVersion.name },
                { key: "file", label: "文件", children: activeVersion.original_name },
                { key: "creator", label: "创建人", children: `用户 #${activeVersion.created_by}` },
                { key: "created", label: "上传时间", children: formatDate(activeVersion.created_at) }
              ]}
            />
            {inspectionLoading || (inspectionVersionId !== activeVersion.id && !inspectionError) ? (
              <div style={{ minHeight: 160, display: "grid", placeItems: "center" }}><Spin description="读取摘要与预览" /></div>
            ) : inspectionError?.versionId === activeVersion.id ? (
              <Alert
                type="error"
                showIcon
                title="无法读取当前版本内容"
                description={inspectionError.message}
                action={<Button size="small" onClick={() => setInspectionAttempt((value) => value + 1)}>重新加载</Button>}
              />
            ) : renderSummary()}
          </>
        )}

        <Divider titlePlacement="start">上传替换</Divider>
        <Typography.Paragraph type="secondary">
          当前固定上传为“{selectedDefinition.label}”，文件校验通过后立即启用，仅影响以后创建的批次。
        </Typography.Paragraph>
        {uploadError?.kind === selectedKind && (
          <Alert className="inline-alert" type="error" showIcon title="上传失败" description={uploadError.message} />
        )}
        <Form form={uploadForm} layout="inline">
          <Form.Item
            label="版本名称"
            name="name"
            rules={[{ required: true, message: "请输入版本名称" }]}
          >
            <Input disabled={mutationBusy} placeholder={`例如：${selectedKind}-20260721`} style={{ width: 260 }} />
          </Form.Item>
          <Form.Item>
            <Upload disabled={mutationBusy} accept=".xls,.xlsx" showUploadList={false} customRequest={uploadVersion}>
              <Button
                aria-label="选择 Excel 并上传替换"
                aria-busy={uploading}
                disabled={mutationBusy}
                loading={uploading}
                icon={<UploadOutlined />}
              >
                选择 Excel 并上传替换
              </Button>
            </Upload>
          </Form.Item>
        </Form>

        <Divider titlePlacement="start">版本记录</Divider>
        <Table<InputVersion>
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={selectedVersions}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          scroll={{ x: 760 }}
          locale={{ emptyText: `暂无${selectedDefinition.label}版本` }}
          columns={[
            { title: "版本", dataIndex: "name", width: 180 },
            { title: "文件", dataIndex: "original_name", ellipsis: true, width: 220 },
            { title: "上传时间", dataIndex: "created_at", width: 190, render: formatDate },
            {
              title: "状态",
              dataIndex: "active",
              width: 110,
              render: (active: boolean) => active ? <Tag color="success">当前启用</Tag> : <Tag>历史版本</Tag>
            },
            {
              title: "操作",
              width: 100,
              render: (_, version) => version.active ? null : (
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
    </div>
  );
}
