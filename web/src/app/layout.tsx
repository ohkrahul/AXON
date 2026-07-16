import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "A.X.O.N.",
  description: "AXON — AI assistant + second brain, powered by Claude",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
