import { forwardRef } from "react";
import { Button, Upload } from "antd";
import { CloudUploadOutlined } from "@ant-design/icons";
import type { BatchFiles } from "./useBatchFiles";

const BatchInboundUpload = forwardRef<
  HTMLButtonElement,
  {
    upload: BatchFiles["uploadInboundFile"];
    disabled: boolean;
    loading: boolean;
    hidden?: boolean;
  }
>(function BatchInboundUpload({ upload, disabled, loading, hidden }, ref) {
  return (
    <span hidden={hidden}>
      <Upload accept=".xls,.xlsx" showUploadList={false} customRequest={upload} disabled={disabled}>
        <Button ref={ref} icon={<CloudUploadOutlined />} disabled={disabled} loading={loading}>
          上传自营仓入库单
        </Button>
      </Upload>
    </span>
  );
});

export default BatchInboundUpload;
