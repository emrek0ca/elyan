/**
 * VARLIK KATALOĞU — regex'in yerine geçen şey.
 *
 * Eski hâl: `/bitcoin|btc/`, `/ethereum|eth/`. İki coin. Üçüncüsünü eklemek
 * yeni bir desen yazmak demekti ve "Solana kaç TL" sessizce aramaya düşüyordu.
 * Burada varlıklar VERİ: yeni bir coin eklemek bir satırdır, yeni bir kural
 * değil. Eşleşme normalize edilmiş TOKEN üzerinden yapılır, desen üzerinden
 * değil — böylece Türkçe ekler ("bitcoin'in", "dolarla") kelimeyi bozmaz.
 */

/**
 * Türkçe duyarlı normalizasyon. `toLowerCase("I")` Türkçe'de "ı" üretir ve
 * ASCII eşleşmeyi bozar; bu yüzden önce Türkçe'ye özgü harfler sabitlenir.
 */
export function normalizeLookupText(value: string): string {
  return String(value ?? "")
    .replace(/İ/g, "i")
    .replace(/I/g, "i")
    .replace(/ı/g, "i")
    .toLowerCase()
    .replace(/[ğ]/g, "g")
    .replace(/[ü]/g, "u")
    .replace(/[ş]/g, "s")
    .replace(/[ö]/g, "o")
    .replace(/[ç]/g, "c")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Türkçe ek toleransıyla token üretir: "bitcoinin" → "bitcoin" adayını da
 * içerir. Tolerans SINIRLIDIR (en fazla 3 harf) — sınırsız kırpma "eth"i
 * "ethernet"ten ayıramaz hâle getirir.
 */
export function lookupTokens(prompt: string): Set<string> {
  const tokens = new Set<string>();
  for (const word of normalizeLookupText(prompt).split(" ")) {
    if (!word) continue;
    tokens.add(word);
    for (let cut = 1; cut <= 3 && word.length - cut >= 3; cut += 1) {
      tokens.add(word.slice(0, word.length - cut));
    }
  }
  return tokens;
}

export type CryptoAsset = { id: string; symbol: string; aliases: string[] };

/** CoinGecko `ids` alanıyla birebir uyumlu. Yeni coin = yeni satır. */
export const CRYPTO_ASSETS: CryptoAsset[] = [
  { id: "bitcoin", symbol: "BTC", aliases: ["bitcoin", "btc"] },
  { id: "ethereum", symbol: "ETH", aliases: ["ethereum", "ether", "eth"] },
  { id: "tether", symbol: "USDT", aliases: ["tether", "usdt"] },
  { id: "binancecoin", symbol: "BNB", aliases: ["binance", "binancecoin", "bnb"] },
  { id: "solana", symbol: "SOL", aliases: ["solana", "sol"] },
  { id: "ripple", symbol: "XRP", aliases: ["ripple", "xrp"] },
  { id: "cardano", symbol: "ADA", aliases: ["cardano", "ada"] },
  { id: "dogecoin", symbol: "DOGE", aliases: ["dogecoin", "doge"] },
  { id: "tron", symbol: "TRX", aliases: ["tron", "trx"] },
  { id: "avalanche-2", symbol: "AVAX", aliases: ["avalanche", "avax"] },
  { id: "chainlink", symbol: "LINK", aliases: ["chainlink", "link"] },
  { id: "polkadot", symbol: "DOT", aliases: ["polkadot", "dot"] },
  { id: "litecoin", symbol: "LTC", aliases: ["litecoin", "ltc"] },
  { id: "matic-network", symbol: "MATIC", aliases: ["polygon", "matic"] },
  { id: "shiba-inu", symbol: "SHIB", aliases: ["shiba", "shib"] },
];

export type FiatCurrency = { code: string; aliases: string[] };

/** Frankfurter (ECB) tarafından desteklenen para birimleri. */
export const FIAT_CURRENCIES: FiatCurrency[] = [
  { code: "USD", aliases: ["dolar", "usd", "amerikan"] },
  { code: "EUR", aliases: ["euro", "avro", "eur"] },
  { code: "GBP", aliases: ["sterlin", "gbp", "pound"] },
  { code: "CHF", aliases: ["frank", "isvicre", "chf"] },
  { code: "JPY", aliases: ["yen", "japon", "jpy"] },
  { code: "CNY", aliases: ["yuan", "cin", "cny"] },
  { code: "SEK", aliases: ["isvec", "krone", "sek"] },
  { code: "NOK", aliases: ["norvec", "nok"] },
  { code: "DKK", aliases: ["danimarka", "dkk"] },
  { code: "PLN", aliases: ["zloti", "polonya", "pln"] },
  { code: "CAD", aliases: ["kanada", "cad"] },
  { code: "AUD", aliases: ["avustralya", "aud"] },
  { code: "TRY", aliases: ["lira", "turk", "try", "tl"] },
];

export function matchCryptoAsset(prompt: string): CryptoAsset | null {
  const tokens = lookupTokens(prompt);
  for (const asset of CRYPTO_ASSETS) {
    if (asset.aliases.some((alias) => tokens.has(alias))) return asset;
  }
  return null;
}

/** TRY dışındaki ilk eşleşen para birimi — "dolar kaç TL" için kaynak taraf. */
export function matchForeignCurrency(prompt: string): FiatCurrency | null {
  const tokens = lookupTokens(prompt);
  for (const currency of FIAT_CURRENCIES) {
    if (currency.code === "TRY") continue;
    if (currency.aliases.some((alias) => tokens.has(alias))) return currency;
  }
  return null;
}
