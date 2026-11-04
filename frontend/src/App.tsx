import { App as AntApp, ConfigProvider, theme } from "antd";

import SessionWorkspace from "./app/SessionWorkspace";

export default function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#055247",
          colorInfo: "#2d5c94",
          colorSuccess: "#1f6b52",
          colorWarning: "#b4381f",
          colorError: "#a3162b",
          colorText: "#182230",
          colorTextSecondary: "#667085",
          colorBgLayout: "#f1f4f8",
          colorBorder: "#848ea0",
          colorBorderSecondary: "#e3e8ef",
          borderRadius: 6,
          controlHeight: 36,
          fontFamily: '"PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif'
        },
        components: {
          Button: { primaryShadow: "none", defaultShadow: "none" },
          // 深主色自动派生的选中底色偏灰，统一改为浅绿。
          Table: { rowSelectedBg: "#edf7f3", rowSelectedHoverBg: "#e6f3ef" },
          Layout: { siderBg: "#f8fafc" },
          Menu: {
            itemHeight: 44,
            itemMarginInline: 12,
            itemMarginBlock: 6,
            itemColor: "#475467",
            itemSelectedColor: "#055247",
            itemSelectedBg: "#e6f1ee",
            itemHoverBg: "#f1f4f8",
            activeBarBorderWidth: 0
          }
        }
      }}
    >
      <AntApp>
        <SessionWorkspace />
      </AntApp>
    </ConfigProvider>
  );
}
