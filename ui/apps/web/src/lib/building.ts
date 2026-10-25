/**
 * Building and lot context for an address. Every value carries where it came
 * from and how far to trust it, so the console never shows a guess as a fact.
 * See ui/docs/building-context.md.
 *
 * - verified: confirmed on site by a crew or the department
 * - record: read from an official or open dataset
 * - estimated: derived from other values (shown with a tilde)
 * - unknown: no public source. `request` says who to ask.
 */
export type Trust = "verified" | "record" | "estimated" | "unknown";

export interface Attribute {
  label: string;
  /** Display value with units. Absent when trust is unknown. */
  value?: string;
  trust: Trust;
  /** Dataset, method and date. For unknown values, who holds the data. */
  source: string;
}

export interface BuildingContext {
  street: string;
  use: string;
  /** Four height-like fields stay apart: never derive one from another. */
  floors: Attribute;
  footprint: Attribute;
  height: Attribute;
  year: Attribute;
  construction: Attribute;
  lot: Attribute;
  zoning: Attribute;
  /** Regulatory ceiling is not obstacle clearance. */
  ceiling: Attribute;
  /** Drawn on the Parcels layer, in map stage pixels. */
  parcel: string;
}

export const trustLabel: Record<Trust, string> = {
  verified: "Verified",
  record: "Record",
  estimated: "Estimate",
  unknown: "Unknown",
};

/** Text shown in place of a missing value. */
export const unknownText = "Not on file";

export function display(a: Attribute): string {
  if (a.trust === "unknown" || !a.value) return unknownText;
  return a.trust === "estimated" ? `~${a.value}` : a.value;
}

/** Mock record for the demo address. Sources mirror the Springfield pilot layers. */
export const elmStreet: BuildingContext = {
  street: "418 Elm St",
  use: "Single-family house",
  floors: { label: "Floors", value: "2", trust: "record", source: "Overture buildings, num_floors" },
  footprint: { label: "Footprint", value: "152 m²", trust: "record", source: "Microsoft Global ML footprint" },
  height: { label: "Height", value: "7 m", trust: "estimated", source: "2 floors × 3.0 m. No measured roof height." },
  year: { label: "Built", trust: "unknown", source: "Capital Township Assessor. No public record." },
  construction: { label: "Construction", trust: "unknown", source: "Fire department preplan or owner" },
  lot: { label: "Lot", value: "0.18 acre", trust: "record", source: "Sangamon County parcels, TOTACRES" },
  zoning: { label: "Zoning", value: "R-2", trust: "record", source: "Springfield PW_Zoning parcelZonesView" },
  ceiling: { label: "Regulatory ceiling", value: "400 ft AGL", trust: "record", source: "14 CFR 107.51. Airspace and TFRs may lower it." },
  parcel: "M 392 372 L 566 354 L 590 508 L 408 528 Z",
};
