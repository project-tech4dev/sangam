"use client";

import { useEffect, useRef } from "react";
import { CircleCheck, X } from "lucide-react";


export function Toast({ children, onDismiss, ms = 4000 }: { children: React.ReactNode; onDismiss: () => void; ms?: number }) {
  
  const dismiss = useRef(onDismiss);
  useEffect(() => {
    dismiss.current = onDismiss;
  });
  useEffect(() => {
    const timer = setTimeout(() => dismiss.current(), ms);
    return () => clearTimeout(timer);
  }, [ms]);
  return (
    <div className="toast" role="status" aria-live="polite">
      <CircleCheck className="icon" />
      <span>{children}</span>
      <button type="button" className="toast-close" onClick={onDismiss} aria-label="Dismiss">
        <X className="icon icon-sm" />
      </button>
    </div>
  );
}
