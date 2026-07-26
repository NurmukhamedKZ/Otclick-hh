"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { Banner } from "@/components/otclick/ui";
import { openCaptchaModal } from "@/components/captcha-modal";

export default function CaptchaBanner() {
  const { data } = useQuery({
    queryKey: ["captcha-pending"],
    queryFn: () => apiFetch<{ items: { id: string }[] }>("/api/captcha/pending"),
    refetchInterval: 15000,
  });
  const n = data?.items?.length ?? 0;
  if (n === 0) return null;
  return (
    <Banner
      tone="err"
      title={n === 1 ? "hh просит пройти капчу" : `hh просит пройти капчу · ${n}`}
      description="автоотклик на паузе, пока капча не решена"
      action={{ label: "Решить", onClick: openCaptchaModal }}
    />
  );
}
