import { Button } from "@swarm/ui/components/button";
import { cn } from "@swarm/ui/lib/utils";
import { createFileRoute, Link } from "@tanstack/react-router";
import { AlertCircle, ArrowRight, Check, ChevronRight, MapPin, Minus, Plus, Search, Truck } from "lucide-react";
import { useMemo, useState } from "react";

import { AttributeRow, TrustLegend } from "@/components/building/trust";
import { Mark } from "@/components/icons";
import { Stage } from "@/components/map/stage";
import { elmStreet } from "@/lib/building";
import { addressResults, missionTypes, recentMissions } from "@/lib/mock";
import { requireUser } from "@/lib/session";

export const Route = createFileRoute("/missions/new")({
  beforeLoad: ({ location }) => requireUser(location.href),
  head: () => ({ meta: [{ title: "New mission" }] }),
  component: NewMissionPage,
});

const layers = ["Map", "Satellite", "Parcels"] as const;

function NewMissionPage() {
  const [query, setQuery] = useState("12 Example");
  const [picked, setPicked] = useState("a1");
  const [type, setType] = useState<(typeof missionTypes)[number]>("Structural collapse");
  const [layer, setLayer] = useState<(typeof layers)[number]>("Map");
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? addressResults.filter((r) => `${r.street} ${r.city}`.toLowerCase().includes(q)) : addressResults;
  }, [query]);
  const chosen = addressResults.find((r) => r.id === picked);

  return (
    <div className="flex h-svh flex-col overflow-hidden">
      <header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-line bg-white px-3">
        <Link to="/" aria-label="Home">
          <Mark />
        </Link>
        <nav className="flex items-center gap-2 text-sm">
          <span className="font-medium text-muted">Missions</span>
          <ChevronRight className="size-3 text-faint" />
          <span className="font-semibold">New mission</span>
        </nav>
        <div className="flex-1" />
        <span className="flex h-7 items-center gap-1.5 rounded-full bg-[#eef8f1] px-2.5 text-xs font-medium text-[#166534]">
          <span className="size-1.5 rounded-full bg-ok" />
          Edge server online
        </span>
        <span className="flex size-[30px] items-center justify-center rounded-full bg-[#e7e7e4] text-xs font-semibold">JR</span>
      </header>
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[440px] shrink-0 flex-col border-r border-line-strong bg-white">
          <div className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto px-5 py-[22px]">
            <div className="flex flex-col gap-1">
              <h1 className="text-[22px] font-semibold tracking-[-0.01em]">New mission</h1>
              <p className="text-[13px] text-muted">Find the building. Floor plan and records load automatically.</p>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="address" className="text-[13px] font-semibold">
                Address
              </label>
              <div className="flex h-[42px] items-center gap-2 rounded-lg bg-white px-3 shadow-[0_0_0_1.5px_var(--color-orange),0_0_0_4px_rgb(255_90_31/0.15)]">
                <Search className="size-4 text-muted" />
                <input
                  id="address"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  autoComplete="off"
                  className="min-w-0 flex-1 text-sm outline-none"
                />
                <span className="rounded bg-panel px-1.5 py-0.5 text-[11px] text-muted shadow-[inset_0_0_0_1px_var(--color-line)]">Use CAD</span>
              </div>
              <ul className="flex flex-col overflow-hidden rounded-lg bg-white shadow-[0_0_0_1px_var(--color-line),0_8px_20px_rgb(0_0_0/0.08)]">
                {results.length === 0 && <li className="px-3 py-3 text-[13px] text-muted">No matches. Try the street name only.</li>}
                {results.map((r, i) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setPicked(r.id)}
                      className={cn(
                        "flex w-full items-center gap-2.5 px-3 py-2.5 text-left",
                        i > 0 && "border-t border-line-soft",
                        r.id === picked ? "bg-orange-tint" : "hover:bg-panel-2",
                      )}
                    >
                      <MapPin className={cn("size-4", r.id === picked ? "fill-orange text-orange" : "text-faint")} />
                      <span className="flex flex-1 flex-col gap-px">
                        <span className={cn("text-sm", r.id === picked ? "font-semibold" : "font-medium")}>{r.street}</span>
                        <span className="text-xs text-muted">{r.city}</span>
                      </span>
                      <span className="text-xs text-muted">{r.distance}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div className="flex flex-col gap-2">
              <span className="text-[13px] font-semibold">Mission type</span>
              <div className="flex flex-wrap gap-1.5">
                {missionTypes.map((t) => (
                  <button
                    key={t}
                    type="button"
                    aria-pressed={t === type}
                    onClick={() => setType(t)}
                    className={cn(
                      "h-8 rounded-full px-3 text-[13px] font-medium",
                      t === type ? "bg-ink text-white" : "shadow-[inset_0_0_0_1px_var(--color-line-strong)] hover:bg-panel",
                    )}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <div className="flex items-baseline">
                <span className="flex-1 text-[13px] font-semibold">Recent missions</span>
                <span className="text-xs font-medium text-orange-edge">View all</span>
              </div>
              <ul className="flex flex-col">
                {recentMissions.map((r, i) => (
                  <li key={r.id} className={cn("flex items-center gap-2.5 py-2", i < recentMissions.length - 1 && "border-b border-line-soft")}>
                    <span className="flex flex-1 flex-col gap-px">
                      <span className="text-[13px] font-medium">{r.place}</span>
                      <span className="text-xs text-muted">{r.meta}</span>
                    </span>
                    <span className="text-xs text-muted">Closed</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <div className="flex shrink-0 gap-2 border-t border-line-strong bg-panel px-5 pt-3.5 pb-4">
            <Button size="lg" render={<Link to="/" />} nativeButton={false}>
              Cancel
            </Button>
            <Button variant="primary" size="lg" className="flex-1" disabled={!chosen} render={<Link to="/setup" />} nativeButton={false}>
              Continue to setup
              <ArrowRight />
            </Button>
          </div>
        </aside>
        <div className="relative min-w-0 flex-1 bg-[#f0f0ee]">
          <Stage width={968} height={848} fit="cover">
            <img src="/assets/streets.png" alt="Street map around the selected building" width={968} height={848} className="absolute inset-0" draggable={false} />
            <span className="absolute text-[11px] font-semibold tracking-[0.04em] text-[#b0784a]" style={{ left: 518, top: 8 }}>
              S 5TH ST
            </span>
            {chosen && layer === "Parcels" && (
              <svg width={968} height={848} className="absolute inset-0" aria-hidden>
                <path d={elmStreet.parcel} fill="rgb(255 90 31 / 0.12)" stroke="var(--color-orange)" strokeWidth={2} strokeDasharray="6 4" />
              </svg>
            )}
            {chosen && (
              <>
                <svg width={28} height={36} viewBox="0 0 28 36" className="absolute" style={{ left: 425, top: 384 }} aria-hidden>
                  <path d="M14 1C6.8 1 1 6.8 1 14c0 9.5 13 21 13 21s13-11.5 13-21C27 6.8 21.2 1 14 1Z" fill="var(--color-orange)" stroke="#fff" strokeWidth={2} />
                  <circle cx={14} cy={14} r={5} fill="#fff" />
                </svg>
                <BuildingCard street={chosen.street} showZoning={layer === "Parcels"} />
              </>
            )}
            <span
              className="absolute flex h-[26px] items-center gap-1.5 rounded-full bg-ink pr-2.5 pl-1 text-xs font-semibold text-white shadow-[0_2px_6px_rgb(0_0_0/0.25)]"
              style={{ left: 250, top: 560 }}
            >
              <span className="flex size-[18px] items-center justify-center rounded-full bg-person">
                <Truck className="size-2.5" />
              </span>
              Engine 7, 3 min out
            </span>
          </Stage>
          <div className="absolute top-3 left-3 flex gap-0.5 rounded-lg bg-white p-[3px] shadow-[0_0_0_1px_var(--color-line-strong),0_1px_2px_rgb(0_0_0/0.08)]">
            {layers.map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={m === layer}
                onClick={() => setLayer(m)}
                className={cn("flex h-[26px] items-center rounded-[5px] px-2.5 text-xs", m === layer ? "bg-ink font-semibold text-white" : "font-medium text-muted hover:bg-panel")}
              >
                {m}
              </button>
            ))}
          </div>
          <div className="btn-secondary absolute right-3 bottom-3 flex flex-col overflow-hidden rounded-lg">
            <button type="button" aria-label="Zoom in" className="flex size-8 items-center justify-center border-b border-line">
              <Plus className="size-3.5" />
            </button>
            <button type="button" aria-label="Zoom out" className="flex size-8 items-center justify-center">
              <Minus className="size-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function BuildingCard({ street, showZoning }: { street: string; showZoning: boolean }) {
  const b = elmStreet;
  return (
    <div className="absolute flex w-[290px] flex-col overflow-hidden rounded-[10px] bg-white shadow-[0_0_0_1px_var(--color-line),0_10px_28px_rgb(0_0_0/0.14)]" style={{ left: 510, top: 290 }}>
      <div className="flex flex-col gap-0.5 px-3.5 pt-3 pb-2.5">
        <span className="text-[15px] font-semibold">{street}</span>
        <span className="flex items-center gap-1.5 text-xs text-muted">
          {b.use}
          {showZoning && <span className="rounded bg-panel px-1.5 py-px font-mono text-[11px] text-ink shadow-[inset_0_0_0_1px_var(--color-line)]">Zoned {b.zoning.value}</span>}
        </span>
      </div>
      <dl className="flex flex-col border-t border-line-soft px-3.5 py-1.5">
        {[b.floors, b.footprint, b.height, b.lot, b.year, b.construction].map((a) => (
          <AttributeRow key={a.label} a={a} />
        ))}
      </dl>
      <div className="flex flex-col gap-2 border-t border-line-soft px-3.5 pt-2.5 pb-3 text-xs">
        <p className="flex items-center gap-2">
          <AlertCircle className="size-3.5 shrink-0 text-hazard" strokeWidth={2.5} />
          Gas service on site
        </p>
        <p className="flex items-center gap-2 text-muted">
          <Check className="size-3.5 shrink-0 text-ok" strokeWidth={2.5} />
          Crew picks the building if several match
        </p>
        <TrustLegend />
      </div>
    </div>
  );
}
