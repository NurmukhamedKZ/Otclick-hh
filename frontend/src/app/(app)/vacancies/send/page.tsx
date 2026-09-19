"use client";

import SenderControl from "../sender-control";
import SendProblems from "./send-problems";

export default function VacancySendControlPage() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <SenderControl />
      <SendProblems />
    </div>
  );
}
