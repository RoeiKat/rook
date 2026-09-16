import { useEffect, useId, useRef } from "react";

interface Props {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  busy?: boolean;
  danger?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ConfirmationModal({
  open,
  title,
  description,
  confirmLabel,
  busy = false,
  danger = false,
  onCancel,
  onConfirm,
}: Props) {
  const titleId = useId();
  const descriptionId = useId();
  const confirmButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    confirmButton.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [busy, onCancel, open]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={() => !busy && onCancel()}>
      <section
        aria-describedby={descriptionId}
        aria-labelledby={titleId}
        aria-modal="true"
        className="confirmation-modal"
        role="dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId}>{title}</h2>
        <p id={descriptionId}>{description}</p>
        <div className="modal-actions">
          <button className="modal-cancel" disabled={busy} onClick={onCancel}>Cancel</button>
          <button ref={confirmButton} className={danger ? "modal-confirm is-danger" : "modal-confirm"} disabled={busy} onClick={onConfirm}>
            {busy ? "Please wait..." : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
