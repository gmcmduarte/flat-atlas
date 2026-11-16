"""Phrase extraction and variant normalisation (PLAN §9.1 step 2), pure functions.

A *phrase* is a run of 1 to 4 word tokens inside one punctuation-delimited segment that neither
starts nor ends with a stop word. Two phrases are the **same candidate** when their *keys* are
equal; the key folds case and accents, splits hyphens, spells Greek letters out ("ω" -> "omega"),
uses American spelling ("synchronising" -> "synchronizing") and reduces plurals ("automata" ->
"automaton"). Nothing here uses a model: it is a light approach on purpose (P1-05).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "ζ": "zeta",
    "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
    "ν": "nu", "ξ": "xi", "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon",
    "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega", "Σ": "sigma", "Ω": "omega", "Δ": "delta",
    "Γ": "gamma", "Π": "pi", "Λ": "lambda",
}  # fmt: skip


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


STOP_WORDS = _words(
    """a about above after again against all also am an and any are as at be because been before
    being below between both but by can could did do does doing down during each either few for
    from further had has have having he her here hers him his how i if in into is it its itself
    just may me might more most must my no nor not of off on once only or other our out over own
    same shall she should so some such than that the their theirs them then there these they this
    those through to too under until up upon us very was we were what when where which while who
    whom why will with within without would you your"""
)
# Words that often open or close a title without naming a topic.
GENERIC_BOUNDARY = _words(
    """new note notes study studies approach approaches paper survey using use used based via
    towards toward case cases remark remarks result results some two one three first second
    simple improved efficient general generalized shown show shows given prove proved proves
    work introduction present presented paper we propose"""
)
# Spelling: British -> American, for words that are not exceptions.
_ISE_EXCEPTIONS = _words(
    """precise precisely concise otherwise exercise exercises rise rises wise likewise premise
    premises promise promises expertise raise advise advisor revise surprise surprising comprise
    compromise disguise enterprise franchise paradise noise poise treatise merchandise
    televise supervise supervised improvise demise exorcise despise arise arises arising
    bruise cruise praise"""
)
_IRREGULAR_SINGULAR = {
    "automata": "automaton",
    "criteria": "criterion",
    "analyses": "analysis",
    "matrices": "matrix",
    "indices": "index",
    "vertices": "vertex",
    "languages": "language",
    "series": "series",
    "species": "species",
}
_NO_STRIP = ("ss", "us", "is", "ics", "ous")
_SEGMENT_BREAK = re.compile(r"[,:;()\[\]{}?!.\"“”‘’—–/\\|=<>+*&%$#@^~`]|\s-\s|\s–\s")
_TOKEN = re.compile(r"[^\W\d_]+(?:[-‐‑][^\W\d_]+)*")  # letters only; hyphens join
_DIGIT_RUN = re.compile(r"\d+")


def fold(text: str) -> str:
    """Lower case, accents dropped, Greek letters spelled out."""
    out = []
    for ch in unicodedata.normalize("NFC", text):
        if ch in GREEK:
            out.append(f" {GREEK[ch]} " if not ch.isascii() else ch)
            continue
        out.append(ch)
    text = "".join(out)
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def american(word: str) -> str:
    """British -> American spelling of one lower-case word (a small, explicit rule set)."""
    if word in _ISE_EXCEPTIONS:
        return word
    for old, new in (
        ("isation", "ization"),
        ("isations", "izations"),
        ("ising", "izing"),
        ("ised", "ized"),
        ("ises", "izes"),
        ("iser", "izer"),
        ("isers", "izers"),
    ):
        if word.endswith(old) and len(word) > len(old) + 2:
            return word[: -len(old)] + new
    if word.endswith("ise") and len(word) > 5:
        return word[:-3] + "ize"
    for old, new in (("ysing", "yzing"), ("ysed", "yzed"), ("yse", "yze"), ("yses", "yzes")):
        if word.endswith(old) and len(word) > len(old) + 2:
            return word[: -len(old)] + new
    for old, new in (("behaviour", "behavior"), ("centre", "center"), ("modelling", "modeling")):
        if word.startswith(old):
            return new + word[len(old) :]
    if word.endswith("elled") and len(word) > 7:  # labelled, modelled
        return word[:-5] + "eled"
    if word.endswith("elling") and len(word) > 7:
        return word[:-6] + "eling"
    return word


def singular(word: str) -> str:
    """A crude plural -> singular that is the same for a word and its plural (not a lemmatiser)."""
    if word in _IRREGULAR_SINGULAR:
        return _IRREGULAR_SINGULAR[word]
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(_NO_STRIP):
        return word[:-1]
    return word


def key_tokens(phrase: str) -> tuple[str, ...]:
    """The tokens of the canonical key of a phrase."""
    folded = fold(phrase)
    words = re.findall(r"[^\W\d_]+", folded)
    return tuple(singular(american(w)) for w in words)


def key_of(phrase: str) -> str:
    return " ".join(key_tokens(phrase))


def _is_boundary(token: str) -> bool:
    words = token.split("-")
    return all(len(w) == 1 and w not in GREEK.values() for w in words) or token in STOP_WORDS


def segments(text: str) -> list[list[str]]:
    """Word tokens of each punctuation-delimited segment (surface form, case folded)."""
    out = []
    for segment in _SEGMENT_BREAK.split(text):
        tokens: list[str] = []
        pos = 0
        for match in _TOKEN.finditer(fold(segment)):
            gap = fold(segment)[pos : match.start()]
            if _DIGIT_RUN.search(gap) and tokens:  # a number breaks a phrase
                out.append(tokens)
                tokens = []
            tokens.append(match.group(0))
            pos = match.end()
        if tokens:
            out.append(tokens)
    return out


def extract(
    text: str,
    *,
    min_n: int = 1,
    max_n: int = 4,
    extra_boundary: Iterable[str] = (),
) -> dict[str, str]:
    """Phrases of ``text`` as ``{key: surface}`` (one surface per key, the first seen).

    Phrases do not start or end with a stop or generic word; the word "of" may sit inside.
    """
    boundary = STOP_WORDS | GENERIC_BOUNDARY | frozenset(extra_boundary)
    found: dict[str, str] = {}
    for tokens in segments(text):
        # split a segment at single-letter tokens (variables) so they do not join phrases
        runs: list[list[str]] = [[]]
        for tok in tokens:
            if _is_boundary(tok) and tok not in boundary and tok not in STOP_WORDS:
                runs.append([])
            else:
                runs[-1].append(tok)
        for run in runs:
            for n in range(min_n, max_n + 1):
                for i in range(len(run) - n + 1):
                    gram = run[i : i + n]
                    if gram[0] in boundary or gram[-1] in boundary:
                        continue
                    if any(t in STOP_WORDS and t != "of" for t in gram[1:-1]):
                        continue
                    if n > 1 and "of" in gram[1:-1] and n < 3:
                        continue
                    surface = " ".join(gram)
                    key = key_of(surface)
                    if key and key not in found:
                        found[key] = surface
    return found
