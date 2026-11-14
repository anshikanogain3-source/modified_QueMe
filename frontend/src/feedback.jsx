import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

const FeedbackContext = createContext(null);
const FOCUSABLE_SELECTOR =
  'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useFeedback() {
  const context = useContext(FeedbackContext);
  if (!context) throw new Error("useFeedback must be used inside FeedbackProvider.");
  return context;
}

export function useDialogAccessibility({ open, dialogRef, initialFocusRef, onClose }) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;

    const returnFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const focusables = () =>
      Array.from(dialogRef.current?.querySelectorAll(FOCUSABLE_SELECTOR) || []);
    const initialTarget = initialFocusRef?.current || focusables()[0] || dialogRef.current;
    initialTarget?.focus();

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current?.();
        return;
      }
      if (event.key !== "Tab") return;

      const items = focusables();
      if (!items.length) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialogRef.current?.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialogRef.current?.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      if (returnFocus?.isConnected) returnFocus.focus();
    };
  }, [open, dialogRef, initialFocusRef]);
}

function ConfirmDialog({ request, onFinish }) {
  const dialogRef = useRef(null);
  const cancelRef = useRef(null);
  const titleId = useId();
  const descriptionId = useId();

  useDialogAccessibility({
    open: Boolean(request),
    dialogRef,
    initialFocusRef: cancelRef,
    onClose: () => onFinish(false),
  });

  if (!request) return null;
  const destructive = request.tone === "danger";

  return (
    <div
      className="feedback-dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onFinish(false);
      }}
    >
      <section
        className={`feedback-dialog${destructive ? " is-destructive" : ""}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        ref={dialogRef}
        tabIndex={-1}
      >
        <div className="feedback-dialog-mark" aria-hidden="true">{destructive ? "!" : "?"}</div>
        <div className="feedback-dialog-copy">
          <h2 id={titleId}>{request.title}</h2>
          <p id={descriptionId}>{request.description}</p>
        </div>
        <div className="feedback-dialog-actions">
          <button ref={cancelRef} type="button" className="feedback-dialog-cancel" onClick={() => onFinish(false)}>
            {request.cancelLabel || "Cancel"}
          </button>
          <button
            type="button"
            className={`feedback-dialog-confirm${destructive ? " is-destructive" : ""}`}
            onClick={() => onFinish(true)}
          >
            {request.confirmLabel || "Confirm"}
          </button>
        </div>
      </section>
    </div>
  );
}

export function FeedbackProvider({ children }) {
  const [notifications, setNotifications] = useState([]);
  const [confirmation, setConfirmation] = useState(null);
  const notificationsRef = useRef([]);
  const timersRef = useRef(new Map());
  const timerVersionsRef = useRef(new Map());
  const timerSequenceRef = useRef(0);
  const sequenceRef = useRef(0);
  const confirmationResolverRef = useRef(null);

  const publishNotifications = useCallback((next) => {
    notificationsRef.current = next;
    setNotifications(next);
  }, []);

  const dismiss = useCallback((id) => {
    const timer = timersRef.current.get(id);
    if (timer) window.clearTimeout(timer);
    timersRef.current.delete(id);
    timerVersionsRef.current.delete(id);
    publishNotifications(notificationsRef.current.filter((item) => item.id !== id));
  }, [publishNotifications]);

  const notify = useCallback((type, message, options = {}) => {
    const text = String(message || "").trim();
    if (!text) return null;
    const normalizedType = ["success", "error", "warning", "info"].includes(type) ? type : "info";
    const current = notificationsRef.current;
    const duplicate = current.find((item) => item.type === normalizedType && item.message === text);
    let id;
    let next;

    if (duplicate) {
      id = duplicate.id;
      const oldTimer = timersRef.current.get(id);
      if (oldTimer) window.clearTimeout(oldTimer);
      next = current.map((item) => item.id === id ? { ...item, createdAt: Date.now() } : item);
    } else {
      id = `feedback-${++sequenceRef.current}`;
      next = [...current, { id, type: normalizedType, message: text, createdAt: Date.now() }];
      while (next.length > 3) {
        const removed = next.shift();
        const oldTimer = timersRef.current.get(removed.id);
        if (oldTimer) window.clearTimeout(oldTimer);
        timersRef.current.delete(removed.id);
        timerVersionsRef.current.delete(removed.id);
      }
    }

    publishNotifications(next);
    const defaultDuration = normalizedType === "error" ? 8000 : normalizedType === "warning" ? 7000 : 4500;
    const duration = Number.isFinite(options.duration) ? Math.max(0, options.duration) : defaultDuration;
    const timerVersion = ++timerSequenceRef.current;
    timerVersionsRef.current.set(id, timerVersion);
    if (duration > 0) {
      const timer = window.setTimeout(() => {
        if (timerVersionsRef.current.get(id) === timerVersion) dismiss(id);
      }, duration);
      timersRef.current.set(id, timer);
    } else {
      timersRef.current.delete(id);
    }
    return id;
  }, [dismiss, publishNotifications]);

  const confirm = useCallback((options) => new Promise((resolve) => {
    if (confirmationResolverRef.current) {
      resolve(false);
      return;
    }
    confirmationResolverRef.current = resolve;
    setConfirmation({
      title: options.title,
      description: options.description,
      confirmLabel: options.confirmLabel,
      cancelLabel: options.cancelLabel,
      tone: options.tone || "default",
    });
  }), []);

  const finishConfirmation = useCallback((accepted) => {
    const resolve = confirmationResolverRef.current;
    if (!resolve) return;
    confirmationResolverRef.current = null;
    setConfirmation(null);
    resolve(accepted);
  }, []);

  useEffect(() => () => {
    for (const timer of timersRef.current.values()) window.clearTimeout(timer);
    timersRef.current.clear();
    timerVersionsRef.current.clear();
    confirmationResolverRef.current?.(false);
    confirmationResolverRef.current = null;
  }, []);

  const value = useMemo(() => ({ notify, confirm }), [notify, confirm]);

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <div className="feedback-notification-stack" aria-label="Notifications">
        {notifications.map((item) => (
          <div
            key={item.id}
            className={`feedback-notification is-${item.type}`}
            role={item.type === "error" ? "alert" : "status"}
            aria-live={item.type === "error" ? "assertive" : "polite"}
            aria-atomic="true"
          >
            <span className="feedback-notification-mark" aria-hidden="true">
              {item.type === "success" ? "✓" : item.type === "error" ? "!" : item.type === "warning" ? "⚠" : "i"}
            </span>
            <span className="feedback-notification-message">{item.message}</span>
            <button type="button" aria-label="Dismiss notification" onClick={() => dismiss(item.id)}>×</button>
          </div>
        ))}
      </div>
      <ConfirmDialog request={confirmation} onFinish={finishConfirmation} />
    </FeedbackContext.Provider>
  );
}
