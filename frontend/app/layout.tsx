import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Auto Literature Review",
  description: "AI-powered Scopus literature review with Zotero integration",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
