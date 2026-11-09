# experiments — alignment algorithms

Exploratory scripts for aligning the parallel Irish/English CELT TEI files
(`celt_samples/G<code>.xml` / `T<code>.xml`) at the section and paragraph
level. Nothing here is the production aligner — these are algorithm
prototypes `python3 experiments/<file>.py` can be run and printed directly,
and `LLM_Based_aligner.py` is the current entry point that chains them
together with an LLM semantic pass.

## Contents

- [Modules](#modules)
  - [`aligner.py` — `Element`, `AlignedPair`, section-level alignment](#alignerpy--element-alignedpair-section-level-alignment)
  - [`distance_based_aligning.py` — `align_on_distance`](#distance_based_aligningpy--align_on_distance)
- [Shared data structures](#shared-data-structures)
  - [`AlignmentKind`](#alignmentkind)
  - [`AnchorMethod`](#anchormethod)
  - [`Element`](#element)
  - [`AlignedPair`](#alignedpair)
- [How the two modules fit together](#how-the-two-modules-fit-together)
- [Known limitations](#known-limitations)

## Modules

### `aligner.py` — `Element`, `AlignedPair`, section-level alignment

Defines the core data model every other alignment module in this folder
depends on (`Element`, `AlignedPair`, `AnchorMethod`, `AlignmentKind`), plus
the section-level (`<div>`) alignment entry point, `align_elements`.

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
  representative sample chosen programmatically.

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
`NON_PRINTED_TAGS` ancestor.

`serialize()` produces the LLM-facing dict:

```python
{
    "name": "p",
    "tag_string": "<p>...</p>",   # str(self.tag) — full markup, used only for the LLM prompt
    "section_number": "12",       # or None
}
```

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

**`serialize()`** turns a pair into the LLM-facing dict `LLM_Based_aligner.py`
sends in its prompt (not the frontend — see the docstring note under
[`aligner.py`](#alignerpy--element-alignedpair-section-level-alignment) above).
Schema (the method's own docstring predates the `alignment_kind` line being
added to its `return` and hasn't been updated to list it — the schema below is
what it actually returns):

```python
{
    # source (Irish) elements, in document order; [] for a target-only orphan
    "source_elements": list[Element.serialize()],
    # target (English) elements, in document order; [] for a source-only orphan
    "target_elements": list[Element.serialize()],
    # div1@n of the section, or None if the file has no numbers
    "section_label": str | None,
    # 0.0 (guess) to 1.0 (certain); None if not computed by the producer
    "confidence_score": float | None,
    # an AnchorMethod value, e.g. "structural_sequence"
    "anchor_method": str,
    # derived from len(source_elements)/len(target_elements) at call time — see AlignmentKind
    "alignment_kind": str,
    # nested pairs one level down; empty at the lowest (paragraph) level
    "child_pairs": list[AlignedPair.serialize()],
}
```

**Example.** `LLM_Based_aligner.py:prepare_prompt` is
`[pair.serialize() for pair in aligned_pairs]` — this is the literal list it
hands to the LLM. Below is pair index 1 from a real `align_on_distance` run on
sample `301043` (`python3 experiments/LLM_Based_aligner.py`), with both
`tag_string`s truncated (`...`) for length — the untruncated run for all pairs
is on disk at the repo root, `serialized_301043.txt` (raw `repr()`, one line)
and `serialized_301043_formatted.txt` (human-readable, one block per pair):

```python
{
    "source_elements": [
        {
            "name": "p",
            "tag_string": '<p>Rob olc di<ex>diu</ex> la rīgaib Ulad in gnīm sin &ampersir adubradar '
                          'nach gēbdais coma ina sarugud acht a marbad, ūair nīr gobad rompo. ...</p>',
            "section_number": None,
        },
    ],
    "target_elements": [
        {
            "name": "p",
            "tag_string": '<p>This deed was displeasing to the kings of Ulster, and they said that '
                          'for the outrage done to them they would accept no terms (from Conn) '
                          'but his death, ...</p>',
            "section_number": None,
        },
    ],
    "section_label": 1,          # not a div@n here — align_on_distance passes the paragraph's
                                  # order_index as section_label, since this file pair's <div0> has no n
    "confidence_score": 0.0,     # align_on_distance never sets this; the AlignedPair default
    "anchor_method": AnchorMethod.STRUCTURAL_SEQUENCE,  # str(...) == "structural_sequence" once JSON-encoded
    "alignment_kind": AlignmentKind.ONE_TO_ONE,  # both sides have exactly 1 element; see AlignmentKind
    "child_pairs": [],           # always empty here — align_on_distance doesn't recurse
}
```

`alignment_kind` is included here so a consumer (the LLM, or anything reading
the serialized JSON) doesn't have to re-derive one-to-one/one-to-many/orphan
from the two elements lists itself — the property already computes it from
`len(source_elements)`/`len(target_elements)` on the Python side, so including
the already-computed value in the output is cheap and removes one more thing
the prompt has to get right downstream. It's still never written back onto
the instance (see [`AlignedPair`](#alignedpair) above) — only the serialized
*dict* carries it, by calling the property at `serialize()` time.
`section_label` being a plain running index rather than a real `div@n` is
specific to this call site: `align_on_distance` is called on this file pair's
direct `<p>` children with no section/`div` grouping in between, so there is
no section number to carry — contrast `align_on_section_numbers`
(`aligner.py`), which passes the real `div1@n` string.

## How the two modules fit together

Nothing in this folder currently wires `aligner.py`'s `align_elements` and
`distance_based_aligning.py`'s `align_on_distance` into a single call chain —
they're two alternative paragraph-level strategies, not pipeline stages. The
one wired entry point, `LLM_Based_aligner.py`, skips `align_elements`
entirely and goes straight from a hand-picked `<div0>`'s direct `<p>` children
to `align_on_distance`:

```python
original_paragraphs = [Element(tag, i) for i, tag in enumerate(original_div0.find_all("p", recursive=False))]
translation_paragraphs = [Element(tag, i) for i, tag in enumerate(translation_div0.find_all("p", recursive=False))]
aligned_pairs = align_on_distance(original_paragraphs, translation_paragraphs, signature_tags=["lg", "l", "q"])
```

i.e. today's actual flow is: load a file pair (`utils.py:load_file_pair`) →
list each side's top-level `<p>`s as `Element`s → `align_on_distance` → (not
yet implemented) feed the serialized pairs into an LLM via
`ALIGN_PROMPT_TEMPLATE` for semantic confirmation/correction. `aligner.py`'s
section-level machinery (`align_sections`, `align_on_section_numbers`,
`align_on_position`) and its own paragraph-level attempt
(`align_individual_section`) are exercised directly from `aligner.py`'s own
`__main__` block and reused as a dependency (`Element`, `AlignedPair`,
`AnchorMethod`, `division_pattern`) by `AlignmentRefiner.py`,
`distance_based_aligning.py`, `locate_section_split_mismatch.py`, and
`test_serialize.py`, but `align_elements` itself isn't currently called from
the `LLM_Based_aligner.py` entry point.

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
