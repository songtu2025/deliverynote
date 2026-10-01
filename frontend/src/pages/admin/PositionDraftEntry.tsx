import { Alert, Button, Card, Spin } from "antd";
import { ArrowLeftOutlined, ReloadOutlined } from "@ant-design/icons";

interface PositionDraftEntryProps {
  loading: boolean;
  error: string | null;
  onBack: () => void;
  onRetry: () => Promise<void>;
}

export function PositionDraftEntry({ loading, error, onBack, onRetry }: PositionDraftEntryProps) {
  if (!loading && !error) return null;
  return (
    <div>
      <Button
        autoFocus
        aria-label="返回基础资料"
        className="back-link"
        type="link"
        icon={<ArrowLeftOutlined />}
        onClick={onBack}
      >
        返回基础资料
      </Button>
      {loading ? (
        <div style={{ minHeight: 360, display: "grid", placeItems: "center" }}>
          <Spin size="large" description="正在创建或恢复服务器草稿" />
        </div>
      ) : (
        <Card>
          <Alert
            type="error"
            showIcon
            title="无法打开库位草稿"
            description={error}
            action={
              <Button icon={<ReloadOutlined />} onClick={() => void onRetry()}>
                重新尝试
              </Button>
            }
          />
        </Card>
      )}
    </div>
  );
}
