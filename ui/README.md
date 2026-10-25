# Mayfly console (UI)

Web console for Mayfly, the search-and-rescue drone swarm: mission setup, the live 3D map with drone feeds and findings, fleet configuration, settings, and a landing page. Built from the "v2 — orange" Paper designs.

Data is mocked in `apps/web/src/lib/mock.ts` until the console is wired to the edge server.

## Stack

Same shape as [yinzone](https://github.com/matmanna/yinzone), minus the database, auth and RPC layers:

- Bun workspaces + Turborepo
- TanStack Start (React 19, file-based routing, SSR) on Vite, Nitro for the server build
- Tailwind CSS v4, shadcn-style primitives in `packages/ui` (Base UI button, `react-resizable-panels`)
- lucide icons, IBM Plex Sans / Mono

## Run

```sh
cd ui
bun install
bun run dev:web        # http://localhost:3001
bun run check-types
```

## Routes

| Path | Screen |
| --- | --- |
| `/` | Landing page: scroll story (one drone vs. the swarm, shared map, split screen) |
| `/missions/new` | New mission: address search and mission type |
| `/setup` | Mission setup: floor plan, geofence, drones, search settings |
| `/live` | Live console: point cloud map, feeds, findings, crew channel |
| `/fleet` | Drone list and per-drone configuration |
| `/settings/detection` | Detection classes, thresholds, vitals, review |
| `/settings/edge` | Edge server health and services |

## Voice agent

Push-to-talk and the text box in the crew channel (`/live`) ask Mayfly's voice agent. Gemini (default when `GEMINI_API_KEY` is set) or Claude (`claude-opus-5-5`) answers and acts through the same tools; Moss retrieves what the mission knows; ElevenLabs speaks.

- **Questions:** findings, drones, how Mayfly works, and "how do I get to them?". Routes come from A* over the live floor plan (`src/lib/routing.ts`: 1 m cells, walls and blocked openings avoided, unmapped stretches cost more and are called out). They run from the nearest open entrance on the survivor's floor; stairs are not on the map, so there are no cross-floor routes yet.
- **Changes:** detection classes (on/off, minimum confidence, speak immediately), camera vitals, the review threshold, pause and resume. These land in the same settings as `/settings/detection` and, with the simulator live, reach it as a `detection` command (the simulator acts on the person row).
- **Proactive:** the bell in the channel header turns on voice alerts. New survivors (with their route) and blocked openings are spoken as they appear if their class is set to speak immediately. Alerts skip Claude: the console writes the sentence, ElevenLabs says it.
- **Retrieval:** the console sends one short document per finding (with its route) and per recent event; the server upserts them into a Moss index with Mayfly's reference notes, and Claude's `search_mission` tool queries it. Without Moss credentials a keyword match over the same documents answers instead.

Server: `src/server/voice-agent.ts` and `src/server/mission-search.ts` behind `POST /api/voice`. Environment (copy `apps/web/.env.example` to `apps/web/.env`, which is gitignored):

| Variable | Needed for |
|---|---|
| `GEMINI_API_KEY`, `GEMINI_MODEL` (`gemini-3.6-flash`) | the agent, by default |
| `ANTHROPIC_API_KEY` | the agent through Claude, when there is no Gemini key or `LLM_PROVIDER=claude` |
| `ELEVENLABS_API_KEY` | ElevenLabs speech to text and voice; without it the browser's own speech stands in. Optional: `ELEVENLABS_VOICE_ID`, `ELEVENLABS_TTS_MODEL` (`eleven_flash_v2_5`), `ELEVENLABS_STT_MODEL` (`scribe_v1`) |
| `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY` | Moss search. Optional: `MOSS_INDEX` (`mayfly-mission`) |

Tests: `bun test` in `apps/web`.

## Rendered assets

The point cloud, floor plan, street map and camera frames in `apps/web/public/assets` are generated, not photographs. Regenerate them with the scripts in `apps/web/scripts/render-assets` (Python 3, Pillow, NumPy):

```sh
cd apps/web/scripts/render-assets
python3 gen2.py ../../public/assets      # cloud.png, f1-f4.png
python3 plan.py ../../public/assets      # plan.png
python3 streets.py ../../public/assets   # streets.png
python3 story.py ../../public/assets     # story-points.bin, story.json (landing page)
```

`story.py` simulates two searches of the same house along hand-drawn flight paths, four drones splitting the rooms and one drone visiting every room in turn, and records when each point of the cloud is first seen. The landing page draws the cloud on a canvas and scrubs that timeline with scroll. It is an illustration of the idea, not a measured result, and the page labels it that way.

Map overlays (drones, pins, labels) are positioned in the pixel space of these images, so re-rendering with different projection parameters means updating the coordinates in `mock.ts` and the map components.
