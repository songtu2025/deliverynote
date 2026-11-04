import { Fragment } from "react";
import { Typography } from "antd";
import { workspacePath } from "../../app/workspaceRoutes";
import type { Batch } from "../../types";

export default function BatchTransferSources({ batch, fileId }: { batch: Batch; fileId?: number }) {
  const sources = batch.transfer_sources?.filter((source) => fileId === undefined || source.file_ids.includes(fileId));
  if (!sources?.length) return null;
  return (
    <div className="muted">
      {fileId === undefined && "转自 "}
      {sources.map((source, index) => (
        <Fragment key={source.batch_id}>
          {index > 0 && "、"}
          {fileId === undefined ? "自营仓 " : "转自 "}
          <Typography.Link href={workspacePath({ page: "self-operated", batchId: source.batch_id })}>
            #{source.batch_id}
          </Typography.Link>
          {fileId === undefined && ` · ${source.record_count} 条 ${source.quantity} 件`}
        </Fragment>
      ))}
    </div>
  );
}
