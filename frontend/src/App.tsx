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
          colorText: "#141b18",
          colorTextSecondary: "#63736e",
          colorBgLayout: "#fbfcfb",
          colorBorder: "#dfe6e3",
          borderRadius: 8,
          fontFamily: "Inter, Microsoft YaHei, sans-serif"
        }
      }}
    >
      <AntApp>
        <SessionWorkspace />
      </AntApp>
    </ConfigProvider>
  );
}
