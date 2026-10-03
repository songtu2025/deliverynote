import { Skeleton } from "antd";

export function AdminPanelFallback() {
  return (
    <div aria-busy="true" aria-label="正在加载维护模块">
      <Skeleton active title={false} paragraph={{ rows: 5 }} />
    </div>
  );
}
