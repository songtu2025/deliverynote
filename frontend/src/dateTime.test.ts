import { describe, expect, it } from "vitest";

import {
  beijingDateTimeParts,
  formatBeijingDate,
  formatBeijingDateTime,
  formatBeijingTime
} from "./dateTime";

describe("Beijing time formatting", () => {
  it("treats legacy timezone-free API values as UTC and displays Beijing time", () => {
    expect(formatBeijingDateTime("2026-07-21T09:00:00")).toBe("2026/7/21 17:00:00");
    expect(formatBeijingDate("2026-07-21T16:30:00Z")).toBe("2026/7/22");
    expect(formatBeijingTime("2026-07-21T16:30:00Z")).toBe("00:30:00");
  });

  it("uses Beijing calendar parts independently of the browser timezone", () => {
    expect(beijingDateTimeParts(new Date("2026-07-21T16:30:00Z"))).toEqual({
      year: "2026",
      month: "07",
      day: "22",
      hour: "00",
      minute: "30"
    });
  });

  it("returns a placeholder for invalid values", () => {
    expect(formatBeijingDateTime("not-a-date")).toBe("—");
  });
});
