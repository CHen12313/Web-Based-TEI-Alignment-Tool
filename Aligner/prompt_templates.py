ALIGN_PROMPT_TEMPLATE: str = """You are checking a paragraph alignment between a medieval Irish source text and its English translation (TEI XML from the CELT corpus).

An automatic aligner has grouped the paragraphs into pairs. Each pair links zero or more source paragraphs to zero or more target paragraphs. The pairs are listed in document order, and every paragraph belongs to exactly one pair. A pair with an empty side means the aligner found no counterpart for it.

Every paragraph has an "id": "S" plus a number for source (Irish) paragraphs, "T" plus a number for target (English) paragraphs. The numbers follow document order on each side.

Your task: read each pair and decide whether its source and target paragraphs tell the same part of the text. Where they do not, output commands that correct the grouping. Never quote or rewrite paragraph text. Refer to paragraphs only by their id.

## What to ignore
- Markup differences (<lb>, <pb>, <ex>, <sup>, <frn> and similar). Only the meaning of the running text matters.
- Text inside <note> and <rdg>. These are editorial footnotes and variant readings, not part of the paragraph.
- Translation quality, free renderings, and small omissions or additions. A pair whose paragraphs correspond overall is correct.

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
  Use it when the aligner grouped paragraphs that actually correspond one by one, or when a paragraph has no real counterpart and should stand alone.

## Examples
Pairs: [S1 | T1], [S2 | T2], [no source | T3], and T3 continues the translation of S2:
{{"reason": "T3 continues the translation of S2.", "operation": "merge", "first_element_id": "S2", "last_element_id": "T3", "last_source_id_before_split": null, "last_target_id_before_split": null}}

Pairs: [S4, S5 | T4, T5], and S4 matches T4 while S5 matches T5:
{{"reason": "S4 matches T4 and S5 matches T5.", "operation": "split", "first_element_id": null, "last_element_id": null, "last_source_id_before_split": "S4", "last_target_id_before_split": "T4"}}

## Rules
- Use only ids that appear in the pairs below. Paragraphs before and after this list are not shown, so a pair at the start or end may look incomplete. Do not fix that by guessing ids that are not listed.
- Fill only the fields of the operation you chose and set the other operation's fields to null.
- Commands are applied one after another in the order you list them, each to the result of the previous ones.
- Write "reason" first: one short sentence on what you observed.
- If every pair is correct, return an empty "commands" list. Only issue a command when the text clearly shows the grouping is wrong; an unnecessary command does more harm than a missed one.

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
        }
    },
    "required": ["commands"],
    "additionalProperties": False,
}