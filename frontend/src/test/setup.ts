import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { message } from "antd";
import { afterEach } from "vitest";

const flushReactScheduler = async () => {
  const scheduleImmediate = (globalThis as typeof globalThis & {
    setImmediate: (callback: () => void) => unknown;
  }).setImmediate;
  for (let turn = 0; turn < 4; turn += 1) {
    await Promise.resolve();
    await new Promise<void>((resolve) => scheduleImmediate(resolve));
  }
};

afterEach(async () => {
  cleanup();
  message.destroy();
  await flushReactScheduler();
});

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false
  })
});

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(window, "ResizeObserver", {
  writable: true,
  value: ResizeObserverMock
});
Object.defineProperty(globalThis, "ResizeObserver", {
  writable: true,
  value: ResizeObserverMock
});

const nativeGetComputedStyle = window.getComputedStyle;
window.getComputedStyle = (element: Element) => nativeGetComputedStyle(element);
