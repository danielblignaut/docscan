// The results screen: what was captured, as a read-only form (one labelled
// input per value, each with a copy button), grouped per side or step, with
// the captured images, a collapsible Metadata section and, for proof of
// address, the page's OCR text.
import { type ReactNode, useState } from "react";
import type { FaceClient } from "./face-client";
import { DOC_THRESHOLD, FACE_DOWNLOAD_MB, FACE_LICENCES, RECOGNISER } from "./face-models";
import { saveEnrolment } from "./face-store";
import type { FaceQuality, PhotoFace } from "./face-types";
import { crossCheck } from "./IdCapture";
import { catalogueEntry } from "./models";
import type { CaptureMeta, Outcome, ReadyInfo } from "./outcome";
import { scannerById } from "./scanners";
import type { AddressResult, CopyAssessment, DocumentResult, LabelledField } from "./types";
import type { CountCheck, FileEvidence } from "./document-files/types";
import type { DocumentEvidence, InputReference } from "./document-review";
import { documentReportJson, sourceLabel } from "./document-report";

type Status = "ok" | "warn" | "bad";

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="copy"
      aria-label="Copy"
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(
          () => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          },
          () => {},
        );
      }}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/** One read-only value: label, input, copy button, and a status under it. */
function Field({ label, value, status, note, name }: { label: string; value: string | number | null | undefined; status?: Status; note?: string; name?: string }) {
  const v = value === null || value === undefined || value === "" ? "" : String(value);
  return (
    <label className="field" data-field={name}>
      <span className="field-label">{label}</span>
      <span className="field-row">
        <input readOnly value={v} placeholder="not found" onFocus={(e) => e.currentTarget.select()} />
        {v ? <CopyButton value={v} /> : null}
      </span>
      {note ? (
        <span className={`field-note ${status ?? ""}`} data-status={status}>
          {note}
        </span>
      ) : null}
    </label>
  );
}

function Group({ title, children, testid }: { title: string; children: ReactNode; testid?: string }) {
  return (
    <fieldset className="group" data-testid={testid}>
      <legend>{title}</legend>
      {children}
    </fieldset>
  );
}

function Verdict({ ok, children, testid }: { ok: boolean; children: ReactNode; testid?: string }) {
  return (
    <p className={`verdict ${ok ? "ok" : "bad"}`} data-testid={testid}>
      {children}
    </p>
  );
}

/** A key–value table, for the metadata (not meant to be copied field by field). */
function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="facts">
      {rows
        .filter(([, v]) => v !== null && v !== undefined && v !== "")
        .map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
    </dl>
  );
}

const ms = (x: number | null | undefined) => (x === null || x === undefined ? null : `${Math.round(x)} ms`);
const secs = (x: number) => `${(x / 1000).toFixed(1)} s`;
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
const human = (s: string) => s.replaceAll("_", " ");

function backend(ready: ReadyInfo | null): string {
  if (!ready) return "loading";
  return ready.threads > 1 ? `WebAssembly, multithreaded (${ready.threads} threads)` : "WebAssembly, single-threaded";
}

function captureFacts(meta: CaptureMeta, ready: ReadyInfo | null): [string, ReactNode][] {
  return [
    ["Source", meta.source === "camera" ? "camera, hands-free" : meta.source === "pdf" ? "rendered PDF page" : "uploaded photo"],
    ["Time to capture", meta.source === "camera" ? secs(meta.captureMs) : null],
    ["Time to read", meta.source !== "camera" ? secs(meta.captureMs) : null],
    ["Frames analysed", meta.frames],
    ["OCR passes", meta.ocrFrames],
    ["Median fast pass", ms(meta.fastMs)],
    ["Median OCR pass", ms(meta.ocrMs)],
    ["Backend", backend(ready)],
    ["Wasm allocated memory", meta.memoryBytes ? `${Math.round(meta.memoryBytes / 1048576)} MB (not total browser RAM)` : null],
    ["Scanner loaded in", ready ? ms(ready.loadMs) : null],
  ];
}

// ---------------------------------------------------------------------------
// Identity documents
// ---------------------------------------------------------------------------

function luhn(ok: boolean | undefined): [Status, string] {
  return ok ? ["ok", "Luhn check digit valid"] : ["bad", "Luhn check digit FAILS"];
}

function DocumentFields({ result }: { result: DocumentResult }) {
  const p = result.printed;
  const m = result.mrz;
  const b = result.smart_id_barcode;
  const check = (k: string): [Status, string] | [] => (m ? (m.checks[k] ? ["ok", "check digit ✓"] : ["bad", "check digit ✗"]) : []);
  return (
    <>
      {p && (
        <Group title="Printed on the document">
          <Field label="Surname" value={p.surname} name="printed.surname" />
          <Field label="Names" value={p.names} name="printed.names" />
          {p.id_number ? (
            <Field
              label="Identity number"
              value={p.id_number.value}
              name="printed.id_number"
              status={luhn(p.id_number.luhn_valid)[0]}
              note={`${luhn(p.id_number.luhn_valid)[1]} · ${p.id_number.sex} · ${p.id_number.citizenship}${p.id_number.date_valid ? "" : " · date invalid"}`}
            />
          ) : (
            <Field label="Identity number" value={null} />
          )}
          <Field label="Date of birth" value={p.date_of_birth} />
          <Field label="Sex" value={p.sex} />
          <Field label="Nationality" value={p.nationality} />
          <Field label="Country of birth" value={p.country_of_birth} />
          <Field label="Status" value={p.status} />
        </Group>
      )}
      {m && (
        <Group title={`Machine-readable zone (${m.format})`} testid="mrz">
          <Verdict ok={Object.values(m.checks).every(Boolean)}>
            {Object.values(m.checks).every(Boolean)
              ? "Every MRZ check digit passes"
              : `Failing: ${Object.entries(m.checks)
                  .filter(([, v]) => !v)
                  .map(([k]) => human(k))
                  .join(", ")}`}
          </Verdict>
          <Field label="Document code" value={m.document_code} />
          <Field label="Issuing state" value={m.issuing_state} />
          <Field label="Surname" value={m.surname} name="mrz.surname" />
          <Field label="Given names" value={m.given_names} name="mrz.given_names" />
          <Field label="Document number" value={m.document_number} name="mrz.document_number" status={check("document_number")[0]} note={check("document_number")[1]} />
          <Field label="Nationality" value={m.nationality} />
          <Field label="Date of birth" value={m.date_of_birth} status={check("date_of_birth")[0]} note={check("date_of_birth")[1]} />
          <Field label="Sex" value={m.sex} />
          <Field label="Date of expiry" value={m.date_of_expiry} status={check("date_of_expiry")[0]} note={check("date_of_expiry")[1]} />
          <Field label="Optional data" value={m.optional_data} status={m.optional_data ? check("optional_data")[0] : undefined} note={m.optional_data ? check("optional_data")[1] : undefined} />
          <Field label="Composite" value={m.checks.composite ? "valid" : "invalid"} status={check("composite")[0]} note={check("composite")[1]} />
          <details className="sub">
            <summary>MRZ lines</summary>
            <pre>{m.lines.join("\n")}</pre>
          </details>
        </Group>
      )}
      {b && (
        <Group title="Smart ID barcode (PDF417)" testid="smart-id-barcode">
          <Field label="Surname" value={b.surname} name="smart_id_barcode.surname" />
          <Field label="Names" value={b.names} />
          <Field label="Identity number" value={b.id_number.value} name="smart_id_barcode.id_number" status={luhn(b.id_number.luhn_valid)[0]} note={luhn(b.id_number.luhn_valid)[1]} />
          <Field label="Date of birth" value={b.date_of_birth} />
          <Field label="Sex" value={b.sex} />
          <Field label="Nationality" value={b.nationality} />
          <Field label="Country of birth" value={b.country_of_birth} />
          <Field label="Status" value={b.status} />
        </Group>
      )}
      {!b && result.id_barcode && (
        <Group title="Identity number barcode (Code 39)">
          <Field
            label="Identity number"
            value={result.id_barcode.value}
            status={luhn(result.id_barcode.luhn_valid)[0]}
            note={`${luhn(result.id_barcode.luhn_valid)[1]} · the PDF417 did not read, so only the number is known`}
          />
        </Group>
      )}
      {result.barcodes.length > 0 && (
        <Group title="Barcodes on the document">
          {result.barcodes.map((code, i) => (
            <Field key={`${code.format}${i}`} label={code.format.toUpperCase()} value={code.text} />
          ))}
        </Group>
      )}
    </>
  );
}

function documentFacts(r: DocumentResult, step: { stepMs?: number; frames?: number; fallback?: boolean }): [string, ReactNode][] {
  return [
    ["Document kind", human(r.kind)],
    ["Accepted", r.accepted ? "yes" : "no"],
    ["Reasons", r.reasons.join("; ") || "—"],
    ["Read from", step.fallback ? "the Code 39 alone (fallback)" : null],
    ["Sharpness", r.quality.sharpness.toFixed(0)],
    ["Glare", pct(r.quality.glare)],
    ["Brightness", r.quality.brightness.toFixed(0)],
    ["Outline support", r.document ? pct(r.document.support) : "no outline"],
    ["Analysed size", `${r.analysed_size[0]} × ${r.analysed_size[1]}`],
    ["Quarter turns · skew", `${r.quarter_turns} · ${r.skew.toFixed(1)}°`],
    ["OCR passes", r.ocr_passes],
    ["Quality stage", ms(r.timings_ms.quality)],
    ["Barcodes stage", ms(r.timings_ms.barcodes)],
    ["OCR stage", ms(r.timings_ms.ocr)],
    ["Total (this frame)", ms(r.timings_ms.total)],
    ["Time on this step", step.stepMs !== undefined ? secs(step.stepMs) : null],
    ["Frames on this step", step.frames],
  ];
}

function IdResults({ outcome, ready }: { outcome: Extract<Outcome, { kind: "id" }>; ready: ReadyInfo | null }) {
  const check = crossCheck(outcome.captured);
  return (
    <>
      {check && (
        <Verdict ok={check.match} testid="crosscheck">
          {check.match
            ? `Front and back agree: identity number ${check.front}`
            : `Mismatch: the front reads ${check.front ?? "no number"}, the back's barcode ${check.back ?? "no number"}`}
        </Verdict>
      )}
      {outcome.captured.map((c, i) => (
        <section className="step" key={`${c.step}${i}`} data-testid="captured-step">
          <h2>{c.step}</h2>
          <Verdict ok={c.result.accepted}>
            {human(c.result.kind)} · {c.result.accepted ? "accepted" : `not accepted: ${c.result.reasons.join("; ")}`}
          </Verdict>
          <img className="captured" src={c.imageUrl} alt={c.step} />
          <InputSource input={c.input} />
          <CopyEvidence assessment={c.result.copy_assessment} />
          <DocumentFields result={c.result} />
          <details className="sub">
            <summary>OCR lines ({c.result.lines.length})</summary>
            <pre>{c.result.lines.map((l) => l.text).join("\n") || "no OCR text"}</pre>
          </details>
          <details className="sub" data-testid="metadata">
            <summary>Metadata: this step</summary>
            <Facts rows={documentFacts(c.result, c)} />
          </details>
        </section>
      ))}
      <details className="metadata" data-testid="metadata">
        <summary>Metadata: the whole capture</summary>
        <Facts
          rows={[
            ["Scanner", scannerById(outcome.scanner).title],
            ["Steps", outcome.captured.length],
            ["Model", `ocrs text detection + recognition (${catalogueEntry("ocrs").downloadMb} MB)`],
            ...captureFacts(outcome.meta, ready),
          ]}
        />
      </details>
    </>
  );
}

// ---------------------------------------------------------------------------
// Proof of address
// ---------------------------------------------------------------------------

const ADDRESS_LABELS: [string, string][] = [
  ["holder_name", "Holder"],
  ["street", "Street"],
  ["suburb", "Suburb"],
  ["city", "City"],
  ["province", "Province"],
  ["postal_code", "Postal code"],
  ["document_date", "Document date"],
  ["period_from", "Period from"],
  ["period_to", "Period to"],
  ["issuer", "Issuer"],
  ["account_number", "Account number"],
];

function addressValues(r: AddressResult): Record<string, string | null> {
  const f = r.fields;
  return {
    holder_name: f.holder_name,
    street: f.address.street,
    suburb: f.address.suburb,
    city: f.address.city,
    province: f.address.province,
    postal_code: f.address.postal_code,
    document_date: f.document_date,
    period_from: f.statement_period?.from ?? null,
    period_to: f.statement_period?.to ?? null,
    issuer: f.issuer,
    account_number: f.account_number,
  };
}

function AddressResults({ outcome, ready }: { outcome: Extract<Outcome, { kind: "address" }>; ready: ReadyInfo | null }) {
  const { captured } = outcome;
  const r = captured.result;
  const values = addressValues(r);
  const age = r.verification.age;
  const check = (k: string) => r.verification.fields.find((c) => c.field === k);
  return (
    <section className="step" data-testid="address">
      <Verdict ok={r.verification.accepted} testid="address-verdict">
        {r.verification.accepted ? "Accepted as proof of address" : `Not accepted: ${r.verification.reasons.join("; ")}`}
      </Verdict>
      <img className="captured" src={captured.imageUrl} alt="captured page" />
      <Group title="Holder and address">
        {ADDRESS_LABELS.map(([k, label]) => {
          const v = values[k];
          const c = check(k);
          let status: Status | undefined;
          let note: string | undefined;
          if (v && k === "province" && r.fields.province_inferred) [status, note] = ["warn", "inferred from the postal code"];
          else if (v && c) [status, note] = c.found ? ["ok", "✓ found on the page"] : ["bad", `✗ not found on the page (${Math.round(c.match_score * 100)}% match)`];
          return <Field key={k} name={k} label={label} value={v} status={status} note={note} />;
        })}
      </Group>
      <Group title="The document">
        <Field label="Document type" value={human(r.fields.document_type)} />
        <Field
          label="Postal code ↔ province"
          value={r.verification.postal_code}
          status={r.verification.postal_code === "consistent" ? "ok" : r.verification.postal_code === "inconsistent" ? "bad" : undefined}
        />
        <div data-testid="age">
          <Field
            label="Age"
            value={age ? `${age.age_days} days` : "no date"}
            status={age ? (age.recent ? "ok" : "bad") : "warn"}
            note={age ? (age.recent ? "within three months" : age.future ? "dated in the future" : "older than three months") : "the document date was not found"}
          />
        </div>
      </Group>
      <details className="sub">
        <summary>Page text (OCR, {r.words} words)</summary>
        <pre data-testid="ocr-text">{r.text}</pre>
      </details>
      <details className="metadata" data-testid="metadata">
        <summary>Metadata</summary>
        <Facts
          rows={[
            ["Document kind", "proof of address"],
            ["Accepted", r.verification.accepted ? "yes" : "no"],
            ["Reasons", r.verification.reasons.join("; ") || "—"],
            ["Extractor", r.method === "tagger" ? `trained tagger (${catalogueEntry("poa-tagger").downloadMb} MB)` : "layout rules"],
            ["Extractor asked for", captured.asked === "auto" ? "automatic (the device's choice)" : captured.asked],
            ["OCR model", `ocrs (${catalogueEntry("ocrs").downloadMb} MB)`],
            ["Page size", `${r.page_size[0]} × ${r.page_size[1]}`],
            ["Enhance stage", ms(r.timings_ms.enhance)],
            ["OCR stage", ms(r.timings_ms.ocr)],
            ["Extract stage", ms(r.timings_ms.extract)],
            ["Total read", ms(r.timings_ms.total)],
            ["Read, end to end", ms(captured.readMs)],
            ...captureFacts(outcome.meta, ready),
          ]}
        />
      </details>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Barcodes and device labels
// ---------------------------------------------------------------------------

function fieldNote(f: LabelledField): [Status | undefined, string] {
  const source =
    f.source === "both" ? "barcode + print" : f.source === "barcode" ? "barcode" : f.barcode_unread ? "print (OCR) · bars present but unreadable" : "print (OCR)";
  const fmt = f.barcode_format ? ` · ${f.barcode_format}` : "";
  if (f.check_digit_valid === true) return ["ok", `${source}${fmt} · check digit ✓`];
  if (f.check_digit_valid === false) return ["bad", `${source}${fmt} · check digit ✗`];
  return [undefined, `${source}${fmt} · no check digit`];
}

function BarcodeResults({ outcome, ready }: { outcome: Extract<Outcome, { kind: "barcodes" }>; ready: ReadyInfo | null }) {
  return (
    <section className="step" data-testid="barcode-results">
      <Verdict ok={outcome.barcodes.length + outcome.fields.length > 0}>
        {outcome.labels ? `${outcome.fields.length} labelled field${outcome.fields.length === 1 ? "" : "s"}` : `${outcome.barcodes.length} barcode${outcome.barcodes.length === 1 ? "" : "s"}`}{" "}
        captured
      </Verdict>
      {outcome.imageUrl && <img className="captured" src={outcome.imageUrl} alt="the frame the set was captured from" />}
      {(outcome.labels || outcome.fields.length > 0) && (
        <Group title={outcome.labels ? "Device label" : "Labelled values"} testid="label-fields">
          {outcome.fields.length === 0 && <p className="empty">No labelled fields were read.</p>}
          {outcome.fields.map((f) => {
            const [status, note] = fieldNote(f);
            return <Field key={`${f.name}|${f.value}`} label={f.name} value={f.value} status={status} note={note} />;
          })}
        </Group>
      )}
      <Group title={outcome.labels ? "Barcodes read" : "Barcodes"} testid="barcodes">
        {outcome.barcodes.length === 0 && <p className="empty">No barcode was confirmed.</p>}
        {outcome.barcodes.map((b) => (
          <Field key={`${b.format}|${b.text}`} name={`${b.format}|${b.text}`} label={b.format.toUpperCase()} value={b.text} />
        ))}
      </Group>
      <details className="metadata" data-testid="metadata">
        <summary>Metadata</summary>
        <Facts
          rows={[
            ["Scanner", outcome.labels ? "device label" : "barcodes"],
            ["Finished because", outcome.finishedBy],
            ["Codes confirmed", outcome.barcodes.length],
            ["Reads per code", outcome.barcodes.map((b) => b.count).join(", ") || null],
            ["Model", outcome.labels ? `rxing barcodes + ocrs, tiled (${catalogueEntry("ocrs").downloadMb} MB)` : "rxing barcodes (no model)"],
            ...captureFacts(outcome.meta, ready),
          ]}
        />
      </details>
    </section>
  );
}


// ---------------------------------------------------------------------------
// Face liveness, Face ID and face vs document
// ---------------------------------------------------------------------------

const CHECK_LABELS: Record<string, string> = {
  coverage: "Ring coverage",
  "3d_motion": "3-D head motion (parallax)",
  antispoof: "Passive anti-spoofing",
  continuity: "Continuity (no splice, gap or second face)",
  identity: "Same face before and after",
  blink: "Blink",
  capture_integrity: "Capture integrity (camera, frame timing)",
};

function templateBase64(t: number[]): string {
  const bytes = new Uint8Array(new Float32Array(t).buffer);
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

function qualityFields(q: FaceQuality, prefix: string) {
  return (
    <>
      <Field name={`${prefix}quality`} label="Quality score (0–1)" value={q.score.toFixed(2)} status={q.score >= 0.5 ? "ok" : "warn"} note={q.problems.length ? q.problems.join(", ") : "no problems found"} />
      <Field label="Eye distance (px)" value={q.interocular_px.toFixed(0)} />
      <Field label="Sharpness" value={q.sharpness.toFixed(0)} />
      <Field label="Brightness" value={q.brightness.toFixed(0)} />
      <Field label="Evenness of light" value={q.evenness.toFixed(2)} />
      <Field label="Eyes open (aspect ratio)" value={q.eyes_open.toFixed(2)} />
      <Field label="Degrees off frontal" value={q.off_frontal.toFixed(0)} />
    </>
  );
}

function photoFields(p: PhotoFace, prefix: string) {
  if (!p.found) return <Verdict ok={false}>No face found</Verdict>;
  return (
    <>
      {qualityFields(p.quality, prefix)}
      {p.antispoof ? (
        <Field label="Passive anti-spoofing: live probability" value={p.antispoof.real.toFixed(2)} status={p.antispoof.real >= 0.5 ? "ok" : "bad"} note="a single still cannot show liveness; this is the passive model alone" />
      ) : null}
    </>
  );
}

function EnrolButton({ template, model }: { template: number[]; model: string }) {
  const [label, setLabel] = useState("Me");
  const [saved, setSaved] = useState<string | null>(null);
  return (
    <div className="enrol" data-testid="enrol">
      <label className="field">
        <span className="field-label">Enrol for Face ID as</span>
        <span className="field-row">
          <input value={label} onChange={(e) => setLabel(e.target.value)} />
          <button
            type="button"
            className="copy"
            data-testid="enrol-button"
            onClick={() => {
              const id = `${Date.now()}`;
              void saveEnrolment({ id, label: label || "Me", template, model, createdAt: new Date().toISOString() }).then(
                () => setSaved(label || "Me"),
                (e) => setSaved(`failed: ${e}`),
              );
            }}
          >
            Enrol
          </button>
        </span>
        <span className="field-note">
          {saved ? `Enrolled as “${saved}”. ` : ""}Demo storage: the template stays in this browser's IndexedDB, is never sent anywhere, and is biometric data (POPIA s.26).
        </span>
      </label>
    </div>
  );
}

function FaceResults({ outcome, face }: { outcome: Extract<Outcome, { kind: "face" }>; face: FaceClient | null }) {
  const l = outcome.liveness;
  const checks = l ? [...l.result.checks, l.integrity.check] : [];
  const m = outcome.match;
  void face;
  return (
    <section className="step" data-testid="face" data-flow={outcome.flow}>
      {l ? (
        <Verdict ok={l.passed} testid="liveness-verdict">
          {l.passed ? "Live face: every liveness check passed" : `Not live: ${[...l.result.reasons, ...(l.integrity.check.passed ? [] : ["capture integrity failed"])].join("; ") || "failed"}`}
        </Verdict>
      ) : (
        <Verdict ok={false} testid="liveness-verdict">
          From a photo: liveness cannot be shown from a still image
        </Verdict>
      )}
      {m !== undefined ? (
        m ? (
          <Verdict ok={m.matched} testid="face-match">
            {m.matched ? `Same person as ${m.against}` : `Not the same person as ${m.against}`}: similarity {m.similarity.toFixed(3)} (threshold {m.threshold.toFixed(3)})
          </Verdict>
        ) : (
          <Verdict ok={false} testid="face-match">
            {l && !l.passed ? "Not compared: the liveness check failed" : "Not compared: no face to compare with"}
          </Verdict>
        )
      ) : null}
      <div className="face-images">
        {l?.bestFrameUrl ? <img className="captured face-portrait" src={l.bestFrameUrl} alt="Best frontal frame" data-testid="best-frame" /> : null}
        {outcome.document ? <img className="captured" src={outcome.document.imageUrl} alt="Identity document" /> : null}
        {outcome.document?.alignedUrl ? <img className="face-crop" src={outcome.document.alignedUrl} alt="The document's face, aligned" /> : null}
        {outcome.photos?.map((p) => (
          <img key={p.label} className="captured face-portrait" src={p.imageUrl} alt={p.label} />
        ))}
      </div>
      {outcome.document ? <CopyEvidence assessment={outcome.document.copy_assessment} /> : null}
      {l ? (
        <Group title="Liveness checks" testid="liveness-checks">
          {checks.map((c) => (
            <Field
              key={c.name}
              name={`check-${c.name}`}
              label={`${CHECK_LABELS[c.name] ?? c.name}${c.required ? "" : " (not required)"}`}
              value={c.score.toFixed(3)}
              status={c.passed ? "ok" : c.required ? "bad" : "warn"}
              note={`${c.passed ? "passed" : "failed"} · threshold ${c.threshold} · ${c.detail}`}
            />
          ))}
        </Group>
      ) : null}
      {l?.result.quality ? <Group title="Best frame quality">{qualityFields(l.result.quality, "")}</Group> : null}
      {outcome.document ? <Group title="The document's face">{photoFields(outcome.document.face, "doc-")}</Group> : null}
      {outcome.photos?.map((p) => (
        <Group key={p.label} title={p.label}>
          {photoFields(p.face, p.label)}
        </Group>
      ))}
      {l && l.result.template.length ? (
        <Group title="Face template" testid="template">
          <Field name="template-model" label="Model" value={l.result.model} />
          <Field name="template" label={`Template (${l.result.template.length} float32, base64)`} value={templateBase64(l.result.template)} />
          {outcome.flow === "liveness" && l.passed ? <EnrolButton template={l.result.template} model={l.result.model} /> : null}
        </Group>
      ) : null}
      <details className="metadata" data-testid="metadata">
        <summary>Metadata</summary>
        <Facts
          rows={[
            ["Source", outcome.meta.source],
            ["Time to complete", l ? secs(l.captureMs) : secs(outcome.meta.captureMs)],
            ["Session (centred to done)", l ? secs(l.result.duration_ms) : null],
            ["Frames analysed", l ? `${l.frames} (${l.result.frames_with_face} with a face)` : outcome.meta.frames],
            ["Analysis rate", l ? `${l.fps.toFixed(1)} frames/s` : null],
            ["Per frame (median)", l?.msPerFrame ? ms(l.msPerFrame) : null],
            ["Camera", l ? `${l.integrity.cameraLabel || "unnamed"}${l.integrity.frameRate ? ` · ${Math.round(l.integrity.frameRate)} fps` : ""}` : null],
            ["Ring", l ? `${l.result.segments.filter(Boolean).length} of ${l.result.segments.length} segments` : null],
            ["Wasm memory", l ? `${Math.round(l.memoryBytes / 1048576)} MB` : null],
            ["Recognition model", `${RECOGNISER.name}; live-to-live threshold from the LFW DEV split, document threshold ${DOC_THRESHOLD}`],
            ["Models", `${FACE_DOWNLOAD_MB.toFixed(1)} MB: ${FACE_LICENCES.join("; ")}`],
          ]}
        />
      </details>
    </section>
  );
}

/** A body can render a batch page without nesting forms or home controls. */
function OutcomeBody({ outcome, ready, face, sourceInHeading = false }: { outcome: Outcome; ready: ReadyInfo | null; face: FaceClient | null; sourceInHeading?: boolean }) {
  return <>
    <InputSource input={outcome.meta.input} hideLabel={sourceInHeading} />
    {outcome.kind === "batch" && <>
      <p>{outcome.pages.length} results. Page readings and file-inspection warnings are listed separately.</p>
      {outcome.pages.map((page, i) => <section className="step" key={i} data-testid="batch-page">
        <h2>{page.meta.input ? sourceLabel(page.meta.input) : `Page result ${i + 1}`}</h2>
        <OutcomeBody outcome={page} ready={ready} face={face} sourceInHeading />
      </section>)}
    </>}
    {outcome.kind === "file_error" && <section role="alert" data-testid="file-error">
      {outcome.severity === "warning" ? <p><strong>Incomplete file inspection:</strong> {outcome.message}</p>
        : <Verdict ok={false}>File or page could not be read: {outcome.message}</Verdict>}
      <p>See the file evidence and any separate page readings. This is not an authenticity verdict.</p>
    </section>}
        {outcome.kind === "text" && <section>
          <Group title="Extracted text">
            <p className="muted">{outcome.result.text ? "Check the reading against the page before using it." : "No text found. Try a closer, sharper photo with the text upright."}</p>
            <textarea aria-label="Extracted text" readOnly value={outcome.result.text} rows={14} style={{ width: "100%", boxSizing: "border-box" }} />
            <CopyButton value={outcome.result.text} />
          </Group>
          <details className="metadata"><summary>Captured page</summary><img className="captured" src={outcome.imageUrl} alt="Captured document" /></details>
          <details className="metadata"><summary>Text positions and metadata</summary>
            <p>{"engine" in outcome.result ? "PP-OCRv6 tiny: line polygons refer to the input page" : "ocrs: word positions refer to the enhanced, deskewed page"} ({outcome.result.page_size.join(" × ")} pixels). Lines follow rows; tables and columns may need rearranging.</p>
            <CopyButton value={JSON.stringify(outcome.result, null, 2)} />
            <Facts rows={[["Words", "words" in outcome.result ? outcome.result.words.length : null], ["Lines", outcome.result.lines.length], ["OCR time", ms("ocr" in outcome.result.timings_ms ? outcome.result.timings_ms.ocr : outcome.result.timings_ms.total)], ...captureFacts(outcome.meta, ready)]} />
          </details>
        </section>}
        {outcome.kind === "id" && <IdResults outcome={outcome} ready={ready} />}
        {outcome.kind === "address" && <AddressResults outcome={outcome} ready={ready} />}
        {outcome.kind === "barcodes" && <BarcodeResults outcome={outcome} ready={ready} />}
        {outcome.kind === "face" && <FaceResults outcome={outcome} face={face} />}

    {outcome.documentEvidence ? <EvidenceResults evidence={outcome.documentEvidence} /> : null}
  </>;
}

export function Results({ outcome, ready, onHome, face = null }: { outcome: Outcome; ready: ReadyInfo | null; onHome: () => void; face?: FaceClient | null }) {
  const title = outcome.kind === "batch" ? `${scannerById(outcome.scanner).title} · document batch`
    : outcome.kind === "file_error" ? "Document could not be read"
    : outcome.kind === "id" ? scannerById(outcome.scanner).title
    : outcome.kind === "face" ? scannerById(outcome.flow).title
    : outcome.kind === "address" ? "Proof of address"
    : outcome.kind === "text" ? "Document text"
    : outcome.labels ? "Device label" : "Barcodes";
  return (
    <main className="results" data-testid="results" data-kind={outcome.kind}>
      <header className="results-head">
        <h1>{title}</h1>
        <span className="muted">{outcome.meta.source === "photo" ? "from uploaded images" : outcome.meta.source === "pdf" ? "from a digital document" : `captured in ${secs(outcome.meta.captureMs)}`}</span>
      </header>
      <p className="muted">Authenticity, issuer and physical originality are not verified.</p>
      <form className="results-form" onSubmit={(e) => e.preventDefault()}>
        <OutcomeBody outcome={outcome} ready={ready} face={face} />
      </form>
      <ReportExport outcome={outcome} />
      <button type="button" className="primary home-button" data-testid="results-home" onClick={onHome}>Back to home</button>
    </main>
  );
}

function InputSource({ input, hideLabel = false }: { input?: InputReference; hideLabel?: boolean }) {
  if (!input) return null;
  return <div data-testid="input-source">{!hideLabel && <p>{sourceLabel(input)}</p>}<Field label="Original file SHA-256" value={input.sha256 ?? "unknown"} /></div>;
}

function CopyEvidence({ assessment }: { assessment?: CopyAssessment }) {
  return <Group title="Physical original or copy" testid="copy-assessment">
    <Facts rows={[
      ["Assessment", human(assessment?.status ?? "unknown")],
      ["Is copy", assessment?.is_copy == null ? "unknown (null)" : assessment.is_copy ? "yes (heuristic indication)" : "no (heuristic indication)"],
      ["Confidence", assessment?.confidence == null ? "unknown (null); not calibrated" : `${assessment.confidence} (uncalibrated heuristic score)`],
    ]} />
    <p className="muted">Physical originality is not established. The pixel heuristic abstains: periodic security patterns can resemble copying artifacts. Upload type and successful reading do not resolve this.</p>
    {assessment?.signals.length ? <details className="sub"><summary>Observed pixel signals</summary><Facts rows={assessment.signals.map((s, i) => [`${s.code} (${i + 1})`, s.value])} /></details> : null}
    {assessment?.limitations.length ? <ul>{assessment.limitations.map((l, i) => <li key={i}>{human(l)}</li>)}</ul> : null}
  </Group>;
}
const countLabel = (c: CountCheck) => `${c.count ?? "unknown"} · ${human(c.status)}${c.capped ? " · capped" : ""} · ${c.scope}`;

function FileEvidenceResults({ file, index }: { file: FileEvidence; index: number }) {
  const pdf = file.pdf;
  return <section className="step" data-testid="file-evidence">
    <h3>File {index + 1}: {file.original.name ?? "unnamed file"}</h3>
    <p><strong>Evidence: {file.status}</strong>{file.status !== "complete" ? ". Missing checks are unknown, not evidence of absence." : ". Complete inspection does not establish authenticity."}</p>
    <Field label="SHA-256 of original bytes" value={file.original.sha256 ?? "unknown"} note="Identifies these bytes; does not authenticate their source." />
    <Facts rows={[
      ["Size", `${file.original.sizeBytes} bytes`], ["Declared / detected type", `${file.original.declaredMime || "unknown"} / ${file.original.detectedMime ?? "unknown"}`],
      ["MIME check", `${human(file.original.mimeCheck)}${file.original.mimeMismatch ? " · mismatch" : ""}`],
      ["Image dimensions", file.image ? `${file.image.width} × ${file.image.height}` : null],
      ["Metadata", `${human(file.metadata.status)} · self-reported, unverified${file.metadata.truncated ? " · truncated" : ""}`],
      ["PDF pages", pdf ? `${pdf.numPages} total · ${pdf.inspectedPages} inspected · ${pdf.omittedPages} omitted from inspection` : null],
    ]} />
    {pdf ? <Group title="PDF signatures and active content">
      <Facts rows={[
        ["Signature evidence", `${human(pdf.signatures.status)} · ${human(pdf.signatures.check)}`],
        ["Signature fields", pdf.signatures.fieldCount ?? "unknown"],
        ["Signed values observed", pdf.signatures.count ?? "unknown"],
        ["Cryptographic verification", "not supported"], ["Issuer trust", "not verified / not supported"],
        ["Annotations", countLabel(pdf.annotations)], ["Form fields", countLabel(pdf.formFields)], ["Attachments", countLabel(pdf.attachments)],
        ["Document JavaScript actions", countLabel(pdf.documentJavaScriptActions)],
        ["Form JavaScript presence", `${pdf.formJavaScriptPresence.present === null ? "unknown" : pdf.formJavaScriptPresence.present ? "present" : "not observed"} · ${human(pdf.formJavaScriptPresence.status)}`],
      ]} />
      <p>A signature field may be empty. A signed value's presence does not verify its cryptography, signer, issuer or coverage.</p>
    </Group> : null}
    {file.errors.length ? <div role="alert"><h4>Evidence errors</h4><ul>{file.errors.map((e, i) => <li key={i}>{e.stage} · {e.code}{e.pageIndex === undefined ? "" : ` · page ${e.pageIndex + 1}`}: {e.message}</li>)}</ul></div> : null}
    {file.signals.length ? <><h4>Observed signals</h4><ul>{file.signals.map((s, i) => <li key={i}><strong>{s.code}</strong> · {s.severity} · {s.source}: {s.observed}<p className="muted">{s.limitations}</p></li>)}</ul></> : null}
    <details className="sub"><summary>File metadata and inspection limits</summary>
      <p>File names, modification dates and metadata are untrusted claims.</p>
      <Facts rows={[["File last modified (milliseconds since epoch)", file.original.lastModified ?? "unknown"], ["GPS presence", human(file.metadata.gpsPresence)], ...Object.entries(file.metadata.fields).map(([k, v]): [string, ReactNode] => [k, String(v)])]} />
      <ul>{file.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
    </details>
    {pdf?.pages.map(page => <details className="sub" key={page.index}>
      <summary>PDF page {page.index + 1}: {page.status} · native text {human(page.text.status)}{page.text.truncated ? " (truncated)" : ""}</summary>
      <p>Native PDF text is untrusted and is not OCR of visible pixels. It may be hidden or differ from the rendered page.</p>
      <Facts rows={[["Page dimensions", `${page.width ?? "unknown"} × ${page.height ?? "unknown"}`], ["Rotation", page.rotation ?? "unknown"], ["Annotations", countLabel(page.annotations)], ["JavaScript actions", countLabel(page.javaScriptActions)]]} />
      <pre>{page.text.items.map(t => t.text).join("\n") || "No native text available"}</pre>
      <details><summary>Native text positions and fonts</summary><pre>{JSON.stringify(page.text.items, null, 2)}</pre></details>
    </details>)}
  </section>;
}

function EvidenceResults({ evidence }: { evidence: DocumentEvidence }) {
  return <section data-testid="document-evidence">
    <h2>Original file evidence</h2>
    <p>Authenticity and tampering: unknown. Issuer not verified. No cryptographic signature verification is performed.</p>
    {!evidence.files.length ? <p>No original-file inspection is available.</p> : evidence.files.map((file, i) => <FileEvidenceResults key={i} file={file} index={i} />)}
    {evidence.comparisons.map((c, i) => <Group key={i} title={`Native text ↔ rendered-page OCR · ${sourceLabel(c.input)}`}>
      <p><strong>{human(c.result.status)}</strong>: {c.result.reason}</p>
      <Facts rows={[
        ["Method", c.result.method], ["Native tokens / OCR tokens", `${c.result.nativeTokens} / ${c.result.ocrTokens}`], ["Shared tokens", c.result.sharedTokens ?? "unknown"],
        ["Native token coverage", c.result.nativeTokenCoverage === null ? "unknown" : pct(c.result.nativeTokenCoverage)],
        ["OCR token support", c.result.ocrTokenSupport === null ? "unknown" : pct(c.result.ocrTokenSupport)],
      ]} />
      <p className="muted">These are text agreement measures, not authenticity probabilities. OCR errors, reading order and legitimate hidden text can explain discrepancies.</p>
      <details className="sub"><summary>Discrepancy samples (bounded)</summary><Facts rows={[
        ["Native only", c.result.nativeOnlySample.join(" · ") || "none reported"], ["OCR only", c.result.ocrOnlySample.join(" · ") || "none reported"],
        ["Numeric native only", c.result.numericDisagreements.nativeOnly.join(" · ") || "none reported"], ["Numeric OCR only", c.result.numericDisagreements.ocrOnly.join(" · ") || "none reported"],
      ]} /></details>
    </Group>)}
  </section>;
}

function ReportExport({ outcome }: { outcome: Outcome }) {
  const [error, setError] = useState<string | null>(null);
  return <section>
    <button type="button" className="copy" data-testid="export-document-report" onClick={() => {
      try {
        const url = URL.createObjectURL(new Blob([documentReportJson(outcome)], { type: "application/json" }));
        const anchor = document.createElement("a");
        anchor.href = url; anchor.download = "document-report.json";
        document.body.append(anchor);
        try { anchor.click(); } finally { anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
        setError(null);
      } catch (e) { setError(`Report export failed: ${e instanceof Error ? e.message : String(e)}`); }
    }}>Export JSON report</button>
    <p className="muted">Includes extracted document data and evidence. Excludes face templates, images and original file bytes.</p>
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
