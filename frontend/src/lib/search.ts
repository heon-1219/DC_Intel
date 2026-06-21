const HANGUL = /[ㄱ-ㆎ가-힣]/;

/** Min 2 chars, but 1 is allowed if it is a Hangul syllable/jamo (Korean tickers searched by
 *  name, e.g. "삼") — ui-ux §6.1. */
export function minCharsOk(q: string): boolean {
  const trimmed = q.trim();
  if (trimmed.length >= 2) return true;
  return trimmed.length === 1 && HANGUL.test(trimmed);
}
