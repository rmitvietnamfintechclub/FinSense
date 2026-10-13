export function formatScore(score: number | null | undefined, isEmpty: boolean = false): string {
  if (isEmpty || score === null || score === undefined) return '-';
  
  const formatted = Math.abs(score).toFixed(2);
  return score >= 0 ? `+${formatted}` : `-${formatted}`;
}

export function getScoreColorClass(score: number | null | undefined, isEmpty: boolean = false): string {
  if (isEmpty || score === null || score === undefined) return 'text-gray-500'; // No data
  if (score > 0) return 'text-sentiment-pos';
  if (score < 0) return 'text-sentiment-neg';
  return 'text-gray-500'; // Neutral (0.00)
}

export function formatTime(isoString: string | null | undefined): string {
  if (!isoString) return '--:--';
  // Always dated: a bare time can't tell "today" from a pipeline that stopped days ago.
  return new Date(isoString).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  });
}