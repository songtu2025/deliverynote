import BatchCreationModal from "./batches/BatchCreationModal";
import BatchListTable from "./batches/BatchListTable";
import BatchListToolbar from "./batches/BatchListToolbar";
import BatchReadiness from "./batches/BatchReadiness";
import { DELIVERY_VERSION_KINDS, SELF_OPERATED_VERSION_KINDS } from "./batches/batchWorkspace";
import { useBatchList } from "./batches/useBatchList";
import { useBatchCreation } from "./batches/useBatchCreation";
import { useBatchDeletion } from "./batches/useBatchDeletion";
import { useMemo } from "react";
import { Form, Skeleton, Typography } from "antd";
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
    syncStatus,
    setSyncStatus,
    load,
    refreshVersions
  } = list;
  const creation = useBatchCreation(workflow, onOpen);
  const { form, openCreate } = creation;
  const deletion = useBatchDeletion(workflow, active, list);
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
  const readiness = (
    <BatchReadiness
      workflow={workflow}
      activeVersions={activeVersions}
      versionKinds={versionKinds}
      missingKinds={missingKinds}
      activeSelfOperatedRule={activeSelfOperatedRule}
      activeOverreceiptRule={activeOverreceiptRule}
    />
  );
  const pageClassName = "page-shell batch-list-page batch-list-page--compact";
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
      </div>

      <section className="batch-materials" aria-label="运行状态">
        {workflow === "delivery" ? (
          <PurchaseSyncPanel
            versions={versions}
            canActivate={canActivatePurchaseSync}
            refreshVersions={refreshVersions}
            compact
            readiness={readiness}
          />
        ) : (
          <InboundSyncPanel syncStatus={syncStatus} sync={inboundSync} readiness={readiness} />
        )}
      </section>
      <BatchListToolbar
        workflow={workflow}
        active={active}
        canDeleteBatches={canDeleteBatches}
        list={list}
        deletion={deletion}
        ready={ready}
        onCreate={openCreate}
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
