import Link from "next/link";

export function Footer() {
  return (
    <footer className="mt-16 bg-sage-900 py-9 text-sand-200">
      <div className="mx-auto flex max-w-(--page-max) flex-wrap items-baseline justify-between gap-5 px-(--page-pad) text-sm">
        <div className="flex gap-[22px]">
          <Link href="/terms" className="text-sand-300 hover:no-underline">
            Terms &amp; Privacy
          </Link>
        </div>
        <div className="opacity-70">© 2026 All rights reserved.</div>
      </div>
    </footer>
  );
}
