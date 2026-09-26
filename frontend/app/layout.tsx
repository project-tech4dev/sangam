import type { Metadata } from "next";
import { Public_Sans } from "next/font/google";
import "./globals.css";
import { NavBar } from "@/components/layout/NavBar";
import { Providers } from "./providers";

const publicSans = Public_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-public-sans",
});

export const metadata: Metadata = {
  title: "Sangam",
  description: "Where funders and CSOs across North East India actually meet",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={publicSans.variable}>
      <body>
        <Providers>
          <NavBar />
          <main>{children}</main>
        </Providers>
      </body>
    </html>
  );
}
