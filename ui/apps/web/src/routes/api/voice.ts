import Anthropic from "@anthropic-ai/sdk";
import { createFileRoute } from "@tanstack/react-router";

import { hasMoss } from "@/server/mission-search";
import { ask, hasElevenLabs, speak, transcribe, type AgentRequest } from "@/server/voice-agent";

/**
 * The voice agent's endpoint. GET says whether ElevenLabs speech is set up. POST takes a multipart form: `audio` (a
 * recording, needs ElevenLabs) or `question` (text), and `context` (JSON: settings, console, history).
 */
export const Route = createFileRoute("/api/voice")({
  server: {
    handlers: {
      GET: () => Response.json({ elevenlabs: hasElevenLabs(), moss: hasMoss() }),
      POST: async ({ request }) => {
        try {
          const form = await request.formData();
          // A proactive alert: the console already wrote the words, so no model is involved, only the voice.
          const announce = String(form.get("announce") ?? "").trim();
          if (announce) return Response.json({ audio: hasElevenLabs() ? await speak(announce.slice(0, 600)) : null });
          const context = JSON.parse(String(form.get("context") ?? "{}")) as Omit<AgentRequest, "question">;
          const audio = form.get("audio");
          let question = String(form.get("question") ?? "").trim();
          if (audio instanceof Blob && audio.size > 0) {
            if (!hasElevenLabs()) return Response.json({ error: "Voice input needs ELEVENLABS_API_KEY on the server." }, { status: 503 });
            question = await transcribe(audio);
          }
          if (!question) return Response.json({ error: "Didn't catch that." }, { status: 400 });
          const reply = await ask({ ...context, question, history: (context.history ?? []).slice(-6) });
          const sound = hasElevenLabs() && form.get("speak") !== "0" ? await speak(reply.reply) : null;
          return Response.json({ ...reply, audio: sound });
        } catch (e) {
          console.error("voice agent:", e);
          const status = e instanceof Anthropic.RateLimitError ? 429 : e instanceof Anthropic.AuthenticationError || /authentication method/.test(String(e)) ? 401 : 500;
          return Response.json({ error: status === 401 ? "The voice agent has no Anthropic credentials." : "The voice agent hit an error." }, { status });
        }
      },
    },
  },
});
