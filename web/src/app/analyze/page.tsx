import type { Metadata } from "next";
import { PageHeader } from "@/components/page-header";
import { HowToRead } from "@/components/how-to-read";
import { Analyzer } from "@/components/analyzer";

export const metadata: Metadata = { title: "Analizuj reklamę" };

export default function AnalyzePage() {
  return (
    <>
      <PageHeader
        title="Analizuj reklamę"
        description="Wgraj reklamę i sprawdź, czy to kolejna odsłona oszustwa, które już znamy."
      />
      <HowToRead
        className="mb-6 max-w-3xl"
        items={[
          "Wgraj zrzut ekranu reklamy albo plik z zapisem strony i kliknij Analizuj. Zgłoszenie zostanie zapisane w bazie; zaznacz „Tylko sprawdź, nie zapisuj”, jeśli tego nie chcesz.",
          "Pierwsze zdanie werdyktu mówi wprost, czy to znana kampania, coś nowego, czy sprawa dla analityka. Niżej jest wynik w procentach i ślady, które o nim zdecydowały.",
          "Pod werdyktem widać, pod jakim numerem zgłoszenie trafiło do bazy. Pomyłkę można od razu cofnąć przyciskiem „Cofnij dodanie”.",
        ]}
      />
      <Analyzer />
    </>
  );
}
