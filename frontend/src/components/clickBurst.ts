import { useRef } from "react";

/** Vraća onClick koji poziva `onBurst` posle `count` uzastopnih klikova (razmak najviše `gapMs`). */
export function useClickBurst(onBurst: () => void, count = 5, gapMs = 1500) {
  const state = useRef({ count: 0, last: 0 });
  return () => {
    const now = Date.now();
    const s = state.current;
    s.count = now - s.last <= gapMs ? s.count + 1 : 1;
    s.last = now;
    if (s.count < count) return;
    s.count = 0;
    onBurst();
  };
}
