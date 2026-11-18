"use client";

// Error boundary per halaman (M-09): kesalahan render tidak lagi membuat seluruh aplikasi kosong;
// header dan navigasi tetap tampil dan pengguna bisa mencoba lagi.

import { useEffect } from "react";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ButtonLink, EmptyState } from "@/components/ui/primitives";

export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="frame flex flex-1 flex-col justify-center">
      <EmptyState
        icon={<TriangleAlert className="size-5" aria-hidden />}
        title="Halaman ini mengalami kesalahan"
        action={
          <div className="flex gap-2">
            <Button onClick={reset}>Coba lagi</Button>
            <ButtonLink href="/" variant="outline">
              Ke beranda
            </ButtonLink>
          </div>
        }
      >
        Data Anda aman. Coba muat ulang bagian ini; bila terus terjadi, periksa apakah backend berjalan.
        {error.digest ? ` (kode: ${error.digest})` : ""}
      </EmptyState>
    </div>
  );
}
