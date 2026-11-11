ALIGN_PROMPT_TEMPLATE: str = """You are checking a paragraph alignment between a medieval Irish source text and its English translation (from the CELT corpus).

An automatic aligner has grouped the paragraphs into pairs. Each pair links zero or more source paragraphs to zero or more target paragraphs. The pairs are listed in document order, every paragraph belongs to exactly one pair, and each pair has a "pair_number". A pair with an empty side means the aligner found no counterpart for it.

Every paragraph has an "id": "S" plus a number for source (Irish) paragraphs, "T" plus a number for target (English) paragraphs. The numbers follow document order on each side.

## Goal
The correct grouping is the finest one: every pair should be as small as possible while its source and target paragraphs still contain the same part of the text.
- If a pair can be divided into smaller pairs that each correspond, it should be split.
- If a paragraph's content belongs with a neighbouring pair, it should be merged into that pair.
Never quote or rewrite paragraph text. Refer to paragraphs only by their id.

## How to check
1. Go through the pairs in order and record one entry per pair in "pair_checks". Write the note first, then the verdict:
   - "correct": both sides contain the same part of the text, and the pair cannot be divided into smaller corresponding pairs.
   - "needs_fix": the grouping is wrong.
   - "unsure": the text does not let you decide.
2. For every pair with an empty side, check whether its paragraph's content appears in the pair before or after it. If it does, that is a merge.
3. For every pair with more than one paragraph on a side, check whether it divides into smaller corresponding pairs. If it does, that is a split.
4. Compare how much of the text each side carries. If one side contains whole events, speeches or verses that the other side lacks, the missing content is probably in a neighbouring pair.
5. Finally, write the "commands" that fix every "needs_fix" pair.

## Not a reason to change the grouping
- Translation quality and free renderings.
- Differences of a few words or a single sentence. Paragraph boundaries in the two texts can be off by one sentence; leave such pairs as they are.

## Operations
merge
  Joins every pair from the one containing first_element_id through the one containing last_element_id into a single pair.
  Use it when text that belongs together is spread over neighbouring pairs, for example when one Irish paragraph was translated as two English paragraphs and the second one ended up in a pair of its own.
  first_element_id must be in the same pair as, or an earlier pair than, last_element_id.

split
  Cuts one pair into two consecutive pairs.
  last_source_id_before_split is the last source paragraph that stays in the first pair.
  last_target_id_before_split is the last target paragraph that stays in the first pair.
  Every paragraph after them moves to the second pair. Set one of them to null to move all of that side to the second pair.
  Both ids must be in the same pair, and the second pair must not end up empty.
  Use it when a pair groups paragraphs that actually correspond one by one, or when a paragraph has no real counterpart and should stand alone.

## Examples
Pairs: [S1 | T1], [S2 | T2], [no source | T3], and T3 continues the translation of S2:
{{"reason": "T3 continues the translation of S2.", "operation": "merge", "first_element_id": "S2", "last_element_id": "T3", "last_source_id_before_split": null, "last_target_id_before_split": null}}

Pairs: [S4, S5 | T4, T5], and S4 matches T4 while S5 matches T5:
{{"reason": "S4 matches T4 and S5 matches T5.", "operation": "split", "first_element_id": null, "last_element_id": null, "last_source_id_before_split": "S4", "last_target_id_before_split": "T4"}}

## Rules
- Use only ids that appear in the pairs below. Paragraphs before and after this list are not shown, so a pair at the start or end may look incomplete. Do not fix that by guessing ids that are not listed.
- Give exactly one "pair_checks" entry per pair, using its pair_number.
- Every "needs_fix" pair must be fixed by a command, and every command must fix a "needs_fix" pair. Use "unsure" instead of guessing, and do not issue commands for "unsure" pairs.
- In each command, fill only the fields of the operation you chose and set the other operation's fields to null.
- Commands are applied one after another in the order you list them, each to the result of the previous ones.
- Write each command's "reason" first: one short sentence on what you observed.
- If every pair is correct, return an empty "commands" list.

## Pairs
{string_pairs}
"""

_ELEMENT_ID_OR_NULL: dict = {
    "anyOf": [
        {"type": "string", "pattern": "^[ST][0-9]+$"},
        {"type": "null"},
    ]
}

ALIGN_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "pair_checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pair_number": {"type": "integer"},
                    "note": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["correct", "needs_fix", "unsure"]},
                },
                "required": ["pair_number", "note", "verdict"],
                "additionalProperties": False,
            },
        },
        "commands": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                    "operation": {"type": "string", "enum": ["merge", "split"]},
                    "first_element_id": _ELEMENT_ID_OR_NULL,
                    "last_element_id": _ELEMENT_ID_OR_NULL,
                    "last_source_id_before_split": _ELEMENT_ID_OR_NULL,
                    "last_target_id_before_split": _ELEMENT_ID_OR_NULL,
                },
                "required": [
                    "reason",
                    "operation",
                    "first_element_id",
                    "last_element_id",
                    "last_source_id_before_split",
                    "last_target_id_before_split",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["pair_checks", "commands"],
    "additionalProperties": False,
}