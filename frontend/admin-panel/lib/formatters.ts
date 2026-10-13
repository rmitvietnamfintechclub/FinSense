export function formatScore(score: number | null | undefined, isEmpty: boolean = false): string {
  if (isEmpty || score === null || score === undefined) return '-';
  const formatted = Math.abs(score).toFixed(2);
  return score >= 0 ? `+${formatted}` : `-${formatted}`;
}

export function getScoreColorClass(score: number | null | undefined, isEmpty: boolean = false): string {
  if (isEmpty || score === null || score === undefined) return 'text-gray-500';
  if (score > 0) return 'text-sentiment-pos';
  if (score < 0) return 'text-sentiment-neg';
  return 'text-gray-500';
}