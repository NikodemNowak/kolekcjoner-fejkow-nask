"use client";

import { RotateCcw, ServerCrash } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <EmptyState
      icon={<ServerCrash className="size-5" strokeWidth={1.75} />}
      title="Nie udało się wczytać danych"
      text="Serwer analizy nie odpowiada albo zwrócił błąd. Sprawdź, czy API działa, i spróbuj ponownie."
      className="mt-6"
    >
      <Button size="sm" variant="outline" className="mt-2" onClick={reset}>
        <RotateCcw className="size-3.5" /> Spróbuj ponownie
      </Button>
    </EmptyState>
  );
}
