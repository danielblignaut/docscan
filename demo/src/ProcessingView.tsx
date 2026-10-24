/** Visible immediately after acquisition; the camera no longer needs the subject. */
export function ProcessingView({ title, stage, onCancel, failed = false }: { title: string; stage: string; onCancel?: () => void; failed?: boolean }) {
  return <main className="processing-panel" data-testid="processing" aria-live="polite" aria-busy={!failed}>
    {!failed && <div className="processing-spinner" aria-hidden="true" />}
    <h1>{title}</h1>
    <p>You can move the image or document away.</p>
    <p role={failed ? "alert" : "status"}>{stage}</p>
    {onCancel && <button type="button" className="primary" data-testid="processing-cancel" onClick={onCancel}>Cancel</button>}
  </main>;
}
