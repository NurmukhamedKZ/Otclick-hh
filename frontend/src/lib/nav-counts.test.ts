import { describe, expect, it } from "vitest";
import { computeNavCounts, formatBadge } from "./nav-counts";

describe("formatBadge", () => {
  it("hides a zero badge", () => {
    expect(formatBadge(0)).toBeNull();
  });

  it("hides a negative count", () => {
    expect(formatBadge(-3)).toBeNull();
  });

  it("shows a plain number up to 99", () => {
    expect(formatBadge(1)).toBe("1");
    expect(formatBadge(99)).toBe("99");
  });

  it("caps above 99", () => {
    expect(formatBadge(100)).toBe("99+");
    expect(formatBadge(4210)).toBe("99+");
  });
});

describe("computeNavCounts", () => {
  it("is all zeros for empty input", () => {
    expect(
      computeNavCounts({
        chats: [],
        formDrafts: [],
        recruiterDrafts: [],
        todos: [],
        unreadNotifications: 0,
      }),
    ).toEqual({ chats: 0, todo: 0, notifications: 0 });
  });

  it("sums unread across chats", () => {
    const r = computeNavCounts({
      chats: [{ unread: 2 }, { unread: 0 }, { unread: 5 }],
      formDrafts: [],
      recruiterDrafts: [],
      todos: [],
      unreadNotifications: 0,
    });
    expect(r.chats).toBe(7);
  });

  it("adds the three todo sources together", () => {
    const r = computeNavCounts({
      chats: [],
      formDrafts: [{}, {}],
      recruiterDrafts: [{}],
      todos: [{}, {}, {}],
      unreadNotifications: 0,
    });
    expect(r.todo).toBe(6);
  });

  it("passes the notification count through", () => {
    const r = computeNavCounts({
      chats: [],
      formDrafts: [],
      recruiterDrafts: [],
      todos: [],
      unreadNotifications: 12,
    });
    expect(r.notifications).toBe(12);
  });
});
