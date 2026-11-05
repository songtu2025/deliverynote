import { Alert, Button, Flex, Input, InputNumber, Table, Typography } from "antd";
import type { TableColumnsType } from "antd";
import type { InboundAllocation, InboundAllocations } from "../../inboundExceptionApi";
import type { DeliveryException } from "../../types";
import { useTargetedAllowances } from "./useTargetedAllowances";

export default function InboundAllocationEditor({
  data,
  exception,
  onSaved
}: {
  data: InboundAllocations;
  exception: DeliveryException;
  onSaved?: () => Promise<unknown>;
}) {
  const editor = useTargetedAllowances(data, exception, onSaved);
  return (
    <Flex vertical gap="small">
      {Boolean(data.inactive_allowances?.length) && (
        <Alert
          type="warning"
          showIcon
          title="指定的 PO 本次无分配，追加未生效"
          description={data.inactive_allowances?.map((entry) => entry.po_code + " / " + entry.inbound_no).join("、")}
        />
      )}
      <Table<InboundAllocation>
        size="small"
        rowKey="id"
        dataSource={data.items}
        scroll={{ x: 1580 }}
        pagination={{ pageSize: 10, showSizeChanger: false, hideOnSinglePage: true }}
        locale={{ emptyText: "当前文件的该 SKU 在此站点暂无可入库分配" }}
        columns={allocationColumns(editor)}
      />
      <label htmlFor="targeted-allowance-reason">原因（选填）</label>
      <Input
        id="targeted-allowance-reason"
        aria-label="原因"
        value={editor.reason}
        disabled={editor.busy || Boolean(editor.disabledReason)}
        onChange={(event) => editor.setReason(event.target.value)}
      />
      {editor.error && <Alert id="targeted-allowance-error" type="error" showIcon title={editor.error} />}
      {editor.disabledReason && <Typography.Text type="secondary">{editor.disabledReason}</Typography.Text>}
      <Flex justify="space-between" align="center" gap="small" wrap>
        <Typography.Text>
          合计追加：{editor.total} / {editor.limit}
        </Typography.Text>
        <Button
          type="primary"
          loading={editor.busy}
          disabled={!editor.changed || Boolean(editor.error) || Boolean(editor.disabledReason)}
          onClick={() => void editor.submit()}
        >
          保存并重算
        </Button>
      </Flex>
    </Flex>
  );
}

const showValue = (value: string | number | null) => value ?? "—";
type AllowanceEditor = ReturnType<typeof useTargetedAllowances>;

function exceedsMaximum(row: InboundAllocation, quantity: number) {
  if (row.max_receive_quantity == null || row.max_receive_quantity === "") return false;
  if (row.received_quantity == null || row.received_quantity === "") return false;
  return quantity > Math.max(Number(row.max_receive_quantity) - Number(row.received_quantity), 0);
}

function allocationColumns(editor: AllowanceEditor): TableColumnsType<InboundAllocation> {
  return [
    { title: "PO 单号", dataIndex: "po_code", width: 150, render: showValue },
    { title: "关联交货单", dataIndex: "delivery_no", width: 150, render: showValue },
    { title: "入库单号", dataIndex: "inbound_no", width: 150, render: showValue },
    { title: "完整站点", dataIndex: "site", width: 190, render: showValue },
    { title: "入库仓", dataIndex: "warehouse", width: 140, render: showValue },
    { title: "历史已入库", dataIndex: "history_quantity", width: 100, align: "right", render: showValue },
    { title: "正常分配", dataIndex: "normal_quantity", width: 100, align: "right", render: showValue },
    { title: "规则内超收", dataIndex: "overreceipt_quantity", width: 100, align: "right", render: showValue },
    {
      title: "本次分配",
      dataIndex: "current_quantity",
      width: 160,
      align: "right",
      render: (value, row) => (
        <>
          {showValue(value)}
          {exceedsMaximum(row, Number(value) - (row.targeted_quantity ?? 0) + editor.valueFor(row)) && (
            <div>
              <Typography.Text type="warning">超出最大可收货，积加可能拒收</Typography.Text>
            </div>
          )}
        </>
      )
    },
    { title: "最大可收货", dataIndex: "max_receive_quantity", width: 100, align: "right", render: showValue },
    { title: "已收货", dataIndex: "received_quantity", width: 100, align: "right", render: showValue },
    {
      title: "追加超收",
      width: 140,
      fixed: "right",
      render: (_, row) => (
        <InputNumber<number>
          aria-label={"追加超收 " + row.po_code + " " + row.inbound_no}
          aria-describedby={editor.error ? "targeted-allowance-error" : undefined}
          min={0}
          precision={0}
          step={1}
          value={editor.valueFor(row)}
          disabled={editor.busy || Boolean(editor.disabledReason) || !row.inbound_no || !row.po_code}
          onChange={(quantity) => editor.setQuantity(row, quantity)}
        />
      )
    }
  ];
}
