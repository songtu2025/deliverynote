import { Breadcrumb, Button } from "antd";

export default function BatchBreadcrumb({
  batchId,
  selfOperated = false,
  onBack
}: {
  batchId: number;
  selfOperated?: boolean;
  onBack: () => void;
}) {
  return (
    <Breadcrumb
      className="batch-breadcrumb"
      items={[
        {
          title: (
            <Button type="link" aria-label="返回批次列表" onClick={onBack}>
              {selfOperated ? "自营仓入库" : "交货批次"}
            </Button>
          )
        },
        { title: <span aria-current="page">#{batchId}</span> }
      ]}
    />
  );
}
