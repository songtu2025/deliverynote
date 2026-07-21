import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { message } from "antd";
import { afterEach } from "vitest";

const flushReactScheduler = () => new Promise<void>((resolve) => {
  const scheduleImmediate = (globalThis as typeof globalThis & {
    setImmediate: (callback: () => void) => unknown;
  }).setImmediate;
  scheduleImmediate(resolve);
});

afterEach(async () => {
  cleanup();
  message.destroy();
  await Promise.resolve();
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
