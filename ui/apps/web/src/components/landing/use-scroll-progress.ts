import { useEffect, useRef, useState } from "react";

/**
 * Progress (0..1) of scrolling through a tall section whose content is pinned
 * with `position: sticky`. 0 when the section top reaches the viewport top, 1
 * when its bottom reaches the viewport bottom.
 */
export function useScrollProgress<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const range = rect.height - window.innerHeight;
      const p = range > 0 ? -rect.top / range : rect.top < 0 ? 1 : 0;
      setProgress(Math.min(1, Math.max(0, p)));
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  return { ref, progress };
}

/** Maps progress within [from, to] to 0..1, clamped. */
export function range(p: number, from: number, to: number) {
  return Math.min(1, Math.max(0, (p - from) / (to - from)));
}

/**
 * Time-based 0..1 progress that plays once `threshold` of the element is on
 * screen and resets once it is fully off screen, so each visit replays.
 * `restart()` replays on demand.
 * With `scrollBoostPx`, scrolling while it plays also pushes it ahead: that
 * many pixels of scrolling (either direction) is worth the whole run.
 * With reduced motion it jumps straight to the end.
 */
export function usePlayOnView<T extends HTMLElement>(durationMs: number, threshold = 0.35, scrollBoostPx = 0) {
  const ref = useRef<T>(null);
  const [progress, setProgress] = useState(0);
  const [run, setRun] = useState(0);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let frame = 0;
    let last = 0;
    let p = 0;
    let lastY = window.scrollY;
    let boost = 0;
    const tick = (now: number) => {
      p = Math.min(1, p + (last ? (now - last) / durationMs : 0) + boost);
      last = now;
      boost = 0;
      setProgress(p);
      if (p < 1) frame = requestAnimationFrame(tick);
      else frame = 0;
    };
    const onScroll = () => {
      const y = window.scrollY;
      if (frame && scrollBoostPx) boost += Math.abs(y - lastY) / scrollBoostPx;
      lastY = y;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry) return;
        if (entry.isIntersecting && entry.intersectionRatio >= threshold) {
          if (frame || p > 0) return;
          if (reduced) {
            p = 1;
            return setProgress(1);
          }
          last = 0;
          boost = 0;
          lastY = window.scrollY;
          frame = requestAnimationFrame(tick);
        } else if (!entry.isIntersecting) {
          cancelAnimationFrame(frame);
          frame = 0;
          p = 0;
          setProgress(0);
        }
      },
      { threshold: [0, threshold] },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      window.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
    };
  }, [durationMs, threshold, scrollBoostPx, reduced, run]);

  return { ref, progress, restart: () => setRun((r) => r + 1) };
}

/** Eases a value toward a target over time (for steps that animate on their own). */
export function useAnimatedValue(target: number, speed = 2.5) {
  const [value, setValue] = useState(target);
  const current = useRef(target);
  useEffect(() => {
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const diff = target - current.current;
      if (Math.abs(diff) < 1e-4) {
        current.current = target;
        setValue(target);
        return;
      }
      current.current += diff * Math.min(1, dt * speed);
      setValue(current.current);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, speed]);
  return value;
}

export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}
