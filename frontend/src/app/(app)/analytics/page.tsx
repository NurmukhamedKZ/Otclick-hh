import { PageHeader } from "@/components/otclick/ui";
import AnalyticsView from "./analytics-view";

export default function AnalyticsPage() {
  return (
    <>
      <PageHeader
        title="Аналитика"
        subtitle="что работает, а что жжёт лимит"
        crumbs={[{ label: "Главная", href: "/dashboard" }, { label: "Аналитика" }]}
      />
      <AnalyticsView />
    </>
  );
}
