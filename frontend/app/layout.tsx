import type { Metadata } from "next";
import Link from "next/link";
import "@copilotkit/react-ui/styles.css";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Sangam",
  description: "Grant intelligence for CSOs and funders",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <nav className="topnav">
            <Link href="/" className="brand">
              Sangam
            </Link>
            <Link href="/orgs">Organisations</Link>
            <Link href="/funders">Funders</Link>
          </nav>
          <main>{children}</main>
        </Providers>
      </body>
    </html>
  );
}
