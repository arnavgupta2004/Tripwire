/** Round to one decimal like Python's format(): ties go to the even digit (0.8125 → 81.2%),
 * so the Evidence page shows the same numbers as evals/agentdojo/results.md. */
export function round1(percent: number): number {
  const n = percent * 10;
  const f = Math.floor(n);
  const tie = Math.abs(n - f - 0.5) < 1e-9;
  return (tie ? (f % 2 === 0 ? f : f + 1) : Math.round(n)) / 10;
}

/** A fraction (0–1) as a percentage string with one decimal, e.g. 0.05 → "5.0%". */
export const pct1 = (x: number): string => `${round1(100 * x).toFixed(1)}%`;
