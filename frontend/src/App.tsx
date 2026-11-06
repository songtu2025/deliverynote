import { App as AntApp, ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";

import SessionWorkspace from "./app/SessionWorkspace";

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#055247",
          colorInfo: "#2d5c94",
          colorLink: "#055247",
          colorLinkHover: "#055247",
          colorLinkActive: "#055247",
          fontSizeHeading2: 24,
          fontWeightStrong: 600,
          colorSuccess: "#055247",
          colorWarning: "#b4381f",
          colorError: "#a3162b",
          // 深色种子色自动派生的浅底偏灰，显式指定选中、提示和标签的底色与边框。
          colorPrimaryBg: "#e6f1ee",
          colorPrimaryBgHover: "#d9ebe5",
          colorPrimaryBorder: "#cfe4df",
          colorInfoBg: "#edf3fa",
          colorInfoBgHover: "#e1eaf5",
          colorInfoBorder: "#c9d8ea",
          colorSuccessBg: "#f3fbf7",
          colorSuccessBgHover: "#e6f4ec",
          colorSuccessBorder: "#cfe8dd",
          colorErrorBg: "#fff6f7",
          colorErrorBgHover: "#fbe9eb",
          colorErrorBorder: "#f2d1d4",
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
          Card: { borderRadiusLG: 10 },
          Tag: { borderRadiusSM: 4 },
          Table: { headerBg: "#f8fafc", headerColor: "#667085", headerSplitColor: "transparent" },
          Segmented: {
            trackBg: "#f1f4f8",
            itemSelectedBg: "#ffffff",
            itemSelectedColor: "#182230",
            borderRadius: 6,
            borderRadiusSM: 6
          },
          Alert: {
            colorWarning: "#8a5a12",
            colorWarningText: "#8a5a12",
            colorWarningBg: "#fdf4e3",
            colorWarningBorder: "#f1dfb6"
          },
          Layout: { siderBg: "#f8fafc" },
          Menu: {
            itemHeight: 44,
            itemMarginInline: 12,
            itemMarginBlock: 6,
            itemColor: "#475467",
            itemSelectedColor: "#055247",
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
