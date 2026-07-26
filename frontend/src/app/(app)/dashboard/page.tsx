import { PageHeader } from "@/components/otclick/ui";
import CaptchaBanner from "@/components/otclick/captcha-banner";
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
      <PageHeader title="Главная" subtitle="обзор автоотклика и последних событий" crumbs={[{ label: "Главная" }]} />
      <HHBanner />
      <CaptchaBanner />
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
