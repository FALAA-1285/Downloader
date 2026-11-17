import type { Metadata } from "next";
import { DownloadsView } from "@/components/download-list/downloads-view";

export const metadata: Metadata = { title: "Downloads" };

export default function DownloadsPage() {
  return <DownloadsView />;
}
