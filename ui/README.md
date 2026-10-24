# Swarm console (UI)

Web console for the disaster swarm: incident setup, the live 3D map with drone feeds and findings, fleet configuration, settings, and a landing page. Built from the "v2 — orange" Paper designs.

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
| `/incidents/new` | New incident: address search and incident type |
| `/setup` | Mission setup: floor plan, geofence, drones, search settings |
| `/live` | Live console: point cloud map, feeds, findings, crew channel |
| `/fleet` | Drone list and per-drone configuration |
| `/settings/detection` | Detection classes, thresholds, vitals, review |
| `/settings/edge` | Edge server health and services |

## Rendered assets

The point cloud, floor plan, street map and camera frames in `apps/web/public/assets` are generated, not photographs. Regenerate them with the scripts in `apps/web/scripts/render-assets` (Python 3, Pillow, NumPy):

```sh
cd apps/web/scripts/render-assets
python3 gen2.py ../../public/assets      # cloud.png, f1-f4.png
python3 plan.py ../../public/assets      # plan.png
python3 streets.py ../../public/assets   # streets.png
python3 story.py ../../public/assets     # story-points.bin, story.json (landing page)
python3 people.py ../../public/assets    # person-*.png (vitals section)
```

`story.py` simulates two searches of the same house along hand-drawn flight paths, four drones splitting the rooms and one drone visiting every room in turn, and records when each point of the cloud is first seen. The landing page draws the cloud on a canvas and scrubs that timeline with scroll. It is an illustration of the idea, not a measured result, and the page labels it that way.

Map overlays (drones, pins, labels) are positioned in the pixel space of these images, so re-rendering with different projection parameters means updating the coordinates in `mock.ts` and the map components.
