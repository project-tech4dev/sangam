"use client";

/** Opens the browser's print dialog, where "Save as PDF" writes the brief with the print styles in globals.css. */
export function PrintButton({ title }: { title: string }) {
  function print() {
    // The browser names the PDF after the document title.
    const previous = document.title;
    document.title = title;
    window.print();
    document.title = previous;
  }
  return (
    <button type="button" className="btn btn-secondary brief-print" onClick={print}>
      Download PDF
    </button>
  );
}
