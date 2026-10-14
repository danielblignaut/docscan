// The JSON shapes docscan returns (see docscan/src/lib.rs).

export type DocumentKind =
  | "za_smart_id_front"
  | "za_smart_id_back"
  | "za_green_book"
  | "za_passport"
  | "gb_passport"
  | "other_passport"
  | "other_id_card"
  | "unknown";

export interface Quality {
  sharpness: number;
  glare: number;
  brightness: number;
  edge_density: number;
}

export interface Barcode {
  format: string;
  text: string;
  bytes: number[];
  points: [number, number][];
}

export interface IdNumber {
  value: string;
  date_of_birth: string;
  sex: string;
  citizenship: string;
  luhn_valid: boolean;
  date_valid: boolean;
}

export interface Mrz {
  format: "TD3" | "TD1";
  document_code: string;
  issuing_state: string;
  surname: string;
  given_names: string;
  document_number: string;
  nationality: string;
  date_of_birth: string;
  sex: string;
  date_of_expiry: string;
  optional_data: string;
  checks: Record<string, boolean>;
  lines: string[];
}

export interface SmartIdBarcode {
  surname: string;
  names: string;
  sex: string;
  nationality: string;
  id_number: IdNumber;
  date_of_birth: string;
  country_of_birth: string;
  status: string;
  fields: string[];
}

export interface PrintedFields {
  surname?: string | null;
  names?: string | null;
  sex?: string | null;
  nationality?: string | null;
  date_of_birth?: string | null;
  country_of_birth?: string | null;
  status?: string | null;
  id_number?: IdNumber | null;
}

export interface Line {
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface DocumentResult {
  kind: DocumentKind;
  accepted: boolean;
  reasons: string[];
  quality: Quality;
  barcodes: Barcode[];
  mrz: Mrz | null;
  smart_id_barcode: SmartIdBarcode | null;
  id_barcode: IdNumber | null;
  printed: PrintedFields | null;
  lines: Line[];
  mrz_lines: string[];
  skew: number;
  quarter_turns: number;
  ocr_passes: number;
  document: { corners: [number, number][]; support: number } | null;
  analysed_size: [number, number];
  timings_ms: { quality: number; barcodes: number; ocr: number; total: number };
}

/** A stable identity for a reading, so two frames can be compared. */
export function readingKey(r: DocumentResult): string | null {
  if (!r.accepted) return null;
  if (r.smart_id_barcode) return `back:${r.smart_id_barcode.id_number.value}`;
  if (r.mrz) return `mrz:${r.mrz.lines.join("")}`;
  if (r.printed?.id_number) return `${r.kind}:${r.printed.id_number.value}:${r.printed.surname ?? ""}:${r.printed.names ?? ""}`;
  return null;
}

/** For a smart ID front and back captured together: do both sides carry the same identity number? */
export function crossCheck(captured: { result: DocumentResult }[]): { front: string | null; back: string | null; match: boolean } | null {
  const front = captured.find((c) => c.result.kind === "za_smart_id_front");
  const back = captured.find((c) => c.result.kind === "za_smart_id_back");
  if (!front || !back) return null;
  const f = front.result.printed?.id_number?.value ?? null;
  const b = back.result.smart_id_barcode?.id_number.value ?? back.result.id_barcode?.value ?? null;
  return { front: f, back: b, match: f !== null && f === b };
}
