/**
 * Character bible for the "Giggle Grove" channel.
 *
 * This is the fixed creative context handed to Gemini for EVERY episode so that
 * scripts stay consistent (brief's "recurring cast + pillar element" requirement).
 *
 * EDIT ME: change the channel name, characters, catchphrases, or sign-off here and
 * every future generated script follows the new bible. Nothing else needs to change.
 */

export interface Character {
  name: string;
  species: string;
  appearance: string;
  personality: string;
  catchphrase: string;
}
export interface ChannelBible {
  channelName: string;
  audience: string;
  tone: string;
  characters: Character[];
  /** The recurring "pillar" element every episode must end with. */
  signOff: string;
  /** Extra production/style rules the model should always follow. */
  rules: string[];
}

export const BIBLE: ChannelBible = {
  channelName: "Giggle Grove",
  audience: "toddlers and preschoolers (ages 2–5)",
  tone: "warm, gentle, upbeat, and encouraging — never scary or sarcastic",
  characters: [
    {
      name: "Milo",
      species: "young fox cub",
      appearance: "bright orange fur, a blue scarf, a bushy tail, big round eyes",
      personality: "energetic, curious, and eager; sometimes rushes ahead and learns to slow down",
      catchphrase: "Let's find out!",
    },
    {
      name: "Lulu",
      species: "wise owl",
      appearance: "soft purple feathers, round golden glasses, perched calmly",
      personality: "calm, patient, kind, and gently encouraging; the reassuring teacher",
      catchphrase: "Great thinking!",
    },
  ],
  signOff:
    'Every episode ends with the "Giggle Grove Goodbye": Milo and Lulu wave together and sing a short, ' +
    "two-line goodbye song inviting kids to come back next time.",
  rules: [
    "Keep sentences short and simple; repeat key words so toddlers can follow along.",
    "Milo asks questions; Lulu explains gently. Learning happens through their friendly dialogue.",
    "Include 2–3 moments that invite the viewer to participate (e.g. 'Can you say it with me?').",
    "No violence, no scary themes, no ads or product mentions, no complex vocabulary.",
    "Reinforce the episode's lesson clearly near the end before the sign-off.",
  ],
};

/** Render the bible as a plain-text block for injection into prompts. */
export function bibleAsPrompt(bible: ChannelBible = BIBLE): string {
  const chars = bible.characters
    .map(
      (c) =>
        `- ${c.name} (${c.species}): ${c.appearance}. Personality: ${c.personality}. Catchphrase: "${c.catchphrase}".`,
    )
    .join("\n");
  const rules = bible.rules.map((r) => `- ${r}`).join("\n");
  return [
    `CHANNEL: ${bible.channelName}`,
    `AUDIENCE: ${bible.audience}`,
    `TONE: ${bible.tone}`,
    ``,
    `RECURRING CAST:`,
    chars,
    ``,
    `SIGN-OFF (must appear at the end of every episode):`,
    bible.signOff,
    ``,
    `PRODUCTION RULES:`,
    rules,
  ].join("\n");
}
