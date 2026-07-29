/**
 * The single authority on turning a Turkish/English self-introduction into a
 * personal name.
 *
 * Why one module: the write path (`preference-extractor.ts`) and the read path
 * (`context-builder.ts`) each grew their own regex and their own tiny stop-word
 * list, and neither knew the words the other rejected. "Benim adım bundan sonra
 * Osman" slipped through both — the capture group swallowed "bundan sonra" and
 * the stop lists contained neither word, so the user was greeted as "bundan"
 * for a day. Two half-lists are worse than one complete one, because each looks
 * done from where it stands.
 *
 * Structure over patterns (NEREDE-KALDIK.md §1): rather than enumerating more
 * sentences, this strips *discourse* material ("from now on", "let it be") and
 * then refuses any candidate containing a Turkish function word. Function words
 * never occur inside Turkish given names, so the reject list is closed and
 * small — unlike the open-ended list of sentence shapes.
 */

/**
 * Leading discourse phrases that precede the actual name in a renaming
 * sentence. Stripped repeatedly so stacked forms ("bundan sonra artık") fall
 * away too.
 */
const NAME_DISCOURSE_PREFIX =
  /^(?:bundan\s+(?:sonra|böyle|boyle)|şu\s+andan\s+itibaren|su\s+andan\s+itibaren|artık|artik|from\s+now\s+on|going\s+forward)\s+/iu;

/**
 * Trailing verb material a renaming sentence ends with ("... Osman olsun",
 * "... Osman diyebilirsin").
 */
const NAME_TRAILING_VERB =
  /\s+(?:olsun|olacak|de|deyin|diyebilirsin|diyebilirsiniz|çağır|cagir|seslen)\s*$/iu;

/**
 * Turkish/English function words that cannot be part of a given name. A closed
 * class: pronouns, conjunctions, postpositions, discourse markers. Any
 * candidate containing one is a mis-parse, not an unusual name.
 */
const NAME_FUNCTION_WORDS = new Set([
  // Discourse / time
  "bundan", "sonra", "böyle", "boyle", "önce", "once", "artık", "artik",
  "itibaren", "şimdi", "simdi", "bugün", "bugun", "yarın", "yarin",
  // Pronouns / determiners
  "ben", "benim", "sen", "senin", "o", "onun", "bu", "şu", "su", "bana",
  "sana", "beni", "seni", "bunu", "şunu", "sunu", "kendi", "her", "hiç", "hic",
  // Conjunctions / particles
  "ve", "veya", "ama", "ancak", "çünkü", "cunku", "yani", "ki", "de", "da",
  "ile", "için", "icin", "gibi", "kadar", "diye", "mi", "mı", "mu", "mü",
  // Degree particles — "En" was once stored as the user's name, almost
  // certainly captured from "bana en kısa yoldan..."-shaped sentences.
  "en", "daha", "pek", "çok", "cok", "az",
  // Verbs common in renaming sentences
  "olsun", "olacak", "değil", "degil", "var", "yok", "istiyorum", "isterim",
  // Address / greeting words that leak from the sentence
  "adım", "adim", "isim", "ismim", "merhaba", "selam", "hey", "lütfen",
  "lutfen",
  // English equivalents
  "the", "a", "an", "my", "your", "name", "is", "call", "me", "from", "now",
  "on", "please", "and", "or", "but",
]);

/**
 * Extraction-time cleanup: remove renaming-sentence scaffolding around the
 * name. Returns the trimmed candidate; validity is `isValidPersonalName`'s job.
 */
export function stripNameDiscourse(raw: string): string {
  let value = raw.replace(/\s+/g, " ").trim();
  // Repeat: "bundan sonra artık Osman" sheds one prefix per pass.
  for (let pass = 0; pass < 3; pass += 1) {
    const next = value.replace(NAME_DISCOURSE_PREFIX, "");
    if (next === value) break;
    value = next;
  }
  return value.replace(NAME_TRAILING_VERB, "").trim();
}

/**
 * Whether a cleaned candidate can be a personal name. Shared by write and read
 * paths so a name rejected on one side can never be accepted on the other.
 */
export function isValidPersonalName(candidate: string): boolean {
  const compact = candidate.replace(/\s+/g, " ").trim();
  if (!compact || compact.length > 48) return false;
  const parts = compact.split(" ");
  if (parts.length > 3) return false;
  for (const part of parts) {
    if (part.length < 2 || part.length > 24) return false;
    if (!/^[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü'-]*$/u.test(part)) {
      return false;
    }
    if (NAME_FUNCTION_WORDS.has(part.toLocaleLowerCase("tr-TR"))) {
      return false;
    }
  }
  return true;
}

/**
 * Full pipeline: strip discourse, validate, title-case. Null means "this
 * sentence does not contain a usable name" — the caller must not fall back to
 * a looser parse of the same text.
 */
export function normalizePersonalName(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const stripped = stripNameDiscourse(String(raw));
  if (!isValidPersonalName(stripped)) return null;
  return stripped
    .split(" ")
    .map(
      (part) =>
        part.charAt(0).toLocaleUpperCase("tr-TR") +
        part.slice(1).toLocaleLowerCase("tr-TR"),
    )
    .join(" ");
}
