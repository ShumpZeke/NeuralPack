"""Research-only filters for the frozen rival's inferred raises relations.

These are conservative surface rules, not a semantic parser or calibrated risk
model. They change only relation bonuses: lexical facets and query bytes remain
unchanged. The original rival is retained as a control, never edited in place.
"""
from dataclasses import dataclass, replace
import re


MODES = ('original', 'disabled', 'action', 'conservative')
ACTION_WORDS = frozenset('raise raises raised raising throw throws thrown'.split())
# Unicode word boundaries avoid matching ASCII substrings inside identifiers.
# Dotted names expose components; underscores/camel case do not invent names.
SURFACE = re.compile(r'(?<!\w)[^\W\d]\w*(?:\.[^\W\d]\w*)*(?!\w)', re.UNICODE)
ABSTAIN_WORDS = frozenset('''not no never neither nor without cannot
avoid avoids avoided avoiding prevent prevents prevented preventing
catch catches caught catching handle handles handled handling
suppress suppresses suppressed suppressing
mention mentions mentioned mentioning literal literals string strings'''.split())
CONTRACTION = re.compile(r"\b\w+n['\u2019]t\b", re.IGNORECASE)


@dataclass(frozen=True)
class IntentDecision:
    relations: tuple[tuple[str, str], ...]
    suppressed: tuple[tuple[str, str], ...]
    reasons: tuple[str, ...]


def surface_names(query):
    """Whole surface words and dotted components, lowercased like the rival."""
    hits = {m.group(0).lower() for m in SURFACE.finditer(query)}
    return hits | {part for hit in hits for part in hit.split('.')}


def filter_relations(query, relations, mode):
    if mode not in MODES:
        raise ValueError('Unknown structural-intent mode')
    relations = tuple(tuple(r) for r in relations)
    if any(len(r) != 2 or r[0] != 'raises' for r in relations):
        raise ValueError('This experiment supports raises relations only')
    if mode == 'original':
        return IntentDecision(relations, (), ())
    if mode == 'disabled':
        return IntentDecision((), relations, ('relation_channel_disabled',))
    # A dotted component may be an argument, but is not an action word: e.g.
    # errors.raise must not be treated as a natural-language request to raise.
    words = {m.group(0).lower() for m in SURFACE.finditer(query)}
    if not words.intersection(ACTION_WORDS):
        return IntentDecision((), relations, ('no_whole_action_word',))
    if mode == 'action':
        return IntentDecision(relations, (), ())
    blockers = sorted(words.intersection(ABSTAIN_WORDS))
    if blockers or CONTRACTION.search(query):
        return IntentDecision((), relations, ('ambiguous_surface_intent',))
    names = surface_names(query)
    kept = tuple(r for r in relations if r[1] in names)
    removed = tuple(r for r in relations if r[1] not in names)
    return IntentDecision(kept, removed, ('argument_not_whole_surface_name',) if removed else ())


def guarded_plan(plan, mode):
    """Return a new QueryPlan; never mutate the original or its facet weights."""
    decision = filter_relations(plan.raw, plan.relations, mode)
    return replace(plan, relations=list(decision.relations)), decision
