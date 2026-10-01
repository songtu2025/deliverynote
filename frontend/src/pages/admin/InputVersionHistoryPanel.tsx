import { useMemo } from "react";
import { Button, Popconfirm, Table, Tag, Typography } from "antd";
import type { TableProps } from "antd";

import { formatBeijingDateTime } from "../../dateTime";
import type { InputVersion } from "../../types";

interface InputVersionHistoryPanelProps {
  label: string;
  versions: InputVersion[];
  loading: boolean;
  activationAllowed: boolean;
  mutationBusy: boolean;
  activatingVersionId: number | null;
  onActivate: (version: InputVersion) => void;
}

export function InputVersionHistoryPanel({
  label,
  versions,
  loading,
  activationAllowed,
  mutationBusy,
  activatingVersionId,
  onActivate
}: InputVersionHistoryPanelProps) {
  const tableComponents = useMemo<NonNullable<TableProps<InputVersion>["components"]>>(
    () => ({ table: (props) => <table {...props} aria-label={`${label}版本记录`} /> }),
    [label]
  );

  return (
    <section aria-label="版本记录" className="input-data-tab-panel">
      <div className="input-data-tab-heading">
        <div>
          <Typography.Title level={5}>版本记录</Typography.Title>
          <Typography.Text type="secondary">查看历次上传，并决定以后新建批次使用的版本。</Typography.Text>
        </div>
        <Typography.Text type="secondary">共 {versions.length} 个版本</Typography.Text>
      </div>
      <Table<InputVersion>
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={versions}
        components={tableComponents}
        pagination={versions.length > 8 ? { pageSize: 8, showSizeChanger: false } : false}
        scroll={{ x: 720 }}
        rowClassName={(version) => (version.active ? "input-data-active-version-row" : "")}
        locale={{ emptyText: `暂无${label}版本` }}
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
            render: (active: boolean) => (active ? <Tag color="success">当前启用</Tag> : <Tag>历史版本</Tag>)
          },
          {
            title: "操作",
            width: 100,
            render: (_, version) =>
              version.active || !activationAllowed ? null : (
                <Popconfirm
                  title={`启用 ${version.name}？`}
                  description="仅用于新批次；已有批次不变。"
                  okText="确认启用"
                  cancelText="取消"
                  onConfirm={() => onActivate(version)}
                >
                  <Button
                    type="link"
                    aria-busy={activatingVersionId === version.id}
                    disabled={mutationBusy}
                    loading={activatingVersionId === version.id}
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
}
