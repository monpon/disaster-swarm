import { useEffect, useRef } from "react";

import { store } from "@/lib/swarm";

/** Drone `drone`'s camera, drawn straight from the frames the database pushes (no React render per frame). */
export function FeedCanvas({ drone, className }: { drone: number; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(
    () =>
      store.onFeed(drone, (b) => {
        const c = ref.current;
        if (!c) return;
        if (c.width !== b.width || c.height !== b.height) {
          c.width = b.width;
          c.height = b.height;
        }
        c.getContext("2d")!.drawImage(b, 0, 0);
      }),
    [drone],
  );
  return <canvas ref={ref} className={className} />;
}
