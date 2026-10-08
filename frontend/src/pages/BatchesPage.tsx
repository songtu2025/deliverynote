import BatchCreationModal from "./batches/BatchCreationModal";
import BatchListTable from "./batches/BatchListTable";
import BatchListToolbar from "./batches/BatchListToolbar";
import BatchReadiness from "./batches/BatchReadiness";
import { DELIVERY_VERSION_KINDS, SELF_OPERATED_VERSION_KINDS } from "./batches/batchWorkspace";
import { useBatchList } from "./batches/useBatchList";
import { useBatchCreation } from "./batches/useBatchCreation";
import { useBatchDeletion } from "./batches/useBatchDeletion";
import { useMemo } from "react";
import { Button, Form, Popconfirm, Skeleton, Space, Typography } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import PurchaseSyncPanel from "./PurchaseSyncPanel";
import InboundSyncPanel from "./batches/InboundSyncPanel";
import { useInboundSync } from "./batches/useInboundSync";

export default function BatchesPage({
  onOpen,
  workflow = "delivery",
  active = true,
  canActivatePurchaseSync = false,
  canDeleteBatches = false
}: {
  onOpen: (id: number) => void;
  workflow?: "delivery" | "self_operated_inbound";
  active?: boolean;
  canActivatePurchaseSync?: boolean;
  canDeleteBatches?: boolean;
}) {
  const list = useBatchList(workflow, active);
  const {
    versions,
    overreceiptRules,
    selfOperatedRules,
    loading,
    initialized,
    emptyDraftCount,
    syncStatus,
    setSyncStatus,
    load,
    refreshVersions
  } = list;
  const creation = useBatchCreation(workflow, onOpen);
  const { form, openCreate } = creation;
  const deletion = useBatchDeletion(workflow, active, list);
  const { cleanEmptyBatches, cleaningEmpty } = deletion;
  const inboundSync = useInboundSync({ workflow, active, status: syncStatus, setStatus: setSyncStatus, reload: load });
  const activeVersions = useMemo(
    () => Object.fromEntries(versions.filter((version) => version.active).map((version) => [version.kind, version])),
    [versions]
  );
  const versionKinds = workflow === "self_operated_inbound" ? SELF_OPERATED_VERSION_KINDS : DELIVERY_VERSION_KINDS;
  const missingKinds = versionKinds.filter((kind) => !activeVersions[kind.value]);
  const activeOverreceiptRule = overreceiptRules.find((rule) => rule.active);
  const activeSelfOperatedRule = selfOperatedRules.find((rule) => rule.active);
  const ready = missingKinds.length === 0;
  const pageClassName = `page-shell batch-list-page${workflow === "delivery" ? " delivery-batch-list-page" : ""}`;
  if (loading && !initialized) {
    return (
      <div
        className={pageClassName}
        aria-busy="true"
        aria-label={workflow === "self_operated_inbound" ? "正在加载自营仓入库" : "正在加载交货批次"}
      >
        <Skeleton active title={{ width: 220 }} paragraph={{ rows: 8 }} />
        <Form form={form} component={false} />
      </div>
    );
  }
  return (
    <div className={pageClassName}>
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>
            {workflow === "self_operated_inbound" ? "自营仓入库" : "交货批次"}
          </Typography.Title>
          <Typography.Text type="secondary">
            {workflow === "self_operated_inbound"
              ? "匹配质检交货单与待入库数据，生成积加入库文件。"
              : "按文件顺序扣减采购余额，批次创建时锁定资料版本。"}
          </Typography.Text>
        </div>
        <Space>
          {emptyDraftCount > 0 && (
            <Popconfirm
              title={`删除 ${emptyDraftCount} 个空批次？`}
              description={
                workflow === "self_operated_inbound"
                  ? "仅删除未上传质检交货单和收货入库单的草稿，无法恢复。"
                  : "仅删除未上传任何交货文件的草稿，无法恢复。"
              }
              okText="删除"
              cancelText="取消"
              onConfirm={() => void cleanEmptyBatches()}
            >
              <Button danger icon={<DeleteOutlined />} loading={cleaningEmpty}>
                清理空批次（{emptyDraftCount}）
              </Button>
            </Popconfirm>
          )}
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!ready}
            title={ready ? "新建批次" : "请先补齐启用版本"}
            onClick={openCreate}
          >
            新建批次
          </Button>
        </Space>
      </div>

      {workflow === "delivery" && (
        <PurchaseSyncPanel
          versions={versions}
          canActivate={canActivatePurchaseSync}
          refreshVersions={refreshVersions}
          compact
        />
      )}

      {workflow === "self_operated_inbound" && <InboundSyncPanel syncStatus={syncStatus} sync={inboundSync} />}

      <BatchReadiness
        workflow={workflow}
        activeVersions={activeVersions}
        versionKinds={versionKinds}
        missingKinds={missingKinds}
        activeSelfOperatedRule={activeSelfOperatedRule}
        activeOverreceiptRule={activeOverreceiptRule}
      />
      <BatchListToolbar
        workflow={workflow}
        active={active}
        canDeleteBatches={canDeleteBatches}
        list={list}
        deletion={deletion}
      />
      <BatchListTable
        workflow={workflow}
        onOpen={onOpen}
        canDeleteBatches={canDeleteBatches}
        list={list}
        deletion={deletion}
      />
      <BatchCreationModal
        workflow={workflow}
        creation={creation}
        activeVersions={activeVersions}
        versionKinds={versionKinds}
        activeSelfOperatedRule={activeSelfOperatedRule}
        activeOverreceiptRule={activeOverreceiptRule}
      />
    </div>
  );
}
