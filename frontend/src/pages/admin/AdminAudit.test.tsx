import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AuditLog } from "../../types";
import { AuditLogPanel } from "./AuditLogPanel";
import { admin, operator, render, setupAdminTests } from "./adminPageTestSupport";

describe("管理员Audit", () => {
  const state = setupAdminTests();
  it("offers labelled audit filters and a clear result count", () => {
    const records: AuditLog[] = [
      {
        id: 1,
        user_id: 1,
        action: "create_user",
        entity_type: "user",
        entity_id: "2",
        details: {},
        created_at: "2026-07-21T09:00:00"
      },
      {
        id: 2,
        user_id: null,
        action: "worker_compute_failed",
        entity_type: "batch",
        entity_id: "7",
        details: {},
        created_at: "2026-07-21T09:10:00"
      },
      {
        id: 3,
        user_id: 2,
        action: "publish_overreceipt_rule",
        entity_type: "overreceipt_rule",
        entity_id: "4",
        details: {},
        created_at: "2026-07-21T09:20:00"
      }
    ];
    render(
      <AuditLogPanel auditLogs={records} users={[admin, operator]} loading={false} error={null} onRetry={vi.fn()} />
    );

    expect(screen.getByRole("table", { name: "操作记录" })).toBeInTheDocument();
    expect(screen.getByText("搜索", { selector: "label" })).toBeInTheDocument();
    expect(screen.getByText("操作类型", { selector: "label" })).toBeInTheDocument();
    expect(screen.getByText("操作人", { selector: "label" })).toBeInTheDocument();
    expect(screen.getByText("显示 3 / 3 条")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("搜索操作记录"), { target: { value: "批次 #7" } });
    expect(screen.getByText("显示 1 / 3 条")).toBeInTheDocument();
    expect(screen.getByText("计算失败")).toBeInTheDocument();
    expect(screen.queryByText("创建用户")).not.toBeInTheDocument();
  });

  it("translates self-operated sync audit values", () => {
    const records: AuditLog[] = [
      {
        id: 4,
        user_id: null,
        action: "self_operated_inbound_sync_succeeded",
        entity_type: "self_operated_inbound_sync_job",
        entity_id: "12",
        details: {},
        created_at: "2026-07-21T09:30:00"
      }
    ];

    render(
      <AuditLogPanel auditLogs={records} users={[admin, operator]} loading={false} error={null} onRetry={vi.fn()} />
    );

    expect(screen.getByText("待入库数据同步完成")).toBeInTheDocument();
    expect(screen.getByText("待入库同步任务 #12")).toBeInTheDocument();
  });

  it("shows draft audit labels and resolves operator names", async () => {
    state.auditLogs = [
      {
        id: 8,
        user_id: 2,
        action: "activate_overreceipt_rule",
        entity_type: "overreceipt_rule",
        entity_id: "9",
        details: {},
        created_at: "2026-07-21T09:07:00"
      },
      {
        id: 7,
        user_id: 2,
        action: "publish_overreceipt_rule",
        entity_type: "overreceipt_rule",
        entity_id: "9",
        details: {},
        created_at: "2026-07-21T09:06:00"
      },
      {
        id: 6,
        user_id: 1,
        action: "activate_input_version",
        entity_type: "input_version",
        entity_id: "32",
        details: {},
        created_at: "2026-07-21T09:05:00"
      },
      {
        id: 5,
        user_id: 1,
        action: "publish_input_draft",
        entity_type: "input_draft",
        entity_id: "7",
        details: {},
        created_at: "2026-07-21T09:04:00"
      },
      {
        id: 4,
        user_id: 1,
        action: "discard_input_draft",
        entity_type: "input_draft",
        entity_id: "7",
        details: {},
        created_at: "2026-07-21T09:03:00"
      },
      {
        id: 3,
        user_id: 2,
        action: "import_input_draft",
        entity_type: "input_draft",
        entity_id: "7",
        details: {},
        created_at: "2026-07-21T09:02:00"
      },
      {
        id: 2,
        user_id: 2,
        action: "create_input_draft",
        entity_type: "input_draft",
        entity_id: "7",
        details: {},
        created_at: "2026-07-21T09:01:00"
      },
      {
        id: 1,
        user_id: 2,
        action: "resume_input_draft",
        entity_type: "input_draft",
        entity_id: "7",
        details: {},
        created_at: "2026-07-21T09:00:00"
      }
    ];
    render(
      <AuditLogPanel auditLogs={state.auditLogs} users={state.users} loading={false} error={null} onRetry={vi.fn()} />
    );

    expect(await screen.findByText("创建库位草稿")).toBeInTheDocument();
    expect(screen.getByText("导入库位草稿")).toBeInTheDocument();
    expect(screen.getByText("放弃库位草稿")).toBeInTheDocument();
    expect(screen.getByText("发布库位版本")).toBeInTheDocument();
    expect(screen.getByText("启用输入版本")).toBeInTheDocument();
    expect(screen.getByText("继续库位草稿")).toBeInTheDocument();
    expect(screen.getByText("发布超收规则")).toBeInTheDocument();
    expect(screen.getByText("启用超收规则")).toBeInTheDocument();
    expect(screen.queryByText("resume_input_draft")).not.toBeInTheDocument();
    expect(screen.getAllByText("operator").length).toBeGreaterThan(0);
  });

  it("shows audit loading, empty, and error feedback", async () => {
    const { rerender } = render(
      <AuditLogPanel auditLogs={[]} users={state.users} loading error={null} onRetry={vi.fn()} />
    );
    expect(screen.getByText("正在读取操作记录")).toBeInTheDocument();

    rerender(<AuditLogPanel auditLogs={[]} users={state.users} loading={false} error={null} onRetry={vi.fn()} />);
    expect(await screen.findByText("暂无操作记录")).toBeInTheDocument();
  });

  it("keeps audit failures inside the operation history panel", async () => {
    render(
      <AuditLogPanel auditLogs={[]} users={state.users} loading={false} error="审计服务暂时不可用" onRetry={vi.fn()} />
    );

    expect(await screen.findByText("无法读取操作记录")).toBeInTheDocument();
    expect(screen.getByText("审计服务暂时不可用")).toBeInTheDocument();
  });
});
