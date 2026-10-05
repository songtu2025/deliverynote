import { useEffect, useRef } from "react";

export function usePositionRequestGuard() {
  const inFlightRef = useRef(false);
  const generationRef = useRef(0);
  const activeRef = useRef(true);

  useEffect(() => {
    activeRef.current = true;
    return () => {
      activeRef.current = false;
      generationRef.current += 1;
    };
  }, []);

  const invalidate = () => {
    // 只使旧响应失效，正在执行的请求仍持有锁。
    generationRef.current += 1;
  };

  return { inFlightRef, generationRef, activeRef, invalidate };
}
