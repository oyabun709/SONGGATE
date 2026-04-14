import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "RopQA — Stop Releasing With Metadata Errors",
  description:
    "Pre-flight every release before delivery. Automated DDEX validation, DSP readiness scoring, and fraud detection for music distributors and labels.",
};

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
