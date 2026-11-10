# Aligner — alignment algorithms

Exploratory scripts for aligning the parallel Irish/English CELT TEI files
(`celt_samples/G<code>.xml` / `T<code>.xml`) at the section and paragraph
level. Nothing here is the production aligner — these are algorithm
prototypes `python3 Aligner/<file>.py` can be run and printed directly,
and `LLM_based_aligner.py` is the current entry point that chains them
together with an LLM semantic pass.

## Contents

- [Modules](#modules)
  - [`data_classes.py` — `Element`, `AlignedPair`, and the shared enums](#data_classespy--element-alignedpair-and-the-shared-enums)
  - [`aligner.py` — section-level alignment](#alignerpy--section-level-alignment)
  - [`distance_based_aligning.py` — `align_on_distance`](#distance_based_aligningpy--align_on_distance)
  - [`LLM_based_aligner.py` — LLM verification pass](#llm_based_alignerpy--llm-verification-pass)
- [Shared data structures](#shared-data-structures)
  - [`AlignmentKind`](#alignmentkind)
  - [`AnchorMethod`](#anchormethod)
  - [`Element`](#element)
  - [`AlignedPair`](#alignedpair)
- [How the two modules fit together](#how-the-two-modules-fit-together)
- [Known limitations](#known-limitations)

## Modules

### `data_classes.py` — `Element`, `AlignedPair`, and the shared enums

Defines the core data model every other alignment module in this folder
depends on (`Element`, `AlignedPair`, `AnchorMethod`, `AlignmentKind`,
`DocumentSide`).

### `aligner.py` — section-level alignment

Imports the data model from `data_classes.py` and defines the section-level
(`<div>`) alignment entry point, `align_elements`.

**Design choices / how it works:**
- `align_elements` first calls `align_sections` to pair up `<div>`s, then
  recurses into each matched section's children. A section with children that
  are themselves `<div>`s (matched by `division_pattern = r"^div\d?$"`, e.g.
  `<div1>`, `<div0>`) recurses via `align_elements` again; a section whose
  children are `<p>`s instead goes to `align_individual_section`. A section
  missing a counterpart on either side (`not sec.source_elements or not
  sec.target_elements`) is skipped entirely rather than recursed into — there
  is nothing on the other side to align its children against.
- `align_sections` picks its strategy by how much structure it can trust, in
  order: if every `<div>` on both sides has a unique `n` attribute, match by
  section number (`align_on_section_numbers`) — the strongest available
  anchor. Otherwise, if both sides have the same number of sections, fall back
  to positional pairing (`align_on_position`) — correct section count is weak
  evidence they correspond 1:1, but it is still evidence. Otherwise
  (`align_as_one_block`, currently a stub, `pass`) there is no reliable way to
  split the sections at all, so the fallback is left unimplemented rather than
  guessing.
- `align_on_section_numbers` is written to explicitly emit orphans — a `<div
  n="x">` present on only one side becomes an `AlignedPair` with the other
  side's element list empty — rather than silently dropping it, since a
  missing section is itself a finding (a candidate omission/insertion) the
  rest of the tool needs to see, not something the aligner should hide. Orphans
  still carry `AnchorMethod.SECTION_NUMBER`, not a separate "none" method: they
  were still discovered *by* section-number matching (the absence of a match
  on one side), so the field answers "which method decided this," not "did a
  match happen."
- `align_individual_section` is a second, finer-grained alignment attempt at
  the `<p>` level, anchored on the editorial `<lb n="...">` line numbers in the
  Irish text and the `<mls unit="Irish text line" n="...">` markers the
  translation carries to say which Irish line each English paragraph starts
  on. It only commits to pairing a `<p>` when its first `<lb>` genuinely marks
  the *start* of that paragraph (`is_paragraph_start`) — a paragraph whose
  first `<lb>` is partway through already has running text before it, so using
  that line number as the paragraph's start would be wrong. The several
  `# TODO` branches (paragraph not starting on its first `<lb>`; a line number
  before every translation paragraph's start; one-to-many/many-to-one splits)
  are left unhandled on purpose — this function is superseded in practice by
  `align_on_distance` (see below) and `LLM_Based_aligner.py`'s LLM pass, so
  finishing it hasn't been a priority.
- `find_containing_translation_paragraph` uses `bisect_right` over the
  ascending `translation_start_lines` to do the containment lookup in
  `O(log n)` instead of a linear scan, since it's called once per source
  paragraph.
- `Element.serialize()` / `AlignedPair.serialize()` exist specifically to turn
  these objects into the LLM-friendly dict shape consumed by
  `LLM_Based_aligner.py:prepare_prompt` — see
  [Shared data structures](#shared-data-structures) below for the exact shape.
  They are explicitly **not** meant for the frontend, per their docstrings;
  the frontend contract (if any) lives elsewhere.

### `distance_based_aligning.py` — `align_on_distance`

The paragraph-level alignment actually wired into the pipeline today (called
from `LLM_Based_aligner.py`, not from `aligner.py:align_elements`). Where
`align_individual_section` anchors on explicit line numbers, `align_on_distance`
has no such anchor available at the `<p>` level and instead treats alignment
as a sequence-diff problem.

**Design choices / how it works:**
- Matching two `<p>` elements by tag name alone doesn't distinguish anything —
  they're all `"p"`. `make_counted_tag_name` instead builds a signature string
  per paragraph from how many of a chosen set of descendant tags it contains
  (e.g. `"p|lg:0-l:4-q:0"` for a paragraph with 4 `<l>` lines and no `<lg>`/`<q>`),
  counting only descendants whose nearest relevant ancestor isn't `<note>` or
  `<rdg>` (`NON_COUNTED_ANCESTORS`) — footnote text and un-chosen `<app>`
  variants aren't part of the paragraph's real content, so they shouldn't
  contribute to its structural signature. `signature_tags` defaults to
  `["lg", "l"]`, tuned for testing against sample `301043`; callers (e.g.
  `LLM_Based_aligner.py`) currently pass `["lg", "l", "q"]`.
- These signature strings are then fed to `difflib.SequenceMatcher` (with
  `autojunk=False` — the default heuristic that discounts "popular" elements
  would be actively harmful here, since a common signature like `"p|lg:0-l:0"`
  recurring across many ordinary paragraphs is exactly the kind of match this
  needs to keep), and `get_opcodes()` is walked to turn each diff op into
  `AlignedPair`s: `"equal"` → one-to-one pairs in order, `"delete"`/`"insert"`
  → orphans (source-only / target-only), `"replace"` → **one** many-to-many
  pair spanning the whole replaced range on both sides, rather than guessing
  which individual elements correspond within it.
- `IGNORE_LIST` (`lb`, `ex`, `sup`, `pb`, `frn`) is defined but not currently
  referenced by any function in this file — it documents tags that are known
  to exist on only one language's side (editorial line breaks, abbreviation
  expansions, editor-supplied words, page breaks, foreign-word markers) and so
  would be noise if counted into a structural signature; nothing here consumes
  it yet.
- After the diff pass, `BoundaryShiftMerger` (from `AlignmentRefiner.py`,
  `max_matched_between=2`) runs as a post-processing step to merge adjacent
  orphan pairs that are more likely one shifted paragraph boundary than two
  independent omissions — see `AlignmentRefiner.py`'s own docstring for the
  merge heuristic. `align_on_distance` is written to run a list of refiner
  modules in sequence (`refiner_modules: List[AlignmentRefiner]`), so adding a
  second refinement pass later is a one-line addition to that list, not a
  change to this function's structure.
- The `if __name__ == "__main__"` block is a standalone smoke test against
  sample `301020B`, picking specific section numbers (`["5", "6", "7", "10",
  "12", "13", "19"]`) known from manual inspection to be worth checking, not a
  representative sample chosen programmatically. **Stale**: it still calls
  `align_on_distance(original_paragraphs, translation_paragraphs,
  signature_tags=...)` with the old two-`List[Element]` signature, but the
  function's first parameter is now `section_label` (see below) — running
  this file directly raises `TypeError: align_on_distance() missing 1
  required positional argument: 'translation_elements'` rather than
  producing output. Only `LLM_Based_aligner.py`'s call site was updated when
  `section_label` was added.

### `LLM_based_aligner.py` — LLM verification pass

The wired entry point: loads a file pair, runs `align_on_distance`, then
sends the resulting pairs to an LLM for a semantic check, and persists both
the prompt and the verification results to disk. Importing it requires the
repo root on `sys.path` (`sys.path.append(str(Path(__file__).resolve().parent.parent))`)
so the top-level `Utils` package resolves alongside `Aligner`'s own modules.

**Design choices / how it works:**
- `prepare_prompt` builds the prompt body by calling `pair.serialize(i,
  for_llm=True)` for each pair at its index `i` in the list passed in (not
  the pair's own position in the full document — see
  [`AlignedPair.serialize()`](#alignedpair) below), JSON-encoding each one
  (`json.dumps(..., ensure_ascii=False)`, compact unless `indent=True`), and
  joining them with a `====...====` separator line before substituting the
  result into `ALIGN_PROMPT_TEMPLATE`'s `{string_pairs}` placeholder.
- `verify_segment` sends one slice of `segment_size` pairs to the model
  (`MODEL = "claude-haiku-5-5"`, `output_config` constrained to
  `ALIGN_RESPONSE_SCHEMA`) and retries on failure, up to `max_retry` times
  (default `2`, so 3 attempts total): a `json.JSONDecodeError` (the model
  returned text that didn't parse, despite the schema constraint) retries
  immediately, since the cause is presumed to be the model, not the network,
  so there's nothing to wait out; an `anthropic.APIError` backs off first,
  for `base_delay * (2 ** (attempt - 1) + uniform(0, 0.5))` seconds — doubling
  per attempt with random jitter so concurrent segments don't all retry in
  lockstep. Either error returns `None` once `max_retry` is exhausted rather
  than raising, so one bad segment doesn't abort the whole batch; both
  outcomes are logged.
- `verify_aligned_pairs` splits `aligned_pairs` into consecutive
  `segment_size`-sized slices (default `3`) and fires every segment's
  `verify_segment` concurrently via `asyncio.gather`. It currently just
  returns the list as-is, including any `None`s from exhausted retries —
  there is no logic yet to re-split, retry, or flag which original pairs
  fell inside a failed segment (see
  [Known limitations](#known-limitations)).
- `SuggestedFixApplier` (renamed from the scaffolded `LLM_suggested_fix_applier`)
  builds `element_pair_index_lookup`, a `dict[str, int]` mapping every
  element's serialized `id` (e.g. `"S4"`, `"T2"`) to the index of the
  `AlignedPair` it currently belongs to, by calling `element.serialize(side)`
  (default `for_llm=True`, since only the `id` field is read) for every
  source and target element of every pair. This is the lookup the LLM's
  `merge`/`split` commands (identified by element id — see
  `prompt_templates.py`'s `ALIGN_PROMPT_TEMPLATE`) will need to resolve back
  to pair positions. `apply_fix` is still an unimplemented stub (`pass`) —
  the commands the LLM returns aren't actually applied to `aligned_pairs`
  yet.
- `main` (now `async`, run via `asyncio.run(main())`) wires the whole pass
  together: `setup_logging()` (`Utils.setup_loggin`, a root `StreamHandler`
  to stdout, idempotent) → load sample `301043`'s `<div0>` paragraphs →
  `align_on_distance(1, ...)` → `save_to_file` the formatted prompt to
  `formatted_prompt_template_<date>_<time>.txt` (`Utils.util`, `include_time=True`
  so repeated runs don't overwrite each other) → `verify_aligned_pairs` →
  `save_dict_to_json` the verified segments to `verified_pairs_301043.json`
  under the key `"verified_pairs"`. Every stage logs its own start/progress
  through `logger = logging.getLogger(__name__)`.

## Shared data structures

### `AlignmentKind`

A `StrEnum` describing the shape of one `AlignedPair` purely from the
element counts on each side: `ONE_TO_ONE`, `ONE_TO_MANY`, `MANY_TO_ONE`,
`MANY_TO_MANY`, `SOURCE_ONLY` (orphan on the target side), `TARGET_ONLY`
(orphan on the source side). It's a derived `@property` on `AlignedPair`
(`alignment_kind`), never stored or set directly, so it can never go stale
relative to the actual element lists.

### `AnchorMethod`

A `StrEnum` naming which evidence produced a given `AlignedPair`, in roughly
descending order of trustworthiness:

```python
class AnchorMethod(StrEnum):
    SECTION_NUMBER = "section_number"            # div1@n matches on both sides
    ELEMENT_ID = "element_id"                    # matching id attributes
    STRUCTURAL_SEQUENCE = "structural_sequence"  # tag-name sequence comparison (difflib)
    TEXT_LENGTH = "text_length"                  # length-ratio alignment with markup bonus
    POSITION = "position"                        # same index on both sides; last resort
```

Only `SECTION_NUMBER` (`align_on_section_numbers`), `STRUCTURAL_SEQUENCE`
(`align_on_distance`, and `align_individual_section`'s pairs via the
`AlignedPair` default), and `POSITION` (`align_on_position`, and as the
`AlignedPair.__init__` default) are produced by any function in this folder
today. `ELEMENT_ID` and `TEXT_LENGTH` are declared for alignment strategies
described in `aligner.py`'s class docstring and the `Element` docstring
(length-based matching for the `<p>`-splitting experiment) but have no
producing code yet — see [Known limitations](#known-limitations).

### `Element`

Wraps one BeautifulSoup `Tag` — in practice always a `<p>` or a `<div\d?>` —
with the metadata alignment needs:

```python
Element(
    name="p",                  # input_element.name
    tag=<Tag>,                 # the wrapped BeautifulSoup element itself
    order_index=3,              # position among siblings at the call site; None if not passed
    start_line_number=None,     # not populated by any current caller
    source_column=512,          # Tag.sourcepos — the element's column in the source file
    section_number="12",        # Tag.get("n"); None if the element has no n attribute
)
```

`get_clean_text()` concatenates the element's own text, skipping any text
whose nearest `NON_PRINTED_TAGS` (`note`, `rdg`) ancestor sits *below*
`self.tag` in the tree — i.e. text that belongs to an editorial footnote or an
un-chosen `<app>` variant inside this element isn't part of its printed
content. The `takewhile` stops climbing parents at `self.tag` itself, since
`self.tag` can legitimately be nested *inside* a `NON_PRINTED_TAGS` ancestor
(e.g. a `<p>` that is itself inside a `<note>`) — without that stop, every
text run in the element would wrongly test positive for having a
`NON_PRINTED_TAGS` ancestor. Whitespace runs (the pretty-printed XML's
newlines and indentation between text nodes) are collapsed to a single space
before returning, so the LLM prompt doesn't carry source-file indentation.

`serialize(side, for_llm=True)` produces the LLM-facing dict. `side` (a
`DocumentSide`, `SOURCE`/`TARGET`) and `self.order_index` combine into the
`id` the LLM uses to refer to the element (`"S3"`, `"T0"`) — always present
regardless of `for_llm`. The
`for_llm` flag swaps which other fields are included, and what `tag_string`
holds, so the default prompt payload stays small:

```python
# for_llm=True (default) — what LLM_based_aligner.py actually sends
{
    "id": "S3",                 # str(side) + str(order_index)
    "tag_string": "...",        # get_clean_text() — markup stripped, whitespace collapsed
}

# for_llm=False — full detail, e.g. for debugging/non-LLM consumers
{
    "id": "S3",
    "tag_string": "<p>...</p>", # get_tag_string() — str(self.tag), whitespace collapsed but markup intact
    "name": "p",                 # input_element.name
    "section_number": "12",      # or None
}
```

This is a reversal from an earlier version of this method, where
`tag_string` held the raw markup *for* the LLM and the clean text otherwise
— `for_llm=True` now means "clean text, minimal fields," not "raw markup."

### `AlignedPair`

The output unit of every alignment function in both modules — a group of
zero-or-more source elements matched to zero-or-more target elements:

```python
AlignedPair(
    source_elements=[<Element>],      # [] for a target-only orphan
    target_elements=[<Element>],      # [] for a source-only orphan
    section_label="12",               # div1@n, for display; None if the file has no numbers
    confidence_score=None,            # 0.0 (guess) .. 1.0 (certain); not populated by any current producer
    anchor_method=AnchorMethod.STRUCTURAL_SEQUENCE,
    # child_pairs: list[AlignedPair] = [] — populated one level down by align_elements'
    # recursion; stays empty at the lowest (paragraph) level
)
```

`alignment_kind` (see [`AlignmentKind`](#alignmentkind)) and `__repr__`/`__str__`
(human-readable `source[...] -> target[...]`, used for debug printing — see
every module's `__main__` block) are both derived purely from
`source_elements`/`target_elements`. Neither has a backing field on the
instance — `alignment_kind` is a `@property` recomputed from the two lists on
every access, so it can never go stale relative to them, even though
`serialize()` (below) does include it in its output.
`confidence_score` is accepted by every constructor call site but not actually
computed by any producer yet; every current caller either omits it (default
`0.0`) or passes `None` explicitly (`align_on_section_numbers`).

**`serialize(id, for_llm=True)`** turns a pair into the LLM-facing dict
`LLM_based_aligner.py:prepare_prompt` sends in its prompt (not the frontend —
see the docstring note under
[`aligner.py`](#alignerpy--section-level-alignment) above). `id` is required
(no default) and becomes `pair_number` in the output — it's whatever the
caller wants to label the pair with, not read from the instance; `prepare_prompt`
passes each pair's index in the list it was given (via `enumerate`), which is
only the same as the pair's position in the full document when the whole
document is serialized in one call. Like `Element.serialize()`, `for_llm`
toggles how much detail comes back:

```python
# for_llm=True (default) — what LLM_based_aligner.py actually sends
{
    "pair_number": int,                             # the `id` argument, not an instance attribute
    "source_elements": list[Element.serialize()],   # [] for a target-only orphan
    "target_elements": list[Element.serialize()],   # [] for a source-only orphan
    "section_label": str | None,                    # div1@n of the section, or None
}

# for_llm=False — adds the bookkeeping fields the LLM doesn't need
{
    "pair_number": int,
    "source_elements": list[Element.serialize()],
    "target_elements": list[Element.serialize()],
    "section_label": str | None,
    "confidence_score": float | None,   # 0.0 (guess) to 1.0 (certain); None if not computed
    "anchor_method": str,                # an AnchorMethod value, e.g. "structural_sequence"
    "alignment_kind": str,               # derived from the two element counts — see AlignmentKind
    "child_pairs": list[AlignedPair.serialize()],  # nested pairs one level down
}
```

**Example.** Pair index 1 from a real `align_on_distance(1, ...)` run on
sample `301043` (`original_div0`/`translation_div0`'s direct `<p>` children,
`signature_tags=["lg", "l", "q"]`), serialized both ways:

```python
# pair.serialize(1) — for_llm=True
{
    "pair_number": 1,
    "source_elements": [
        {
            "id": "S1",
            "tag_string": "Rob olc didiu la rīgaib Ulad in gnīm sin &ampersir adubradar nach "
                           "gēbdais coma ina sarugud acht a marbad, ūair nīr gobad rompo. ...",
        },
    ],
    "target_elements": [
        {
            "id": "T1",
            "tag_string": "This deed was displeasing to the kings of Ulster, and they said that "
                           "for the outrage done to them they would accept no terms (from Conn) ...",
        },
    ],
    "section_label": 1,   # not a div@n here — align_on_distance's caller passed the literal
                           # int 1 for this whole call, since this file pair's <div0> has no n
}

# pair.serialize(1, for_llm=False)
{
    "pair_number": 1,
    "source_elements": [
        {
            "id": "S1",
            "tag_string": '<p>Rob olc di<ex>diu</ex> la rīgaib Ulad in gnīm sin &amp;ampersir '
                          'adubradar nach gēbdais coma ...</p>',
            "name": "p",
            "section_number": None,
        },
    ],
    "target_elements": [
        {
            "id": "T1",
            "tag_string": '<p>This deed was displeasing to the kings of Ulster, and they said '
                          'that for the outrage done to them ...</p>',
            "name": "p",
            "section_number": None,
        },
    ],
    "section_label": 1,
    "confidence_score": 0.0,     # align_on_distance never sets this; the AlignedPair default
    "anchor_method": "structural_sequence",
    "alignment_kind": "one_to_one",  # both sides have exactly 1 element; see AlignmentKind
    "child_pairs": [],            # always empty here — align_on_distance doesn't recurse
}
```

`alignment_kind` is included in the `for_llm=False` shape so a consumer
doesn't have to re-derive one-to-one/one-to-many/orphan from the two element
lists itself — the property already computes it from
`len(source_elements)`/`len(target_elements)` on the Python side. It's still
never written back onto the instance (see [`AlignedPair`](#alignedpair)
above) — only the serialized *dict* carries it, by calling the property at
`serialize()` time. `section_label` being a plain `int` rather than a real
`div@n` string is specific to this call site: `LLM_based_aligner.py:main`
calls `align_on_distance(1, ...)` on this file pair's direct `<p>` children
with no section/`div` grouping in between, so there is no real section
number to carry — contrast `align_on_section_numbers` (`aligner.py`), which
passes the real `div1@n` string as `section_label`.

## How the two modules fit together

Nothing in this folder currently wires `aligner.py`'s `align_elements` and
`distance_based_aligning.py`'s `align_on_distance` into a single call chain —
they're two alternative paragraph-level strategies, not pipeline stages. The
one wired entry point, `LLM_based_aligner.py:main`, skips `align_elements`
entirely and goes straight from a hand-picked `<div0>`'s direct `<p>` children
to `align_on_distance`, then on to the LLM verification pass:

```python
original_paragraphs = [Element(tag, i) for i, tag in enumerate(original_div0.find_all("p", recursive=False))]
translation_paragraphs = [Element(tag, i) for i, tag in enumerate(translation_div0.find_all("p", recursive=False))]
aligned_pairs = align_on_distance(1, original_paragraphs, translation_paragraphs, signature_tags=["lg", "l", "q"])

verified = await verify_aligned_pairs(aligned_pairs)  # sends pairs to the LLM in segments, see below
```

i.e. today's actual flow is: load a file pair (`utils.py:load_file_pair`) →
list each side's top-level `<p>`s as `Element`s → `align_on_distance` →
`verify_aligned_pairs` sends the serialized pairs to the LLM via
`ALIGN_PROMPT_TEMPLATE` for semantic confirmation/correction, in
`segment_size`-sized batches — but the `merge`/`split` commands it returns
aren't applied back onto `aligned_pairs` yet (`SuggestedFixApplier.apply_fix`
is a stub); see
[`LLM_based_aligner.py`](#llm_based_alignerpy--llm-verification-pass) above
for the full breakdown. `aligner.py`'s section-level machinery
(`align_sections`, `align_on_section_numbers`, `align_on_position`) and its
own paragraph-level attempt (`align_individual_section`) are exercised
directly from `aligner.py`'s own `__main__` block. `Element`, `AlignedPair`,
and `AnchorMethod` live in `data_classes.py` and are reused as a dependency
by `AlignmentRefiner.py`, `distance_based_aligning.py`, and
`test_serialize.py`; `aligner.py`'s own `division_pattern` is reused the same
way by `locate_section_split_mismatch.py`. `align_elements` itself isn't
currently called from the `LLM_based_aligner.py` entry point.

## Known limitations

- `align_as_one_block` (`aligner.py`) is an unimplemented stub (`pass`,
  returns `None`) — reached only when sections can't be matched by number or
  by equal count, which no current sample file pair triggers.
- `align_individual_section`'s three `# TODO` branches (paragraph not
  starting on its own first `<lb>`; an Irish line before every translation
  paragraph's start; one-to-many/many-to-one splits) are unhandled; the
  function silently omits those paragraphs from its output rather than
  raising, so a caller can't currently distinguish "nothing to align" from
  "an unhandled case was skipped."
- `AnchorMethod.ELEMENT_ID` and `AnchorMethod.TEXT_LENGTH` are declared but no
  function in this folder produces either yet.
- `IGNORE_LIST` in `distance_based_aligning.py` is defined but not read by any
  function in the file.
- `Element.__init__`'s `order_index: int = None` and `start_line_number: int =
  None` are typed as plain `int` with a `None` default rather than
  `int | None` — both are genuinely optional in practice (not every caller
  passes them), it's just that the type hints don't say so.
- `confidence_score` is threaded through every `AlignedPair` but has no
  producer; every pair in this folder's output currently carries either the
  default `0.0` or an explicit `None`, not a real computed value.
- `distance_based_aligning.py`'s own `__main__` block wasn't updated when
  `align_on_distance` gained its leading `section_label` parameter — running
  `python3 Aligner/distance_based_aligning.py` directly now raises a
  `TypeError` instead of printing a result. Only `LLM_based_aligner.py:main`
  calls it with the new signature.
- `AlignedPair.serialize()`'s `for_llm=False` branch recurses into
  `child_pairs` with `pair.serialize()` — no `id` argument — even though
  `id` is now a required parameter with no default; this would raise a
  `TypeError` if any pair in this folder's output actually had non-empty
  `child_pairs`, which none currently do (`align_on_distance` never
  recurses), so the bug is latent rather than observed.
- `verify_aligned_pairs` (`LLM_based_aligner.py`) returns whatever
  `asyncio.gather` collects, including `None` for any segment that
  exhausted its retries — there is no logic yet to tell the caller which
  original pairs fell inside a failed segment, or to retry a failed segment
  at a smaller size.
- `SuggestedFixApplier.apply_fix` (`LLM_based_aligner.py`) is an
  unimplemented stub (`pass`) — the `merge`/`split` commands the LLM returns
  are never actually applied to `aligned_pairs`; only the id-to-pair-index
  lookup it needs to do so is built so far.
