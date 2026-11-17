"use client";

import { useState } from "react";
import { CloudOff, Loader2, RotateCcw } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { syncHistory, useSyncError } from "@/services/jobs-store";

/** Ditampilkan saat sinkronisasi dengan backend gagal; data yang terlihat mungkin tidak terbaru. */
export function SyncErrorAlert({ className }: { className?: string }) {
  const error = useSyncError();
  const [retrying, setRetrying] = useState(false);
  if (!error) return null;

  return (
    <Alert variant="destructive" className={className}>
      <CloudOff aria-hidden />
      <AlertTitle>Tidak dapat memuat data terbaru</AlertTitle>
      <AlertDescription>
        <p>{error} Daftar di bawah mungkin bukan kondisi terkini di server.</p>
        <Button
          variant="outline"
          size="sm"
          className="mt-2"
          disabled={retrying}
          onClick={async () => {
            setRetrying(true);
            await syncHistory();
            setRetrying(false);
          }}
        >
          {retrying ? <Loader2 className="animate-spin" aria-hidden /> : <RotateCcw aria-hidden />}
          Coba lagi
        </Button>
      </AlertDescription>
    </Alert>
  );
}
