"""
ELYAN Advanced Turkish NLP - Phase 7
Agglutination handling, vowel harmony, suffix analysis, NER, dependency parsing.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class VowelType(Enum):
    FRONT = "front"
    BACK = "back"
    ROUNDED = "rounded"
    UNROUNDED = "unrounded"


class SuffixType(Enum):
    NOUN_CASE = "noun_case"
    NOUN_PLURAL = "noun_plural"
    NOUN_POSSESSIVE = "noun_possessive"
    VERB_TENSE = "verb_tense"
    VERB_PERSON = "verb_person"
    VERB_NEGATION = "verb_negation"
    VERB_ABILITY = "verb_ability"
    VERB_CAUSATIVE = "verb_causative"
    VERB_PASSIVE = "verb_passive"
    DERIVATIONAL = "derivational"
    QUESTION = "question"


class EntityType(Enum):
    PERSON = "person"
    LOCATION = "location"
    ORGANIZATION = "organization"
    DATE = "date"
    TIME = "time"
    MONEY = "money"
    PERCENT = "percent"
    PRODUCT = "product"
    EVENT = "event"
    LANGUAGE = "language"


@dataclass
class MorphemeAnalysis:
    word: str
    root: str
    suffixes: List[Dict[str, str]]
    pos: str = ""
    is_compound: bool = False
    vowel_harmony_valid: bool = True


@dataclass
class NamedEntity:
    text: str
    entity_type: EntityType
    start: int
    end: int
    confidence: float = 0.0


@dataclass
class DependencyNode:
    word: str
    index: int
    head_index: int
    relation: str
    pos: str = ""


# Turkish vowel classification
FRONT_VOWELS = set("eEiIöÖüÜ")
BACK_VOWELS = set("aAıIoOuU")
ROUNDED_VOWELS = set("oOöÖuUüÜ")
UNROUNDED_VOWELS = set("aAeEıIiI")
ALL_VOWELS = FRONT_VOWELS | BACK_VOWELS

# Common Turkish suffixes
TURKISH_SUFFIXES = {
    SuffixType.NOUN_CASE: [
        ("da", "de", "ta", "te"),   # locative
        ("dan", "den", "tan", "ten"),  # ablative
        ("a", "e", "ya", "ye"),     # dative
        ("ı", "i", "u", "ü"),      # accusative
        ("ın", "in", "un", "ün"),   # genitive
        ("la", "le"),               # instrumental
    ],
    SuffixType.NOUN_PLURAL: [
        ("lar", "ler"),
    ],
    SuffixType.NOUN_POSSESSIVE: [
        ("ım", "im", "um", "üm"),  # 1st sg
        ("ın", "in", "un", "ün"),   # 2nd sg
        ("ı", "i", "u", "ü"),      # 3rd sg
        ("ımız", "imiz", "umuz", "ümüz"),  # 1st pl
        ("ınız", "iniz", "unuz", "ünüz"),  # 2nd pl
        ("ları", "leri"),           # 3rd pl
    ],
    SuffixType.VERB_TENSE: [
        ("yor",),                   # present continuous
        ("dı", "di", "du", "dü", "tı", "ti", "tu", "tü"),  # past definite
        ("mış", "miş", "muş", "müş"),  # past indefinite
        ("acak", "ecek"),           # future
        ("r", "ar", "er", "ır", "ir", "ur", "ür"),  # aorist
    ],
    SuffixType.VERB_NEGATION: [
        ("ma", "me"),
    ],
    SuffixType.VERB_ABILITY: [
        ("abil", "ebil"),
    ],
    SuffixType.VERB_PERSON: [
        ("ım", "im", "um", "üm"),  # 1st sg
        ("sın", "sin", "sun", "sün"),  # 2nd sg
        ("ız", "iz", "uz", "üz"),  # 1st pl
        ("sınız", "siniz", "sunuz", "sünüz"),  # 2nd pl
        ("lar", "ler"),            # 3rd pl
    ],
    SuffixType.QUESTION: [
        ("mı", "mi", "mu", "mü"),
    ],
}

# Turkish cities and landmarks for NER
TURKISH_LOCATIONS = {
    "istanbul", "ankara", "izmir", "bursa", "antalya", "adana", "konya",
    "gaziantep", "mersin", "diyarbakir", "kayseri", "eskisehir", "samsun",
    "trabzon", "erzurum", "malatya", "elazig", "van", "urfa", "mardin",
    "karadeniz", "akdeniz", "ege", "marmara", "anadolu", "trakya",
    "bogazici", "galata", "besiktas", "kadikoy", "uskudar", "beyoglu",
}

TURKISH_ORGANIZATIONS = {
    "tbmm", "cumhurbaskanligi", "bakanlik", "belediye", "universite",
    "holding", "banka", "vakif", "dernegi", "sirketi", "anonim",
    "limited", "kooperatif", "odasi", "birligi", "federasyonu",
}

TURKISH_PERSON_TITLES = {
    "bey", "hanim", "efendi", "pasa", "sultan", "prof", "doc", "dr",
    "av", "muh", "ogretmen", "hemshire", "uzman",
}

TURKISH_TIME_WORDS = {
    "bugun", "yarin", "dun", "simdi", "sonra", "once", "sabah", "aksam",
    "gece", "ogle", "hafta", "ay", "yil", "saat", "dakika", "saniye",
    "pazartesi", "sali", "carsamba", "persembe", "cuma", "cumartesi", "pazar",
    "ocak", "subat", "mart", "nisan", "mayis", "haziran",
    "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik",
}

TURKISH_STOPWORDS = {
    "bir", "bu", "su", "o", "ve", "ile", "de", "da", "ki", "mi", "mu",
    "ama", "fakat", "ancak", "lakin", "yoksa", "ya", "hem", "ne", "ise",
    "icin", "gibi", "kadar", "daha", "en", "cok", "az", "her", "bazi",
    "tum", "butun", "hep", "hic", "sadece", "bile", "dahi", "zaten",
    "artik", "henuz", "yine", "tekrar", "asla", "kesinlikle",
}


class VowelHarmonyAnalyzer:
    """Analyzes and validates Turkish vowel harmony rules."""

    @staticmethod
    def get_last_vowel(word: str) -> Optional[str]:
        for ch in reversed(word.lower()):
            if ch in "aeıioöuü":
                return ch
        return None

    @staticmethod
    def is_front(vowel: str) -> bool:
        return vowel.lower() in "eiöü"

    @staticmethod
    def is_back(vowel: str) -> bool:
        return vowel.lower() in "aıou"

    @staticmethod
    def is_rounded(vowel: str) -> bool:
        return vowel.lower() in "oöuü"

    def check_two_way(self, root: str, suffix: str) -> bool:
        """Check two-way (e/a) vowel harmony."""
        last_vowel = self.get_last_vowel(root)
        if last_vowel is None:
            return True
        suffix_vowel = self.get_last_vowel(suffix)
        if suffix_vowel is None:
            return True
        if self.is_front(last_vowel):
            return self.is_front(suffix_vowel)
        return self.is_back(suffix_vowel)

    def check_four_way(self, root: str, suffix: str) -> bool:
        """Check four-way (ı/i/u/ü) vowel harmony."""
        last_vowel = self.get_last_vowel(root)
        if last_vowel is None:
            return True
        suffix_vowel = self.get_last_vowel(suffix)
        if suffix_vowel is None:
            return True
        if self.is_front(last_vowel) and self.is_rounded(last_vowel):
            return suffix_vowel == "ü"
        if self.is_front(last_vowel) and not self.is_rounded(last_vowel):
            return suffix_vowel == "i"
        if self.is_back(last_vowel) and self.is_rounded(last_vowel):
            return suffix_vowel == "u"
        if self.is_back(last_vowel) and not self.is_rounded(last_vowel):
            return suffix_vowel in ("ı", "a")
        return True

    def validate_word(self, word: str) -> bool:
        """Check if a word follows vowel harmony throughout."""
        vowels = [ch for ch in word.lower() if ch in "aeıioöuü"]
        if len(vowels) <= 1:
            return True
        for i in range(1, len(vowels)):
            prev = vowels[i - 1]
            curr = vowels[i]
            if self.is_front(prev) and self.is_back(curr):
                return False
            if self.is_back(prev) and self.is_front(curr):
                return False
        return True


class AgglutinationAnalyzer:
    """Analyzes Turkish agglutinative morphology."""

    def __init__(self):
        self.harmony = VowelHarmonyAnalyzer()
        self._suffix_patterns = self._build_suffix_patterns()

    def _build_suffix_patterns(self) -> List[Tuple[str, SuffixType, str]]:
        patterns = []
        for suffix_type, variants in TURKISH_SUFFIXES.items():
            for group in variants:
                for suffix in group:
                    patterns.append((suffix, suffix_type, suffix))
        patterns.sort(key=lambda x: len(x[0]), reverse=True)
        return patterns

    def analyze(self, word: str) -> MorphemeAnalysis:
        word_lower = word.lower()
        suffixes_found = []
        remaining = word_lower
        for suffix_text, suffix_type, raw_suffix in self._suffix_patterns:
            if len(remaining) > len(suffix_text) + 1 and remaining.endswith(suffix_text):
                suffixes_found.append({
                    "suffix": raw_suffix,
                    "type": suffix_type.value,
                })
                remaining = remaining[: -len(suffix_text)]
        suffixes_found.reverse()
        harmony_valid = self.harmony.validate_word(word_lower)
        return MorphemeAnalysis(
            word=word,
            root=remaining,
            suffixes=suffixes_found,
            vowel_harmony_valid=harmony_valid,
        )

    def get_root(self, word: str) -> str:
        analysis = self.analyze(word)
        return analysis.root

    def get_suffix_chain(self, word: str) -> List[str]:
        analysis = self.analyze(word)
        return [s["suffix"] for s in analysis.suffixes]


class TurkishNER:
    """Turkish Named Entity Recognition using rule-based + pattern matching."""

    def __init__(self):
        self._custom_entities: Dict[EntityType, Set[str]] = {
            EntityType.LOCATION: TURKISH_LOCATIONS,
            EntityType.ORGANIZATION: TURKISH_ORGANIZATIONS,
        }

    def extract(self, text: str) -> List[NamedEntity]:
        entities = []
        entities.extend(self._extract_locations(text))
        entities.extend(self._extract_dates(text))
        entities.extend(self._extract_money(text))
        entities.extend(self._extract_percentages(text))
        entities.extend(self._extract_persons(text))
        entities.extend(self._extract_organizations(text))
        entities.extend(self._extract_times(text))
        seen = set()
        unique = []
        for ent in entities:
            key = (ent.text.lower(), ent.entity_type, ent.start)
            if key not in seen:
                seen.add(key)
                unique.append(ent)
        return sorted(unique, key=lambda e: e.start)

    def _extract_locations(self, text: str) -> List[NamedEntity]:
        entities = []
        words = text.lower().split()
        for i, word in enumerate(words):
            clean = re.sub(r"[^a-zçğıöşü]", "", word)
            if clean in TURKISH_LOCATIONS:
                start = text.lower().find(clean)
                entities.append(NamedEntity(
                    text=clean, entity_type=EntityType.LOCATION,
                    start=start, end=start + len(clean), confidence=0.9,
                ))
        return entities

    def _extract_dates(self, text: str) -> List[NamedEntity]:
        entities = []
        date_pattern = r"\b(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})\b"
        for m in re.finditer(date_pattern, text):
            entities.append(NamedEntity(
                text=m.group(), entity_type=EntityType.DATE,
                start=m.start(), end=m.end(), confidence=0.95,
            ))
        turkish_date = r"\b(\d{1,2})\s+(ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)\b"
        for m in re.finditer(turkish_date, text.lower()):
            entities.append(NamedEntity(
                text=m.group(), entity_type=EntityType.DATE,
                start=m.start(), end=m.end(), confidence=0.9,
            ))
        return entities

    def _extract_money(self, text: str) -> List[NamedEntity]:
        entities = []
        money_patterns = [
            r"\b(\d+(?:[.,]\d+)?)\s*(TL|tl|lira|dolar|euro|EUR|USD|₺|\$|€)\b",
            r"(₺|\$|€)\s*(\d+(?:[.,]\d+)?)\b",
        ]
        for pat in money_patterns:
            for m in re.finditer(pat, text):
                entities.append(NamedEntity(
                    text=m.group(), entity_type=EntityType.MONEY,
                    start=m.start(), end=m.end(), confidence=0.95,
                ))
        return entities

    def _extract_percentages(self, text: str) -> List[NamedEntity]:
        entities = []
        pct_patterns = [
            r"%\s*(\d+(?:[.,]\d+)?)",
            r"(\d+(?:[.,]\d+)?)\s*%",
            r"yuzde\s+(\d+)",
        ]
        for pat in pct_patterns:
            for m in re.finditer(pat, text.lower()):
                entities.append(NamedEntity(
                    text=m.group(), entity_type=EntityType.PERCENT,
                    start=m.start(), end=m.end(), confidence=0.9,
                ))
        return entities

    def _extract_persons(self, text: str) -> List[NamedEntity]:
        entities = []
        words = text.split()
        for i, word in enumerate(words):
            clean = word.lower().rstrip(".,;:!?")
            if clean in TURKISH_PERSON_TITLES and i + 1 < len(words):
                name = words[i + 1].rstrip(".,;:!?")
                full = f"{word} {words[i + 1]}"
                start = text.find(full)
                if start >= 0:
                    entities.append(NamedEntity(
                        text=full.strip(".,;:!?"),
                        entity_type=EntityType.PERSON,
                        start=start, end=start + len(full),
                        confidence=0.8,
                    ))
        return entities

    def _extract_organizations(self, text: str) -> List[NamedEntity]:
        entities = []
        words = text.lower().split()
        for i, word in enumerate(words):
            clean = re.sub(r"[^a-zçğıöşü]", "", word)
            if clean in TURKISH_ORGANIZATIONS:
                start = text.lower().find(clean)
                entities.append(NamedEntity(
                    text=clean, entity_type=EntityType.ORGANIZATION,
                    start=start, end=start + len(clean), confidence=0.7,
                ))
        return entities

    def _extract_times(self, text: str) -> List[NamedEntity]:
        entities = []
        time_pattern = r"\b(\d{1,2})[:.:](\d{2})\b"
        for m in re.finditer(time_pattern, text):
            hour = int(m.group(1))
            minute = int(m.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                entities.append(NamedEntity(
                    text=m.group(), entity_type=EntityType.TIME,
                    start=m.start(), end=m.end(), confidence=0.85,
                ))
        return entities

    def add_custom_entities(self, entity_type: EntityType, entities: Set[str]):
        if entity_type not in self._custom_entities:
            self._custom_entities[entity_type] = set()
        self._custom_entities[entity_type].update(entities)


class TurkishDependencyParser:
    """Rule-based Turkish dependency parsing."""

    POS_PATTERNS = {
        "NOUN": re.compile(r"^[A-ZÇĞIİÖŞÜ][a-zçğıiöşü]+$"),
        "VERB": re.compile(r".*(mak|mek|yor|dı|di|du|dü|mış|miş|muş|müş|acak|ecek)$", re.IGNORECASE),
        "ADJ": re.compile(r".*(lı|li|lu|lü|sız|siz|suz|süz|sal|sel|ik|ak)$", re.IGNORECASE),
        "ADV": re.compile(r"^(cok|az|hizla|yavas|hemen|simdi|sonra|once)$", re.IGNORECASE),
        "DET": re.compile(r"^(bir|bu|su|o|her|bazi|tum|butun|birkac)$", re.IGNORECASE),
        "PRON": re.compile(r"^(ben|sen|o|biz|siz|onlar|bu|su|kendisi)$", re.IGNORECASE),
        "CONJ": re.compile(r"^(ve|veya|ama|fakat|ancak|lakin|hem|ne|ya)$", re.IGNORECASE),
        "POSTP": re.compile(r"^(icin|ile|gibi|kadar|gore|dolayi|ragmen)$", re.IGNORECASE),
    }

    def parse(self, sentence: str) -> List[DependencyNode]:
        words = sentence.split()
        nodes = []
        verb_index = -1
        for i, word in enumerate(words):
            pos = self._detect_pos(word)
            if pos == "VERB":
                verb_index = i
            nodes.append(DependencyNode(
                word=word, index=i, head_index=-1, relation="root", pos=pos,
            ))
        if verb_index >= 0:
            nodes[verb_index].head_index = -1
            nodes[verb_index].relation = "root"
            for i, node in enumerate(nodes):
                if i == verb_index:
                    continue
                node.head_index = verb_index
                if node.pos == "NOUN":
                    node.relation = "nsubj" if i < verb_index else "obj"
                elif node.pos == "ADJ":
                    next_noun = self._find_next_noun(nodes, i)
                    if next_noun >= 0:
                        node.head_index = next_noun
                        node.relation = "amod"
                    else:
                        node.relation = "advmod"
                elif node.pos == "ADV":
                    node.relation = "advmod"
                elif node.pos == "DET":
                    next_noun = self._find_next_noun(nodes, i)
                    if next_noun >= 0:
                        node.head_index = next_noun
                        node.relation = "det"
                elif node.pos == "CONJ":
                    node.relation = "cc"
                elif node.pos == "POSTP":
                    node.relation = "case"
                else:
                    node.relation = "dep"
        elif nodes:
            nodes[-1].head_index = -1
            nodes[-1].relation = "root"
            for i in range(len(nodes) - 1):
                nodes[i].head_index = len(nodes) - 1
                nodes[i].relation = "dep"
        return nodes

    def _detect_pos(self, word: str) -> str:
        for pos, pattern in self.POS_PATTERNS.items():
            if pattern.match(word):
                return pos
        return "NOUN"

    @staticmethod
    def _find_next_noun(nodes: List[DependencyNode], start: int) -> int:
        for i in range(start + 1, len(nodes)):
            if nodes[i].pos == "NOUN":
                return i
        return -1


class SemanticSimilarity:
    """Turkish semantic similarity using keyword overlap and morphological analysis."""

    def __init__(self):
        self.agglutination = AgglutinationAnalyzer()

    def similarity(self, text1: str, text2: str) -> float:
        roots1 = self._extract_roots(text1)
        roots2 = self._extract_roots(text2)
        if not roots1 or not roots2:
            return 0.0
        intersection = roots1 & roots2
        union = roots1 | roots2
        jaccard = len(intersection) / len(union) if union else 0.0
        len_ratio = min(len(roots1), len(roots2)) / max(len(roots1), len(roots2))
        return round(jaccard * 0.7 + len_ratio * 0.3, 4)

    def _extract_roots(self, text: str) -> Set[str]:
        words = text.lower().split()
        roots = set()
        for word in words:
            clean = re.sub(r"[^a-zçğıiöşü0-9]", "", word)
            if clean and clean not in TURKISH_STOPWORDS and len(clean) > 1:
                root = self.agglutination.get_root(clean)
                if root:
                    roots.add(root)
        return roots

    def find_most_similar(self, query: str, candidates: List[str], top_k: int = 5) -> List[Tuple[str, float]]:
        scored = [(c, self.similarity(query, c)) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


class CodeSwitchDetector:
    """Detect and handle Turkish-English code-switching."""

    ENGLISH_INDICATORS = {
        "the", "is", "are", "was", "were", "have", "has", "had", "will",
        "can", "could", "would", "should", "this", "that", "these", "those",
        "from", "with", "about", "into", "through", "during", "before", "after",
        "please", "thanks", "sorry", "hello", "yes", "no", "ok", "okay",
    }

    TURKISH_INDICATORS = {
        "bir", "bu", "su", "ve", "ile", "icin", "gibi", "kadar", "ama",
        "fakat", "daha", "cok", "az", "var", "yok", "evet", "hayir",
        "tamam", "lutfen", "tesekkur", "merhaba", "nasil", "nerede",
        "ne", "kim", "neden", "niye", "zaman", "hani", "bence", "galiba",
    }

    def detect(self, text: str) -> Dict[str, Any]:
        words = text.lower().split()
        clean_words = [re.sub(r"[^a-zçğıiöşü]", "", w) for w in words]
        clean_words = [w for w in clean_words if w]
        if not clean_words:
            return {"language": "unknown", "confidence": 0.0, "is_mixed": False}
        turkish_count = sum(1 for w in clean_words if w in self.TURKISH_INDICATORS)
        english_count = sum(1 for w in clean_words if w in self.ENGLISH_INDICATORS)
        # Check for Turkish-specific characters
        has_turkish_chars = bool(re.search(r"[çğıöşü]", text.lower()))
        if has_turkish_chars:
            turkish_count += 2
        total = turkish_count + english_count
        if total == 0:
            return {
                "language": "turkish" if has_turkish_chars else "unknown",
                "confidence": 0.5,
                "is_mixed": False,
                "turkish_ratio": 0.5,
                "english_ratio": 0.5,
            }
        tr_ratio = turkish_count / total
        en_ratio = english_count / total
        is_mixed = tr_ratio > 0.2 and en_ratio > 0.2
        lang = "turkish" if tr_ratio >= en_ratio else "english"
        confidence = max(tr_ratio, en_ratio)
        return {
            "language": "mixed" if is_mixed else lang,
            "confidence": round(confidence, 3),
            "is_mixed": is_mixed,
            "turkish_ratio": round(tr_ratio, 3),
            "english_ratio": round(en_ratio, 3),
        }


class TurkishNLPEngine:
    """Unified Turkish NLP engine combining all components."""

    def __init__(self):
        self.morphology = AgglutinationAnalyzer()
        self.harmony = VowelHarmonyAnalyzer()
        self.ner = TurkishNER()
        self.parser = TurkishDependencyParser()
        self.similarity = SemanticSimilarity()
        self.code_switch = CodeSwitchDetector()

    def analyze(self, text: str) -> Dict[str, Any]:
        lang_info = self.code_switch.detect(text)
        entities = self.ner.extract(text)
        words = text.split()
        morphology = [self.morphology.analyze(w) for w in words[:20]]
        deps = self.parser.parse(text) if len(words) <= 50 else []
        return {
            "text": text,
            "language": lang_info,
            "entities": [
                {
                    "text": e.text,
                    "type": e.entity_type.value,
                    "start": e.start,
                    "end": e.end,
                    "confidence": e.confidence,
                }
                for e in entities
            ],
            "morphology": [
                {
                    "word": m.word,
                    "root": m.root,
                    "suffixes": m.suffixes,
                    "harmony_valid": m.vowel_harmony_valid,
                }
                for m in morphology
            ],
            "dependencies": [
                {
                    "word": d.word,
                    "index": d.index,
                    "head": d.head_index,
                    "relation": d.relation,
                    "pos": d.pos,
                }
                for d in deps
            ],
            "word_count": len(words),
            "entity_count": len(entities),
        }

    def get_roots(self, text: str) -> List[str]:
        words = text.split()
        return [self.morphology.get_root(w) for w in words]

    def check_harmony(self, word: str) -> bool:
        return self.harmony.validate_word(word)

    def find_entities(self, text: str) -> List[NamedEntity]:
        return self.ner.extract(text)

    def compute_similarity(self, text1: str, text2: str) -> float:
        return self.similarity.similarity(text1, text2)


_turkish_nlp: Optional[TurkishNLPEngine] = None


def get_turkish_nlp() -> TurkishNLPEngine:
    global _turkish_nlp
    if _turkish_nlp is None:
        _turkish_nlp = TurkishNLPEngine()
    return _turkish_nlp
