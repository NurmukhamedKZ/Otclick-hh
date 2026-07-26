import { Btn, KeyHint, PageHeader } from "@/components/otclick/ui";
import { ISearch } from "@/components/otclick/icons";
import { openCommandPalette } from "@/components/otclick/command-palette";
import HHBanner from "@/components/otclick/hh-banner";
import LimitRing from "./limit-ring";
import WeeklyPlan from "./weekly-plan";
import QuickActions from "./quick-actions";
import RecentApplicationsCard from "./recent-applications-card";
import ResumesCard from "./resumes-card";
import NotificationsCard from "./notifications-card";

export default async function DashboardPage() {
  return (
    <>
      <PageHeader title="Главная" subtitle="обзор автоотклика и последних событий" crumbs={[{ label: "Главная" }]}
        actions={<Btn kind="ghost" size="sm" icon={<ISearch size={15} />} onClick={openCommandPalette}>поиск <KeyHint>⌘K</KeyHint></Btn>}
      />
      <HHBanner />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 240px), 1fr))",
          gap: 18,
        }}
      >
        <LimitRing />
        <WeeklyPlan />
        <QuickActions />
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))",
          gap: 18,
          marginTop: 18,
        }}
      >
        <RecentApplicationsCard />
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <ResumesCard />
          <NotificationsCard />
        </div>
      </div>
    </>
  );
}
