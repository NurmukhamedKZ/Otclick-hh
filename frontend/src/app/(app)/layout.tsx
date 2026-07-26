import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { Providers } from "@/lib/providers";
import Sidebar from "@/components/otclick/sidebar";
import WorkerBar from "@/components/otclick/worker-bar";
import FiltersDrawer from "@/components/filters-drawer";
import CaptchaModal from "@/components/captcha-modal";
import CommandPalette from "@/components/otclick/command-palette";
import OnboardingModal from "@/components/otclick/onboarding-modal";
import Toaster from "@/components/toaster";
import RealtimeBridge from "@/app/(app)/dashboard/realtime-bridge";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/auth");

  return (
    <Providers>
      <div
        className="oc-app-shell"
        style={{
          minHeight: "100vh",
          display: "flex",
          padding: "16px 16px 16px 8px",
          gap: 0,
          position: "relative",
          zIndex: 1,
        }}
      >
        <Sidebar email={user.email ?? null} />
        <main className="oc-app-main" style={{ flex: 1, minWidth: 0, padding: "4px 12px 24px" }}>
          <WorkerBar />
          {children}
        </main>
        <FiltersDrawer />
        <CaptchaModal />
        <CommandPalette />
        <OnboardingModal />
        <RealtimeBridge />
        <Toaster />
      </div>
    </Providers>
  );
}
