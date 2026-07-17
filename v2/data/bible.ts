// Character bible — the fixed creative context handed to Gemini for every episode.
// EDIT this to rebrand; every future script follows it.
export const BIBLE = {
  channel: "Giggle Grove",
  audience: "toddlers and preschoolers (ages 2–5)",
  tone: "warm, gentle, upbeat, encouraging — never scary or sarcastic",
  characters: [
    {
      name: "Milo",
      who: "an energetic young fox cub — orange fur, blue scarf, bushy tail",
      trait: "curious and enthusiastic; asks lots of questions",
      catchphrase: "Let's find out!",
    },
    {
      name: "Lulu",
      who: "a calm, wise owl — purple feathers, round glasses",
      trait: "patient, kind teacher who explains gently",
      catchphrase: "Great thinking!",
    },
  ],
  signOff:
    'Every episode ends with the "Giggle Grove Goodbye": Milo and Lulu wave and sing a ' +
    "short two-line goodbye inviting kids back next time.",
  rules: [
    "Short, simple sentences; repeat key words so toddlers follow along.",
    "Milo asks; Lulu explains. Learning happens through their friendly dialogue.",
    "Include 2–3 participation moments (e.g. 'Can you say it with me?').",
    "No violence, scary themes, ads, or complex vocabulary.",
    "Reinforce the lesson clearly near the end, before the sign-off.",
  ],
} as const;

export function bibleText(): string {
  const chars = BIBLE.characters
    .map((c) => `- ${c.name}: ${c.who}. ${c.trait}. Catchphrase: "${c.catchphrase}".`)
    .join("\n");
  const rules = BIBLE.rules.map((r) => `- ${r}`).join("\n");
  return [
    `CHANNEL: ${BIBLE.channel}`,
    `AUDIENCE: ${BIBLE.audience}`,
    `TONE: ${BIBLE.tone}`,
    ``,
    `CAST:`,
    chars,
    ``,
    `SIGN-OFF (end every episode with this): ${BIBLE.signOff}`,
    ``,
    `RULES:`,
    rules,
  ].join("\n");
}
