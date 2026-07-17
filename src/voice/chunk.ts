/**
 * Split text into chunks no larger than maxChars, breaking on sentence boundaries
 * (then whitespace) so no word is cut. Used to stay under per-request TTS limits.
 */
export function chunkText(text: string, maxChars: number): string[] {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= maxChars) return clean ? [clean] : [];

  const sentences = clean.match(/[^.!?]+[.!?]*\s*/g) ?? [clean];
  const chunks: string[] = [];
  let cur = "";
  for (const s of sentences) {
    if ((cur + s).length > maxChars) {
      if (cur) chunks.push(cur.trim());
      if (s.length > maxChars) {
        // A single very long sentence: hard-split on spaces.
        const words = s.split(" ");
        cur = "";
        for (const w of words) {
          if ((cur + " " + w).length > maxChars) {
            chunks.push(cur.trim());
            cur = w;
          } else {
            cur = cur ? `${cur} ${w}` : w;
          }
        }
      } else {
        cur = s;
      }
    } else {
      cur += s;
    }
  }
  if (cur.trim()) chunks.push(cur.trim());
  return chunks;
}
