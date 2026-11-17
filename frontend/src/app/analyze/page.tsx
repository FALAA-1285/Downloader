import type { Metadata } from "next";
import { Suspense } from "react";
import { AnalyzeView, AnalyzeSkeleton } from "@/components/media-preview/analyze-view";

export const metadata: Metadata = { title: "Hasil analisis" };

export default function AnalyzePage() {
  return (
    <Suspense fallback={<AnalyzeSkeleton />}>
      <AnalyzeView />
    </Suspense>
  );
}
