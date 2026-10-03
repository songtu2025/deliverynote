import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Typography } from "antd";
import { InputDataPanel } from "./InputDataPanel";
import { AdminPanelFallback } from "./AdminPanelFallback";
import type { AdminData } from "./useAdminData";

const PositionMaintenance = lazy(() =>
  import("./PositionMaintenance").then((module) => ({
    default: module.PositionMaintenance
  }))
);

type InputView = "catalog" | "position";

export function AdminInputWorkspace({ data }: { data: AdminData }) {
  const { versions, loading, errors, loadVersions, refreshVersions } = data;
  const [inputView, setInputView] = useState<InputView>("catalog");
  const inputWorkspaceRef = useRef<HTMLDivElement>(null);
  const focusInputViewRef = useRef(false);
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  useEffect(() => {
    if (!focusInputViewRef.current || inputView !== "catalog") return undefined;
    focusInputViewRef.current = false;
    const timer = window.setTimeout(() => {
      inputWorkspaceRef.current?.querySelector<HTMLElement>('[data-input-catalog-heading="true"]')?.focus();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [inputView]);

  const activePositionVersion = useMemo(
    () => versions.find((version) => version.kind === "position" && version.active) ?? null,
    [versions]
  );

  const openPosition = () => {
    focusInputViewRef.current = true;
    setInputView("position");
  };

  const returnToCatalog = () => {
    focusInputViewRef.current = true;
    setInputView("catalog");
  };

  const handlePublished = async () => {
    const refreshed = await loadVersions(false, true, "库位版本已发布，但读取基础资料目录失败：");
    if (mountedRef.current) returnToCatalog();
    return refreshed;
  };

  return (
    <div className="input-workspace" ref={inputWorkspaceRef}>
      {inputView === "catalog" ? (
        <div className="input-data-view">
          <div className="admin-section-heading">
            <div>
              <Typography.Title data-input-catalog-heading="true" tabIndex={-1} level={4}>
                基础资料目录
              </Typography.Title>
            </div>
          </div>
          {errors.versions && (
            <Alert
              className="inline-alert"
              type="error"
              showIcon
              title="无法读取基础资料"
              description={errors.versions}
              action={
                <Button size="small" onClick={() => void refreshVersions()}>
                  重新加载
                </Button>
              }
            />
          )}
          <div className="input-data-layout">
            <InputDataPanel
              versions={versions}
              loading={loading.versions}
              onVersionsChanged={() => loadVersions(true, true)}
              onOpenPositionDraft={openPosition}
            />
          </div>
        </div>
      ) : activePositionVersion ? (
        <div className="position-workspace">
          <Suspense fallback={<AdminPanelFallback />}>
            <PositionMaintenance
              activeVersion={activePositionVersion}
              onPublished={handlePublished}
              onBack={returnToCatalog}
            />
          </Suspense>
        </div>
      ) : null}
    </div>
  );
}
