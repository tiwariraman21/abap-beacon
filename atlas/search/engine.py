"""Hybrid search over stored objects.

Ranking model (keyword side)
  1. Tokens are split into *content* terms and *type-hint* terms
     ("interface", "class", "report", "table"...). Hint terms are not
     expanded with synonyms and carry little content weight; instead they
     boost objects whose type or tags match the hint. "salesorder interface"
     therefore means: things about sales orders, preferably interfaces.
  2. Compounds are split both ways using the corpus vocabulary:
     "salesorder" ~ "sales order", "flightbooking" ~ "flight booking".
  3. BM25 (b=0.5, less bias toward tiny objects) over a weighted document.
  4. Coverage: objects matching more of the content terms rank higher.
  5. Boosts when a content term hits the object NAME or SAP short text -
     the strongest signals a developer can give.
Semantic side: cosine similarity from the index; its weight depends on the
backend quality (MiniLM/model2vec full weight, TF-IDF fallback reduced).
Results collapse to one entry per object and carry matching components.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from atlas.db.models import SapObject, System
from atlas.ingest.types import get_type
from atlas.search import synonyms
from atlas.search.semantic import SemanticIndex, load_index

STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "can", "code", "do", "does", "for",
    "from", "get", "has", "have", "how", "i", "in", "into", "is", "it", "me", "my", "need", "of",
    "on", "or", "some", "that", "the", "their", "them", "then", "there", "this", "to", "up",
    "use", "used", "using", "via", "want", "was", "we", "what", "when", "where", "which", "who",
    "will", "with", "would", "you", "your", "object", "objects", "something", "abap", "sap",
    "custom", "existing", "already", "find", "show", "give", "all", "one", "new",
}

# Words that describe WHAT KIND of object rather than what it does. Each maps to
# object types and tag fragments that satisfy the hint.
TYPE_HINTS: dict[str, tuple[set[str], tuple[str, ...]]] = {
    "interface": ({"INTF", "SPRX", "IWSV", "IWPR", "IWMO", "IWSG", "WEBI", "IDOC", "IEXT"}, ("interface", "odata", "api", "idoc", "proxy", "integration", "inbound", "outbound", "rest")),
    "api": ({"IWSV", "IWPR", "IWMO", "WEBI", "SPRX", "SRVD", "SRVB"}, ("api", "odata", "rest", "http", "bapi", "integration", "service")),
    "service": ({"IWSV", "IWPR", "SRVD", "SRVB", "WEBI"}, ("odata", "service", "api", "rest")),
    "odata": ({"IWSV", "IWPR", "IWMO", "SRVD", "SRVB"}, ("odata", "gateway", "data provider", "model provider")),
    "class": ({"CLAS"}, ("class",)),
    "program": ({"PROG"}, ("program",)),
    "report": ({"PROG"}, ("report", "alv", "program")),
    "include": ({"PROG"}, ("include",)),
    "table": ({"TABL", "TTYP", "VIEW"}, ("table", "structure")),
    "structure": ({"TABL"}, ("structure",)),
    "view": ({"DDLS", "VIEW"}, ("cds", "view")),
    "cds": ({"DDLS", "DCLS", "DDLX"}, ("cds",)),
    "function": ({"FUGR"}, ("function",)),
    "fm": ({"FUGR"}, ("function",)),
    "exception": ({"CLAS"}, ("exception",)),
    "element": ({"DTEL", "DOMA"}, ("data element", "domain")),
    "domain": ({"DOMA"}, ("domain",)),
    "enhancement": ({"ENHO", "ENHS", "SXCI"}, ("badi", "enhancement")),
    "badi": ({"ENHO", "SXCI"}, ("badi",)),
    "transaction": ({"TRAN"}, ("transaction",)),
    "package": ({"DEVC"}, ()),
    "form": ({"SFPF", "SSFO", "FORM"}, ("smartform", "adobe form", "form")),
}

TOKEN = re.compile(r"[a-z0-9]+")
# fragments that must never count as a compound half
_NO_SPLIT = {"inter", "face", "ment", "tion", "ness", "able", "ible", "ance", "ence", "ting", "ping", "ling", "sion"}


def tokenise(text: str) -> list[str]:
    """Lower-case word tokens; splits ZCL_SALES_ORDER into zcl, sales, order."""
    words = TOKEN.findall(text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def stem(token: str) -> str:
    """Very light stemming so 'ageing' ~ 'aging' ~ 'age', 'orders' ~ 'order'."""
    t = token
    if t == "aging":
        return "age"
    for suffix in ("ings", "ing", "ers", "ies", "ed", "es", "s"):
        if len(t) > 4 and t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    if t.endswith("e") and len(t) > 4:
        t = t[:-1]
    return t


class Vocabulary:
    """Natural-language words seen in short texts, descriptions and tags.
    Used to split compound identifiers like SALESORDER into sales + order."""

    def __init__(self) -> None:
        self.words: set[str] = set()

    def add_text(self, text: str) -> None:
        for w in tokenise(text):
            if w.isalpha() and len(w) >= 3:
                self.words.add(w)

    def split(self, token: str) -> list[str]:
        """SALESORDER -> [sales, order] when both halves are real corpus words.
        Also splits tokens that are themselves in the vocabulary, since SAP
        texts use both 'Salesorder' and 'Sales Order'. Halves need 4+ letters
        to avoid false splits such as inter+face."""
        if not token.isalpha() or len(token) < 8:
            return []
        best: list[str] = []
        for i in range(4, len(token) - 3):
            left, right = token[:i], token[i:]
            if left in self.words and right in self.words and not (left in _NO_SPLIT or right in _NO_SPLIT):
                if not best or min(len(left), len(right)) > min(len(best[0]), len(best[1])):
                    best = [left, right]
        return best

    def join(self, tokens: list[str]) -> list[str]:
        """['sales', 'order'] -> ['salesorder'] for adjacent pairs that exist as one word."""
        joined: list[str] = []
        for a, b in zip(tokens, tokens[1:]):
            if a.isalpha() and b.isalpha() and (a + b) in self.words:
                joined.append(a + b)
        return joined


def object_text(obj: SapObject) -> str:
    """Text used for the semantic index (readable, not weighted)."""
    comps = "; ".join(f"{c.name} {c.short_text}".strip() for c in obj.components[:60] if c.short_text)
    return f"{obj.name.replace('_', ' ')}. {get_type(obj.obj_type).label}. {obj.short_text}. {', '.join(obj.tags or [])}. {obj.description} {comps}"


@dataclass
class ComponentHit:
    kind: str
    name: str
    short_text: str


@dataclass
class SearchResult:
    object: SapObject
    score: float
    keyword_rank: int | None
    semantic_rank: int | None
    similarity: float
    matched_terms: list[str] = field(default_factory=list)
    component_hits: list[ComponentHit] = field(default_factory=list)
    why: list[str] = field(default_factory=list)

    @property
    def type_label(self) -> str:
        return get_type(self.object.obj_type).label


@dataclass
class SearchFilters:
    system: str | None = None
    types: list[str] | None = None
    module: str | None = None
    tags: list[str] | None = None
    category: str | None = None  # code | ddic | config | other


@dataclass
class _Doc:
    tokens: list[str]                 # weighted BM25 bag (stemmed)
    all_stems: set[str]               # every stem in any field (coverage)
    name_stems: set[str]
    short_stems: set[str]
    type_key: str
    tag_text: str


class SearchEngine:
    """Loads objects once and answers many queries. Recreate after ingest."""

    def __init__(self, session: Session, index_dir: Path | None = None, system: str | None = None):
        query = select(SapObject).options(selectinload(SapObject.components), selectinload(SapObject.system))
        if system:
            query = query.join(System).where(System.sid == system.upper())
        self.objects: list[SapObject] = list(session.scalars(query))
        self.vocab = Vocabulary()
        for o in self.objects:
            self.vocab.add_text(o.name)
            self.vocab.add_text(o.short_text)
            self.vocab.add_text(o.description)
            self.vocab.add_text(" ".join(o.tags or []))
            self.vocab.add_text(" ".join(c.short_text for c in o.components[:400]))
        self.docs = [self._document(o) for o in self.objects]
        self.bm25 = BM25Okapi([d.tokens for d in self.docs], b=0.5) if self.docs else None
        self.semantic: SemanticIndex | None = load_index(index_dir) if index_dir else None
        self._by_id = {o.id: o for o in self.objects}

    # ------------------------------------------------------------------ indexing

    def _expand(self, tokens: list[str]) -> list[str]:
        out: list[str] = []
        for t in tokens:
            out.append(t)
            out.extend(self.vocab.split(t))
        return out

    def _document(self, obj: SapObject) -> _Doc:
        name_tokens = self._expand(tokenise(obj.name))
        short_tokens = self._expand(tokenise(obj.short_text))
        tags_text = " ".join(obj.tags or [])
        fields: list[tuple[list[str], int]] = [
            (name_tokens, 4),
            (short_tokens, 4),
            (tokenise(tags_text), 3),
            (tokenise(obj.module), 2),
            (tokenise(get_type(obj.obj_type).label), 1),
            (self._expand(tokenise(obj.description)), 1),
            (self._expand(tokenise(" ".join(f"{c.name} {c.short_text}" for c in obj.components[:400]))), 1),
            (tokenise(" ".join((obj.attributes or {}).get("tables", []))), 2),
        ]
        bag: list[str] = []
        all_stems: set[str] = set()
        for toks, weight in fields:
            stems = [stem(t) for t in toks]
            bag.extend(stems * weight)
            all_stems.update(stems)
        return _Doc(
            tokens=bag,
            all_stems=all_stems,
            name_stems={stem(t) for t in name_tokens},
            short_stems={stem(t) for t in short_tokens},
            type_key=obj.obj_type,
            tag_text=(tags_text + " " + get_type(obj.obj_type).label).lower(),
        )

    # ------------------------------------------------------------------ querying

    @property
    def size(self) -> int:
        return len(self.objects)

    def _classify_query(self, query: str) -> tuple[list[str], list[str]]:
        tokens = tokenise(query)
        hints = [t for t in tokens if t in TYPE_HINTS or stem(t) in TYPE_HINTS]
        content = [t for t in tokens if t not in hints]
        if not content:               # query is only type words -> treat them as content
            content, hints = hints, []
        return content, hints

    def search(self, query: str, limit: int = 10, mode: str = "hybrid", filters: SearchFilters | None = None) -> list[SearchResult]:
        if not self.objects:
            return []
        if mode in ("semantic", "hybrid") and self.semantic is None:
            mode = "keyword"

        content, hints = self._classify_query(query)
        content_expanded = self._expand(content) + self.vocab.join(content)
        content_stems = list(dict.fromkeys(stem(t) for t in content_expanded))
        primary_stems = [stem(t) for t in content]
        syn_stems = [stem(t) for t in synonyms.expand(content)]
        hint_stems = [stem(t) for t in hints]

        keyword_scores: dict[int, float] = {}
        why: dict[int, list[str]] = {}
        if mode in ("keyword", "hybrid") and self.bm25 is not None and (content_stems or hint_stems):
            base = self.bm25.get_scores(content_stems) if content_stems else [0.0] * len(self.objects)
            syn = self.bm25.get_scores(syn_stems) if syn_stems else [0.0] * len(self.objects)
            hint = self.bm25.get_scores(hint_stems) if hint_stems else [0.0] * len(self.objects)

            for obj, doc, b, s, h in zip(self.objects, self.docs, base, syn, hint):
                score = float(b) + 0.35 * float(s) + 0.25 * float(h)
                if score <= 0:
                    continue
                reasons: list[str] = []

                # coverage of the words the user actually typed
                if primary_stems:
                    covered = sum(1 for st in primary_stems if st in doc.all_stems or any(p in doc.all_stems for p in self._parts(st)))
                    coverage = covered / len(primary_stems)
                    score *= 0.35 + 0.65 * coverage
                    if coverage == 1.0 and len(primary_stems) > 1:
                        reasons.append("all terms")

                # exact identifier / short-text hits
                name_hits = sum(1 for st in primary_stems if st in doc.name_stems)
                short_hits = sum(1 for st in primary_stems if st in doc.short_stems)
                if len(primary_stems) > 1:
                    for j in self.vocab.join(content):
                        js = stem(j)
                        if js in doc.name_stems:
                            name_hits = max(name_hits, 2)
                        if js in doc.short_stems:
                            short_hits = max(short_hits, 2)
                if name_hits:
                    score *= 1 + 0.6 * name_hits / max(1, len(primary_stems))
                    reasons.append("name")
                if short_hits:
                    score *= 1 + 0.3 * short_hits / max(1, len(primary_stems))
                    reasons.append("short text")

                # type hints refine among content matches
                if hints:
                    if self._hint_matches(hints, doc):
                        score *= 1.35
                        reasons.append("type " + "/".join(hints))
                    elif primary_stems and not any(st in doc.all_stems for st in primary_stems):
                        score *= 0.5   # only the hint matched, nothing of the content

                keyword_scores[obj.id] = score
                why[obj.id] = reasons

        semantic_scores: dict[int, float] = {}
        if mode in ("semantic", "hybrid") and self.semantic is not None:
            raw = self.semantic.scores(query)
            threshold = 0.05 if self.semantic.backend == "builtin" else 0.2
            semantic_scores = {oid: s for oid, s in raw.items() if s >= threshold and oid in self._by_id}

        kw_max = max(keyword_scores.values(), default=0.0)
        sem_max = max(semantic_scores.values(), default=0.0)
        sem_weight = {"builtin": 0.35}.get(self.semantic.backend if self.semantic else "", 1.0)

        keyword_rank = {oid: r for r, (oid, _) in enumerate(sorted(keyword_scores.items(), key=lambda kv: -kv[1]), start=1)}
        semantic_rank = {oid: r for r, (oid, _) in enumerate(sorted(semantic_scores.items(), key=lambda kv: -kv[1]), start=1)}

        results: list[SearchResult] = []
        for oid in set(keyword_scores) | set(semantic_scores):
            obj = self._by_id[oid]
            if not self._passes(obj, filters):
                continue
            kw = keyword_scores.get(oid, 0.0) / kw_max if kw_max else 0.0
            sm = semantic_scores.get(oid, 0.0) / sem_max if sem_max else 0.0
            if mode == "semantic":
                score = sm
            elif mode == "keyword":
                score = kw
            else:
                score = kw + sem_weight * sm
            if obj.described_by in ("ai", "human"):
                score *= 1.02
            results.append(
                SearchResult(
                    object=obj,
                    score=score,
                    keyword_rank=keyword_rank.get(oid),
                    semantic_rank=semantic_rank.get(oid),
                    similarity=round(semantic_scores.get(oid, 0.0), 3),
                    matched_terms=self._matched_terms(obj, content_expanded, synonyms.expand(content), hints),
                    component_hits=self._component_hits(obj, content_stems),
                    why=why.get(oid, []),
                )
            )

        results.sort(key=lambda r: (-r.score, r.object.name))
        if results:
            best = results[0].score
            if mode != "semantic":
                results = [r for r in results if r.score >= best * 0.3]
            for r in results:
                r.score = round(100 * r.score / best, 1) if best else 0.0
        return results[:limit]

    # ------------------------------------------------------------------ helpers

    def _parts(self, st: str) -> list[str]:
        return [stem(p) for p in self.vocab.split(st)]

    @staticmethod
    def _hint_matches(hints: list[str], doc: _Doc) -> bool:
        for h in hints:
            key = h if h in TYPE_HINTS else stem(h)
            types, fragments = TYPE_HINTS.get(key, (set(), ()))
            if doc.type_key in types or any(f in doc.tag_text for f in fragments):
                return True
        return False

    @staticmethod
    def _passes(obj: SapObject, filters: SearchFilters | None) -> bool:
        if not filters:
            return True
        if filters.types and obj.obj_type not in {t.upper() for t in filters.types}:
            return False
        if filters.module and obj.module != filters.module.upper():
            return False
        if filters.tags and not set(filters.tags) & set(obj.tags or []):
            return False
        if filters.category and get_type(obj.obj_type).category != filters.category:
            return False
        return True

    @staticmethod
    def _matched_terms(obj: SapObject, content: list[str], extra: list[str], hints: list[str]) -> list[str]:
        haystack = " ".join(
            [obj.name, obj.short_text, obj.description, " ".join(obj.tags or []), obj.module, get_type(obj.obj_type).label,
             " ".join(f"{c.name} {c.short_text}" for c in obj.components[:400])]
        ).lower()
        hay_stems = {stem(t) for t in tokenise(haystack)}
        out = [t for t in content if stem(t) in hay_stems]
        out += [t for t in extra if stem(t) in hay_stems and t not in out]
        out += [t for t in hints if stem(t) in hay_stems and t not in out]
        return out

    @staticmethod
    def _component_hits(obj: SapObject, stems: list[str], limit: int = 5) -> list[ComponentHit]:
        if not stems:
            return []
        hits: list[ComponentHit] = []
        wanted = set(stems)
        for c in obj.components:
            if c.kind in ("parameter", "include"):
                continue
            text_stems = {stem(t) for t in tokenise(f"{c.name} {c.short_text}")}
            if wanted & text_stems:
                hits.append(ComponentHit(c.kind, c.name, c.short_text))
                if len(hits) >= limit:
                    break
        return hits


def relevance_label(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 55:
        return "good"
    return "weak"
