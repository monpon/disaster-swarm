/**
 * Mana (mana.space) holds Mayfly's building research and keeps a log of every mission's building lookup.
 *
 * The research itself was done in a Mana chat and saved as the Mana document "Mayfly: Building & Lot Context". A Mana
 * API key (MANA_API_KEY) can read and write the owner's Mana workspace through Mana's external API, so the console:
 * - reads that document and returns the findings that apply to the chosen address, with their sources;
 * - pushes a log entry for the lookup into the "Mayfly missions" app in the same workspace (see ensureMissionsApp).
 * The key only reaches the workspace API; chat and search in Mana need a signed-in browser session.
 * Server only.
 */

const API = process.env.MANA_API_URL ?? "https://server-prod.mana.space/api";
const DOC = "file-system/documents/mayfly-context-research";
const APP = "file-system/apps/Mayfly";
export const MANA_DOC_TITLE = "Mayfly: Building & Lot Context";

export const hasMana = () => !!process.env.MANA_API_KEY;

async function call<T>(op: "read" | "write" | "push", body: Record<string, unknown>): Promise<T> {
  const r = await fetch(`${API}/external/${op}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.MANA_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(15_000),
  });
  if (!r.ok) throw new Error(`Mana ${op} ${body.path}: ${r.status} ${(await r.text()).slice(0, 200)}`);
  return (await r.json()) as T;
}

const read = async <T>(path: string) => (await call<{ data: T | null }>("read", { path })).data;

export interface Finding {
  label: string;
  text: string;
  /** Where the research says the fact comes from. */
  source: string;
}

export interface ManaResearch {
  address: string;
  findings: Finding[];
  doc: { title: string; status: string; updatedAt: number | null };
  /** Key of the entry written to the Mayfly missions app in Mana, or null if logging failed. */
  logged: string | null;
}

interface ResearchEntry {
  status?: string;
  regridSangamon?: { yearbuilt_pct?: number; zoning_pct?: number; owner_pct?: number; checked?: string; source?: string };
  femaService?: { url?: string; spatialQuery?: string };
  springfieldResearch?: string;
}

/** First sentence of the paragraph under a markdown heading, without bold markers. */
function lead(md: string | undefined, heading: string): string | null {
  if (!md) return null;
  const i = md.indexOf(heading);
  if (i < 0) return null;
  const para = md.slice(i + heading.length).trim().split(/\n\s*\n/)[0] ?? "";
  return para.replace(/\*\*/g, "").trim() || null;
}

/** The findings from the Mana research that apply to this address. Springfield, IL gets the verified pilot results. */
export function findingsFor(address: string, r: ResearchEntry): Finding[] {
  const out: Finding[] = [];
  const springfield = /springfield,?\s*il/i.test(address);
  if (springfield) {
    const verified = lead(r.springfieldResearch, "## Verified findings");
    if (verified) out.push({ label: "Springfield records", text: verified, source: "Sangamon County and City of Springfield ArcGIS REST, live-tested" });
    out.push({
      label: "Zoning",
      text: "City zoning is published separately from county zoning; use the city layer inside Springfield.",
      source: "Springfield PW_Zoning parcelZonesView (MapServer 0, 2, 7)",
    });
  }
  const regrid = r.regridSangamon;
  if (springfield && regrid?.yearbuilt_pct !== undefined) {
    out.push({
      label: "Year built",
      text: `No public year-built record. Regrid reports ${regrid.yearbuilt_pct}% year-built coverage in Sangamon County (zoning ${regrid.zoning_pct ?? "?"}%, owner ${regrid.owner_pct ?? "?"}%). Ask the assessor or a fire department preplan.`,
      source: `Regrid parcel schema coverage, checked ${regrid.checked ?? "2026-10-25"}`,
    });
  }
  if (springfield && r.femaService?.spatialQuery) {
    out.push({ label: "Occupancy class", text: `FEMA USA Structures can add occupancy, but: ${r.femaService.spatialQuery}`, source: "FEMA / ORNL USA Structures" });
  }
  if (!springfield) {
    out.push({
      label: "Local records",
      text: "The Mana research verified local parcel and zoning services for Springfield, IL only. Elsewhere, look up the county parcel and city zoning GIS before trusting lot or zoning values.",
      source: "Mana research brief, US coverage",
    });
    out.push({
      label: "Year built",
      text: "Usually not in any free public layer. Ask the assessor or a fire department preplan.",
      source: "Assessor CAMA records, fire department preplans",
    });
  }
  out.push({
    label: "Footprint and height",
    text: "Footprints come from Overture or Microsoft Global ML. Keep tagged height, floors and modelled height apart; never merge them into one safe altitude.",
    source: "Overture buildings, Microsoft Global ML footprints, OSM",
  });
  return out;
}

export async function researchAddress(address: string, missionType?: string): Promise<ManaResearch> {
  const [research, meta] = await Promise.all([read<ResearchEntry>(`${DOC}/report/research`), read<{ updatedAt?: number }>(`${DOC}/report/metadata`)]);
  if (!research) throw new Error(`Mana document "${MANA_DOC_TITLE}" not found`);
  const findings = findingsFor(address, research);
  let logged: string | null = null;
  try {
    await ensureMissionsApp();
    logged = (
      await call<{ key: string }>("push", {
        path: `${APP}/missions-log/entries`,
        value: { address, missionType: missionType ?? null, at: Date.now(), findings: findings.map((f) => `${f.label}: ${f.text}`), from: "Mayfly console" },
      })
    ).key;
  } catch (e) {
    console.error("Mana log:", e);
  }
  return { address, findings, doc: { title: MANA_DOC_TITLE, status: research.status ?? "", updatedAt: meta?.updatedAt ?? null }, logged };
}

/** A small Mana app that lists the console's building lookups, newest first. Written once, then left alone. */
const APP_CODE = `function UserDiv(){
 const {tc}=useTheme(); const [rows,setRows]=React.useState(null);
 React.useEffect(()=>FS.onValue(FS.ref(FS.db,relPathAddress('entries')),s=>{const v=s.val()||{};setRows(Object.entries(v).map(([k,e])=>({k,...e})).sort((a,b)=>b.at-a.at));}),[]);
 return <div className={'w-full py-6 '+tc.text}>
  <div className={'text-xs uppercase tracking-widest '+tc.textMuted}>Mayfly / Mission log</div>
  <h1 className="text-3xl mt-3 font-semibold tracking-tight">Building lookups from the console</h1>
  <p className={'mt-2 text-sm '+tc.textMuted}>Each time a crew researches an address in Mayfly, the findings from "Mayfly: Building & Lot Context" are logged here.</p>
  {!rows?<p className={'mt-6 '+tc.textMuted}>Loading…</p>:rows.length===0?<p className={'mt-6 '+tc.textMuted}>No lookups yet.</p>:
  <ul className="mt-6 flex flex-col gap-4">{rows.map(r=><li key={r.k} className={'rounded-xl border p-4 '+tc.border}>
   <div className="flex items-baseline justify-between gap-3"><span className="font-semibold">{r.address}</span><span className={'text-xs '+tc.textMuted}>{new Date(r.at).toLocaleString()}</span></div>
   {r.missionType&&<div className={'text-xs mt-1 '+tc.textMuted}>{r.missionType}</div>}
   <ul className="mt-3 flex flex-col gap-1.5 text-sm">{(r.findings||[]).map((f,i)=><li key={i}>{f}</li>)}</ul>
  </li>)}</ul>}
 </div>;
}`;

let appReady: Promise<void> | null = null;
function ensureMissionsApp() {
  appReady ??= (async () => {
    const existing = await read<string>(`${APP}/missions-log/code`);
    if (existing) return;
    await call("write", { path: `${APP}/metadata`, value: { displayName: "Mayfly missions", type: "link" } });
    await call("write", { path: `${APP}/missions-log/metadata`, value: { type: "user_div" } });
    await call("write", { path: `${APP}/missions-log/code`, value: APP_CODE });
  })().catch((e) => {
    appReady = null;
    throw e;
  });
  return appReady;
}
