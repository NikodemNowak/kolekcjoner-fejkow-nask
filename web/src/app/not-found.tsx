import Link from "next/link";
import { SearchX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";

export default function NotFound() {
  return (
    <EmptyState
      icon={<SearchX className="size-5" strokeWidth={1.75} />}
      title="Nie znaleziono strony"
      text="Ta strona nie istnieje albo zgłoszenie zostało usunięte."
      className="mt-6"
    >
      <Button asChild size="sm" variant="outline" className="mt-2">
        <Link href="/">Wróć do przeglądu</Link>
      </Button>
    </EmptyState>
  );
}
