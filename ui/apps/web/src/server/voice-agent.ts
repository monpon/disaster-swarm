import Anthropic from "@anthropic-ai/sdk";

import { reviewOptions, type DetectionSettings } from "@/lib/detection";
import { searchMission, type MissionDoc } from "./mission-search";

/**
 * Mayfly's voice agent, server side. A question (spoken or typed) and a snapshot of the console come in; Claude answers
 * about the search and may change what the drones look for. Speech goes through ElevenLabs when ELEVENLABS_API_KEY is
 * set; without it the browser does its own speech recognition and synthesis.
 */

const MODEL = "claude-opus-5-5";
const MAX_STEPS = 4;
const ELEVEN = "https://api.elevenlabs.io/v1";

export interface AgentRequest {
  question: string;
  settings: DetectionSettings;
  /** What the console shows right now: mission, drones, findings. Free-form, already trimmed by the browser. */
  console: unknown;
  /** The last few exchanges, oldest first. */
  history: { q: string; a: string }[];
  /** What the mission knows, one short document each (findings with routes, recent events): searched with Moss. */
  docs?: MissionDoc[];
}

export type MissionAction = "pause" | "resume";

export interface AgentReply {
  question: string;
  reply: string;
  settings: DetectionSettings;
  changes: string[];
  actions: MissionAction[];
  audio: string | null;
}

const SYSTEM = `You are Mayfly, the voice assistant in the console of a search-and-rescue drone system. Firefighters and the incident commander talk to you hands-free during a search, so your answers are spoken aloud.

How Mayfly searches:
- Several small drones fly a building together and build one shared map. A central computer runs object detection on every camera frame.
- The detector is a YOLO model (object_det/model.pt) trained for disaster response. It reports fire, smoke, person and door with a confidence between 0 and 1.
- The console lets the crew choose which classes the drones search for, the minimum confidence for each class, and whether a finding is spoken to the crew right away or only on request.
- Camera vitals estimate breathing and pulse when a drone holds on a person. They are estimates, never a medical assessment.
- Findings below the human-review threshold wait for the incident commander before they reach the crew.
- Raising a class's minimum confidence means fewer false alarms but a higher chance of missing something; lowering it finds more but with more false alarms. For people, missing someone is worse than a false alarm.

How to answer:
- Answer in one to three short spoken sentences. No markdown, no lists, no emoji. Say numbers the way a person would ("sixty percent", "zero point six").
- Use the console state you are given to answer questions about the mission as it is right now. For routes to people, past events and how Mayfly works, call search_mission first and answer only from what it returns. If neither says, say you do not know rather than guessing.
- When you give a route, read the directions in order, with the distance, and say if part of it is not mapped yet. Never invent a turn. Routes are guidance on the map; the incident commander decides.
- When the user asks to change what the drones look for, use the tools, then say plainly what changed. If a request is ambiguous or unsafe for the search (for example turning off person detection), make the change only if they clearly asked for it, and mention the risk in one short phrase.
- You cannot fly or steer drones. You can pause or resume the search as a whole.
- Latency-sensitive; begin your visible answer immediately.`;

const CLASS_IDS = ["person", "door", "blockage", "gas", "fire"] as const;

const TOOLS: Anthropic.Beta.BetaTool[] = [
  {
    name: "search_mission",
    description:
      "Search the mission's documents: each finding (people, openings, blockages) with its route from the nearest open entrance, recent events, and notes on how Mayfly works. Use for 'how do I get to...', 'what happened with...', 'how does X work'.",
    input_schema: { type: "object", properties: { query: { type: "string" } }, required: ["query"], additionalProperties: false },
    strict: true,
  },
  {
    name: "set_detection_class",
    description:
      "Change how the drones search for one class of object: turn it on or off, set its minimum confidence (0.05 to 0.95), or set whether a finding is spoken to the crew immediately. Only include the fields that change.",
    input_schema: {
      type: "object",
      properties: {
        class_id: { type: "string", enum: [...CLASS_IDS], description: "person, door, blockage (blocked passage), gas (gas cylinder) or fire (fire and smoke)" },
        enabled: { type: "boolean" },
        min_confidence: { type: "number" },
        speak_immediately: { type: "boolean" },
      },
      required: ["class_id"],
      additionalProperties: false,
    },
    strict: true,
  },
  {
    name: "set_camera_vitals",
    description: "Turn the camera vitals estimate (breathing and pulse from a drone holding on a person) on or off.",
    input_schema: { type: "object", properties: { enabled: { type: "boolean" } }, required: ["enabled"], additionalProperties: false },
    strict: true,
  },
  {
    name: "set_review_threshold",
    description: "Set the confidence below which findings wait for the incident commander's review before reaching the crew.",
    input_schema: {
      type: "object",
      properties: { threshold: { type: "string", enum: reviewOptions } },
      required: ["threshold"],
      additionalProperties: false,
    },
    strict: true,
  },
  {
    name: "control_search",
    description: "Pause the whole search (every drone holds position) or resume it.",
    input_schema: { type: "object", properties: { action: { type: "string", enum: ["pause", "resume"] } }, required: ["action"], additionalProperties: false },
    strict: true,
  },
];

/** Run one tool call against the working copy of the settings; returns what to tell the model. */
async function runTool(
  name: string,
  input: Record<string, unknown>,
  work: { settings: DetectionSettings; changes: string[]; actions: MissionAction[]; docs: MissionDoc[] },
): Promise<string> {
  const s = work.settings;
  if (name === "search_mission") {
    const r = await searchMission(work.docs, String(input.query ?? ""));
    return JSON.stringify({ engine: r.via, results: r.hits.map((h) => ({ text: h.text, score: h.score })) });
  }
  if (name === "set_detection_class") {
    const c = s.classes.find((x) => x.id === input.class_id);
    if (!c) throw new Error(`unknown class ${String(input.class_id)}`);
    const next = { ...c };
    if (typeof input.enabled === "boolean") next.enabled = input.enabled;
    if (typeof input.min_confidence === "number") next.threshold = Math.round(Math.min(Math.max(input.min_confidence, 0.05), 0.95) * 100) / 100;
    if (typeof input.speak_immediately === "boolean") next.speak = input.speak_immediately;
    work.settings = { ...s, classes: s.classes.map((x) => (x.id === c.id ? next : x)) };
    const parts = [
      next.enabled !== c.enabled && (next.enabled ? "on" : "off"),
      next.threshold !== c.threshold && `minimum confidence ${next.threshold.toFixed(2)}`,
      next.speak !== c.speak && (next.speak ? "spoken immediately" : "spoken on request"),
    ].filter(Boolean);
    if (parts.length) work.changes.push(`${c.label}: ${parts.join(", ")}`);
    return JSON.stringify({ ok: true, class: next });
  }
  if (name === "set_camera_vitals") {
    work.settings = { ...s, vitals: input.enabled === true };
    work.changes.push(`Camera vitals ${input.enabled ? "on" : "off"}`);
    return JSON.stringify({ ok: true, vitals: work.settings.vitals });
  }
  if (name === "set_review_threshold") {
    const t = String(input.threshold);
    if (!reviewOptions.includes(t)) throw new Error(`threshold must be one of ${reviewOptions.join(", ")}`);
    work.settings = { ...s, review: t };
    work.changes.push(`Human review below ${t}`);
    return JSON.stringify({ ok: true, review: t });
  }
  if (name === "control_search") {
    const a = input.action === "pause" ? "pause" : "resume";
    work.actions.push(a);
    work.changes.push(a === "pause" ? "Search paused" : "Search resumed");
    return JSON.stringify({ ok: true, action: a });
  }
  throw new Error(`unknown tool ${name}`);
}

let client: Anthropic | null = null;

export async function ask(req: AgentRequest): Promise<Omit<AgentReply, "audio">> {
  client ??= new Anthropic();
  const work = { settings: req.settings, changes: [] as string[], actions: [] as MissionAction[], docs: req.docs ?? [] };
  const recent = req.history.length ? `<recent_conversation>\n${req.history.map((h) => `Crew: ${h.q}\nMayfly: ${h.a}`).join("\n")}\n</recent_conversation>\n\n` : "";
  const messages: Anthropic.Beta.BetaMessageParam[] = [
    {
      role: "user",
      content: `${recent}<console_state>\n${JSON.stringify({ detection: req.settings, ...(req.console as object) })}\n</console_state>\n\n${req.question}`,
    },
  ];

  for (let step = 0; step < MAX_STEPS; step++) {
    const res = await client.beta.messages.create({
      model: MODEL,
      max_tokens: 4096,
      system: [{ type: "text", text: SYSTEM, cache_control: { type: "ephemeral" } }],
      tools: TOOLS,
      messages,
      output_config: { effort: "low" },
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
    });
    if (res.stop_reason === "refusal") {
      return { question: req.question, reply: "I can't help with that one.", settings: work.settings, changes: work.changes, actions: work.actions };
    }
    const text = res.content.flatMap((b) => (b.type === "text" ? [b.text] : [])).join(" ").trim();
    const calls = res.content.filter((b): b is Anthropic.Beta.BetaToolUseBlock => b.type === "tool_use");
    if (res.stop_reason !== "tool_use" || !calls.length) {
      return { question: req.question, reply: text || "Done.", settings: work.settings, changes: work.changes, actions: work.actions };
    }
    messages.push({ role: "assistant", content: res.content });
    messages.push({
      role: "user",
      content: await Promise.all(
        calls.map(async (c): Promise<Anthropic.Beta.BetaToolResultBlockParam> => {
          try {
            return { type: "tool_result", tool_use_id: c.id, content: await runTool(c.name, c.input as Record<string, unknown>, work) };
          } catch (e) {
            return { type: "tool_result", tool_use_id: c.id, content: String((e as Error).message), is_error: true };
          }
        }),
      ),
    });
  }
  return {
    question: req.question,
    reply: work.changes.length ? `Done: ${work.changes.join("; ")}.` : "Sorry, I couldn't finish that.",
    settings: work.settings,
    changes: work.changes,
    actions: work.actions,
  };
}

// ---------------------------------------------------------------- ElevenLabs speech

export const hasElevenLabs = () => !!process.env.ELEVENLABS_API_KEY;

/** Speech to text with ElevenLabs Scribe. */
export async function transcribe(audio: Blob): Promise<string> {
  const form = new FormData();
  form.append("model_id", process.env.ELEVENLABS_STT_MODEL ?? "scribe_v1");
  form.append("file", audio, "question.webm");
  const r = await fetch(`${ELEVEN}/speech-to-text`, { method: "POST", headers: { "xi-api-key": process.env.ELEVENLABS_API_KEY! }, body: form });
  if (!r.ok) throw new Error(`ElevenLabs speech to text: ${r.status} ${await r.text()}`);
  return (((await r.json()) as { text?: string }).text ?? "").trim();
}

/** Text to speech with ElevenLabs; base64 MP3, or null if it fails (the browser then speaks the reply itself). */
export async function speak(text: string): Promise<string | null> {
  const voice = process.env.ELEVENLABS_VOICE_ID ?? "JBFqnCBsd6RMkjVDRZzb";
  try {
    const r = await fetch(`${ELEVEN}/text-to-speech/${voice}?output_format=mp3_44100_128`, {
      method: "POST",
      headers: { "xi-api-key": process.env.ELEVENLABS_API_KEY!, "content-type": "application/json" },
      body: JSON.stringify({ text, model_id: process.env.ELEVENLABS_TTS_MODEL ?? "eleven_flash_v2_5" }),
    });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return Buffer.from(await r.arrayBuffer()).toString("base64");
  } catch (e) {
    console.error("ElevenLabs text to speech failed:", e);
    return null;
  }
}
