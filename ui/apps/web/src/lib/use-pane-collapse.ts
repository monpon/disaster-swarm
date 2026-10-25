import type { PanelImperativeHandle } from "@swarm/ui/components/resizable";
import { useEffect, useRef, useState } from "react";

/**
 * Wires a ResizablePanel to a header collapse button. Tracks collapse state
 * through onResize, so dragging past the threshold keeps the button in sync.
 */
export function usePaneCollapse(defaultCollapsed = false) {
  const ref = useRef<PanelImperativeHandle | null>(null);
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const onResize = () => setCollapsed(ref.current?.isCollapsed() ?? false);
  const toggle = () => {
    const panel = ref.current;
    if (!panel) return;
    if (panel.isCollapsed()) panel.expand();
    else panel.collapse();
  };
  useEffect(() => {
    if (defaultCollapsed) ref.current?.collapse();
    // Only applied once, right after the panel mounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return { ref, collapsed, onResize, toggle };
}
