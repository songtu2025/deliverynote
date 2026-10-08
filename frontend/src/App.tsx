import { App as AntApp, ConfigProvider, theme } from "antd";

import SessionWorkspace from "./app/SessionWorkspace";

export default function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#055247",
          colorInfo: "#055247",
          colorText: "#202a27",
          colorTextSecondary: "#707b76",
          colorBgLayout: "#f6f8f7",
          colorBorder: "#e3e8e5",
          borderRadius: 6,
          controlHeight: 36,
          fontFamily: '"PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif'
        },
        components: {
          Button: { primaryShadow: "none", defaultShadow: "none" },
          Menu: {
            itemHeight: 44,
            itemMarginInline: 12,
            itemMarginBlock: 6,
            itemColor: "#707b76",
            itemSelectedColor: "#055247",
            itemSelectedBg: "#edf4f0",
            itemHoverBg: "#f6f8f7",
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
