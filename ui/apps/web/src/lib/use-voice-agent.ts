import { useCallback, useEffect, useRef, useState } from "react";

import { getDetection, setDetection } from "./detection";
import { store } from "./swarm";

/**
 * The console side of the Mayfly voice agent (server: src/server/voice-agent.ts). Hold to talk records a question;
 * typed questions work too. With ElevenLabs on the server, the recording is transcribed and the reply is spoken there;
 * without it, the browser's own speech recognition and synthesis stand in.
 */

export type VoiceState = "idle" | "listening" | "thinking" | "speaking";

export interface Exchange {
  id: number;
  at: string;
  q: string;
  a: string;
  changes: string[];
  error?: boolean;
  /** Said by Mayfly unprompted (a new finding): there is no question. */
  alert?: boolean;
}

interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start(): void;
  stop(): void;
}

function browserRecognition(): SpeechRecognitionLike | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, (new () => SpeechRecognitionLike) | undefined>;
  const R = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return R ? new R() : null;
}

const now = () => new Date().toTimeString().slice(0, 5);

/** `consoleState` is what the agent may know about the mission: keep it small. */
export function useVoiceAgent(consoleState: () => unknown, missionDocs: () => { id: string; text: string }[]) {
  const [state, setState] = useState<VoiceState>("idle");
  const [log, setLog] = useState<Exchange[]>([]);
  const [eleven, setEleven] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const heard = useRef("");
  const seq = useRef(0);
  const logRef = useRef(log);
  logRef.current = log;

  useEffect(() => {
    fetch("/api/voice")
      .then((r) => r.json())
      .then((j: { elevenlabs?: boolean }) => setEleven(!!j.elevenlabs))
      .catch(() => setEleven(false));
  }, []);

  const say = useCallback((text: string, audio: string | null) => {
    if (audio) {
      const a = new Audio(`data:audio/mpeg;base64,${audio}`);
      setState("speaking");
      a.onended = a.onerror = () => setState("idle");
      a.play().catch(() => setState("idle"));
      return;
    }
    if (typeof speechSynthesis === "undefined") return setState("idle");
    const u = new SpeechSynthesisUtterance(text);
    u.onend = u.onerror = () => setState("idle");
    setState("speaking");
    speechSynthesis.speak(u);
  }, []);

  const send = useCallback(
    async (input: { question?: string; audio?: Blob }) => {
      setState("thinking");
      const form = new FormData();
      if (input.audio) form.append("audio", input.audio, "question.webm");
      if (input.question) form.append("question", input.question);
      const history = logRef.current.filter((e) => !e.error).map(({ q, a }) => ({ q, a }));
      form.append("context", JSON.stringify({ settings: getDetection(), console: consoleState(), history, docs: missionDocs() }));
      const id = ++seq.current;
      try {
        const r = await fetch("/api/voice", { method: "POST", body: form });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error ?? `HTTP ${r.status}`);
        if (j.changes.length) setDetection(j.settings);
        for (const a of j.actions as string[]) store.command(a === "pause" ? "pause" : "play");
        setLog((l) => [...l, { id, at: now(), q: j.question, a: j.reply, changes: j.changes }]);
        say(j.reply, j.audio);
      } catch (e) {
        setLog((l) => [...l, { id, at: now(), q: input.question ?? "(voice)", a: (e as Error).message, changes: [], error: true }]);
        setState("idle");
      }
    },
    [consoleState, missionDocs, say],
  );

  // Alerts go one at a time: the next one waits until the last has been said.
  const alerts = useRef<Promise<void>>(Promise.resolve());
  const announce = useCallback(
    (text: string) => {
      alerts.current = alerts.current.then(async () => {
        const id = ++seq.current;
        setLog((l) => [...l, { id, at: now(), q: "", a: text, changes: [], alert: true }]);
        let audio: string | null = null;
        if (eleven) {
          try {
            const form = new FormData();
            form.append("announce", text);
            audio = ((await (await fetch("/api/voice", { method: "POST", body: form })).json()) as { audio?: string | null }).audio ?? null;
          } catch {
            // the browser voice below still says it
          }
        }
        await new Promise<void>((done) => {
          if (audio) {
            const a = new Audio(`data:audio/mpeg;base64,${audio}`);
            a.onended = a.onerror = () => done();
            a.play().catch(() => done());
          } else if (typeof speechSynthesis !== "undefined") {
            const u = new SpeechSynthesisUtterance(text);
            u.onend = u.onerror = () => done();
            speechSynthesis.speak(u);
          } else done();
        });
      });
    },
    [eleven],
  );

  const start = useCallback(async () => {
    if (state !== "idle") return;
    if (typeof speechSynthesis !== "undefined") speechSynthesis.cancel();
    if (eleven && typeof MediaRecorder !== "undefined") {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const chunks: Blob[] = [];
        const rec = new MediaRecorder(stream);
        rec.ondataavailable = (e) => chunks.push(e.data);
        rec.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          const blob = new Blob(chunks, { type: rec.mimeType });
          if (blob.size > 2000) send({ audio: blob });
          else setState("idle");
        };
        rec.start();
        recorder.current = rec;
        setState("listening");
        return;
      } catch {
        // no microphone permission: fall through to the browser recognizer, which will ask again
      }
    }
    const r = browserRecognition();
    if (!r) {
      setLog((l) => [...l, { id: ++seq.current, at: now(), q: "(voice)", a: "This browser can't listen. Type the question instead.", changes: [], error: true }]);
      return;
    }
    heard.current = "";
    r.lang = "en-US";
    r.interimResults = false;
    r.onresult = (e) => {
      heard.current = Array.from(e.results, (x) => x[0].transcript).join(" ");
    };
    r.onerror = () => setState("idle");
    r.onend = () => {
      recognition.current = null;
      if (heard.current.trim()) send({ question: heard.current.trim() });
      else setState("idle");
    };
    r.start();
    recognition.current = r;
    setState("listening");
  }, [eleven, send, state]);

  const stop = useCallback(() => {
    recorder.current?.stop();
    recorder.current = null;
    recognition.current?.stop();
  }, []);

  const ask = useCallback((question: string) => question.trim() && state !== "thinking" && send({ question: question.trim() }), [send, state]);

  return { state, log, start, stop, ask, announce };
}
