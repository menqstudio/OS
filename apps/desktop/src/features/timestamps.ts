// One parser for the timestamps the backend writes.
//
// `brops_core::now()` returns MILLISECONDS SINCE THE EPOCH AS TEXT — `"1700000000000"` — and
// every `created_at` / `updated_at` / `ran_at` column carries that. `new Date("1700000000000")`
// is an Invalid Date, because a digit string is not an ISO date. Each page had its own copy of
// the conversion and two had none: Integrations and Automations called `new Date(raw)` and so
// rendered a dash for every date they have ever shown, and Security printed the raw number.
//
// The pages keep their own formatters (each shows a different granularity). What they share is
// the one step that was wrong when it was missing.

/**
 * Parse a backend timestamp. Accepts epoch-milliseconds as text or as a number, and an ISO
 * string (calendar events and delegation frames carry ISO). Returns `null` for an absent,
 * blank or unparseable value — never a `Date` that would format as "Invalid Date", and never
 * "now" standing in for a time nobody recorded.
 */
export function parseTimestamp(raw: string | number | null | undefined): Date | null {
  if (raw == null) return null;
  const text = String(raw).trim();
  if (text === '') return null;
  const ms = Number(text);
  const d = new Date(Number.isNaN(ms) ? text : ms);
  return Number.isNaN(d.getTime()) ? null : d;
}
