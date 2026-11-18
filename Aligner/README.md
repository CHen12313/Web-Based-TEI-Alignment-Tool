# Aligner — alignment algorithms

Aligns the parallel Irish/English CELT TEI files
(`celt_samples/G<code>.xml` / `T<code>.xml`) at the section and paragraph
level, has an LLM check the paragraph pairs, and applies the fixes it
suggests. This is still prototype code, not the production aligner.
`main.py:align_files` is the entry point that chains all the stages (see
[Pipeline](#pipeline)); most modules can also be run on their own as smoke
tests. Run them from inside `Aligner/`, because the modules import each other
without a package prefix.

## Contents

- [Modules](#modules)
  - [`data_classes.py` — `Element`, `AlignedPair`, and the shared enums](#data_classespy--element-alignedpair-and-the-shared-enums)
  - [`aligner_module_abc.py` — `AlignerModule`](#aligner_module_abcpy--alignermodule)
  - [`main.py` — pipeline entry point](#mainpy--pipeline-entry-point)
  - [`File_Aligner_Modules/` — section aligners](#file_aligner_modules--section-aligners)
  - [`distance_based_aligner.py` — `DistanceBasedAligner`](#distance_based_alignerpy--distancebasedaligner)
  - [`line_break_aligner.py` — `LineBreakAligner`](#line_break_alignerpy--linebreakaligner)
  - [`Alignment_Refiner_Modules/` — refiners](#alignment_refiner_modules--refiners)
  - [`llm_based_verifier.py` — LLM verification pass](#llm_based_verifierpy--llm-verification-pass)
  - [`suggested_fix_applier.py` — `SuggestedFixApplier`](#suggested_fix_applierpy--suggestedfixapplier)
- [Shared data structures](#shared-data-structures)
  - [`AlignmentKind`](#alignmentkind)
  - [`AnchorMethod`](#anchormethod)
  - [`Element`](#element)
  - [`AlignedPair`](#alignedpair)
  - [`FixCommand`](#fixcommand)
  - [`OPCode` and `CommandOutcome`](#opcode-and-commandoutcome)
- [Pipeline](#pipeline)
- [Known limitations](#known-limitations)

## Modules

### `data_classes.py` — `Element`, `AlignedPair`, and the shared enums

Defines the core data model every other alignment module in this folder
depends on (`Element`, `AlignedPair`, `AnchorMethod`, `AlignmentKind`,
`DocumentSide`), plus the types the fix step uses (`FixCommand`, `OPCode`,
`CommandOutcome`). See [Shared data structures](#shared-data-structures).

### `aligner_module_abc.py` — `AlignerModule`

The base class of every class that pairs the source elements with the target
elements, whether it pairs a file's sections or a section's `<p>`s. It has one
abstract method, `align(source_elements, target_elements, section_label=None)
-> List[AlignedPair]`.

**Design choices / how it works:**
- The input is `List[Element]` on both sides, not `List[Tag]`. The distance
  aligner already took `Element`s, and `Element` carries the `order_index` that
  the LLM ids (`S1`, `T2`) are built from, so the caller numbers the elements
  once instead of each aligner re-numbering them.
- Settings (e.g. `signature_tags`) go in the subclass `__init__`, not in `align`,
  so `align` has one signature that every subclass shares and `main.py` can
  swap one aligner for another.
- An element with no counterpart must come back as an orphan (an `AlignedPair`
  with the other side empty) instead of being dropped, because a missing element
  is itself a finding.
- Naming: a file is `<what tells it apart>_aligner.py` and its class is
  `<WhatTellsItApart>Aligner`. Aligners that pair a file's sections live in
  `File_Aligner_Modules/`, aligners that pair a section's elements live in
  `Section_Aligner_Modules/`.

### `main.py` — pipeline entry point

Defines `align_files`, the entry point that runs the whole chain (this file was
`aligner.py` before the aligners were split into classes, and `align_files` was
called `align_elements`). It is `async` because it awaits the LLM pass; the
`__main__` block runs it with `asyncio.run` on sample `301020B`. The order of
the stages and the contracts between them are in [Pipeline](#pipeline).

**Design choices / how it works:**
- `align_files(original_tags, translation_tags)` returns
  `(aligned_elements, aligned_sections)`: the flat list of paragraph-level
  pairs after the LLM's fixes were applied, and the section-level pairs (whose
  `child_pairs` hold the nested `<div>` alignment).
- The paragraph-level pairs are collected into **one flat list**, not one list
  per section. The LLM pass works on fixed-size windows of that list, so a
  section's last window is not left half empty, and a window may straddle a
  section boundary on purpose: the alignment is meant to follow the meaning of
  the text, so a section boundary that drifted is something a fix is allowed to
  cross. The price is that the list no longer shows which section a pair is
  from; every pair carries its `section_label` instead.
- `align_individual_section(section, counters, aligned_elements)` is
  **recursive**, because `<div>`s can be nested and without recursion only the
  direct children of each section would be paired. For one pair it looks one
  level down on both sides (`division_pattern = r"^div\d?$"`, so `<div0>` to
  `<div9>`):
  - both sides have child `<div>`s: wrap them in `Element`s, align them with
    `DistanceBasedAligner()`, store the result in `section.child_pairs`, and
    call itself on every child pair;
  - neither side has child `<div>`s: this is the base case. The direct `<p>`s
    are aligned with `DistanceBasedAligner(signature_tags=["lg", "l", "q"])`
    and the pairs are appended to `aligned_elements`;
  - only one side has child `<div>`s: nothing is done and nothing is logged
    (see [Known limitations](#known-limitations)).

  A pair missing a counterpart on either side (`not section.source_elements or
  not section.target_elements`) returns at once, since there is nothing on the
  other side to align its children against.
- `counters` is a two-item list, `[source, target]`, that numbers the elements.
  `Element.order_index` becomes the `S<n>`/`T<n>` id the LLM and
  `SuggestedFixApplier` use to refer to an element, and the applier's lookup
  holds one entry per id, so the ids have to be **unique across the whole flat
  list**, not just inside one section. The counters are bumped before the
  recursive call, so the paragraphs of the first child never reuse the ids of
  the child `<div>`s. It is a mutable list rather than a tuple or two ints
  because the increments made inside a recursive call must be visible to the
  caller. The paragraph ids still increase in document order; the `<div>`
  elements use up ids too, which only leaves gaps. The whole numbering phase is
  synchronous and finishes before the first `await`, so the ids never depend
  on task scheduling.
- After the LLM pass, the commands are applied one at a time, in the order the
  verifier returned them, with a single `SuggestedFixApplier` over
  `aligned_elements`. The applier changes the list in place. A `REJECTED`
  command is logged as a warning and the run goes on.
- `align_sections` wraps both sides' `<div>` tags into `Element`s, then picks
  its aligner by how much structure it can trust, in order: if every `<div>` on
  both sides has a unique `n` attribute, `SectionNumberAligner` — the strongest
  available anchor. Otherwise, if both sides have the same number of sections,
  `PositionAligner` — correct section count is weak evidence they correspond
  1:1, but it is still evidence. Otherwise `OneBlockAligner`, which is not
  implemented and raises `NotImplementedError`.
- `Element.serialize()` / `AlignedPair.serialize()` exist specifically to turn
  these objects into the LLM-friendly dict shape consumed by
  `llm_based_verifier.py:prepare_prompt` — see
  [Shared data structures](#shared-data-structures) below for the exact shape.
  They are explicitly **not** meant for the frontend, per their docstrings;
  the frontend contract (if any) lives elsewhere.

### `File_Aligner_Modules/` — section aligners

`AlignerModule` subclasses that pair the sections (`<div>`s) of a file pair.
`main.py:align_sections` chooses between them.

**Design choices / how it works:**
- `section_number_aligner.py` — `SectionNumberAligner` pairs the sections that
  have the same `n` attribute. It builds one `{div@n: Element}` lookup per side
  (from `Element.section_number`) and walks the source side in order, then adds
  the target sections whose number is not on the source side. A `<div n="x">`
  present on only one side becomes an `AlignedPair` with the other side's
  element list empty — rather than silently dropping it, since a missing
  section is itself a finding (a candidate omission/insertion) the rest of the
  tool needs to see, not something the aligner should hide. Orphans still carry
  `AnchorMethod.SECTION_NUMBER`, not a separate "none" method: they were still
  discovered *by* section-number matching (the absence of a match on one side),
  so the field answers "which method decided this," not "did a match happen."
  It requires the numbers to be unique on each side (a lookup would overwrite a
  duplicate), which `align_sections` checks before choosing it.
- `position_aligner.py` — `PositionAligner` pairs the section at index `i` on
  one side with the section at index `i` on the other, and labels each pair
  with `str(i)` because the files it is used for have no `n` to carry. It
  raises `ValueError` when the two sides have a different number of sections.
  The pairs keep the default `AnchorMethod.POSITION`.
- `one_block_aligner.py` — `OneBlockAligner` is for sections that can't be
  matched by number or by position. It is not implemented: there is no reliable
  way to split the sections, so it raises `NotImplementedError` instead of
  guessing.
- Neither `SectionNumberAligner` nor `PositionAligner` reads the `section_label`
  argument, since every pair is labelled by its own `div@n` or its index; the
  argument is only there for the shared `align` signature.

### `distance_based_aligner.py` — `DistanceBasedAligner`

Lives in `Section_Aligner_Modules/`. The paragraph-level alignment actually
wired into the pipeline today (called from `main.py:align_individual_section`
and from `llm_based_verifier.py:main`). Where `LineBreakAligner` anchors on explicit
line numbers, `DistanceBasedAligner` has no such anchor available at the `<p>`
level and instead treats alignment as a sequence-diff problem.

**Design choices / how it works:**
- Matching two `<p>` elements by tag name alone doesn't distinguish anything —
  they're all `"p"`. `_make_counted_tag_name` instead builds a signature string
  per paragraph from how many of a chosen set of descendant tags it contains
  (e.g. `"p|lg:0-l:4-q:0"` for a paragraph with 4 `<l>` lines and no `<lg>`/`<q>`),
  counting only descendants whose nearest relevant ancestor isn't `<note>` or
  `<rdg>` (`NON_COUNTED_ANCESTORS`) — footnote text and un-chosen `<app>`
  variants aren't part of the paragraph's real content, so they shouldn't
  contribute to its structural signature. `signature_tags` is a constructor
  argument and defaults to `["lg", "l"]`, tuned for testing against sample
  `301043`; callers (e.g. `llm_based_verifier.py`) currently pass
  `["lg", "l", "q"]`.
- These signature strings are then fed to `difflib.SequenceMatcher` (with
  `autojunk=False` — the default heuristic that discounts "popular" elements
  would be actively harmful here, since a common signature like `"p|lg:0-l:0"`
  recurring across many ordinary paragraphs is exactly the kind of match this
  needs to keep), and `get_opcodes()` is walked to turn each diff op into
  `AlignedPair`s: `"equal"` → one-to-one pairs in order, `"delete"`/`"insert"`
  → orphans (source-only / target-only), `"replace"` → **one** many-to-many
  pair spanning the whole replaced range on both sides, rather than guessing
  which individual elements correspond within it. Each op has its own private
  method (`_align_equal_pairs`, `_align_delete_pairs`, `_align_insert_pairs`,
  `_align_replace_pairs`).
- `IGNORE_LIST` (`lb`, `ex`, `sup`, `pb`, `frn`) is defined but not currently
  referenced by any function in this file — it documents tags that are known
  to exist on only one language's side (editorial line breaks, abbreviation
  expansions, editor-supplied words, page breaks, foreign-word markers) and so
  would be noise if counted into a structural signature; nothing here consumes
  it yet.
- After the diff pass, the aligner runs its `refiner_modules` in sequence; the
  default is `[BoundaryShiftMerger(max_matched_between=2)]`, which merges
  adjacent orphan pairs that are more likely one shifted paragraph boundary
  than two independent omissions (see
  [`Alignment_Refiner_Modules/`](#alignment_refiner_modules--refiners)). The
  list is a constructor argument (`refiner_modules: List[AlignmentRefiner]`),
  so adding a second refinement pass later is a one-line addition to that list,
  not a change to `align`.
- The `if __name__ == "__main__"` block is a standalone smoke test against
  sample `301020B`, picking specific section numbers (`["5", "6", "7", "10",
  "12", "13", "19"]`) known from manual inspection to be worth checking, not a
  representative sample chosen programmatically. Because the file is in a
  subfolder and imports its siblings flat, `Aligner/` has to be on the path:
  `cd Aligner && PYTHONPATH=. python3 Section_Aligner_Modules/distance_based_aligner.py`.

### `line_break_aligner.py` — `LineBreakAligner`

Lives in `Section_Aligner_Modules/`. Not called by `align_files` yet. Pairs a
section's `<p>`s using the editorial line numbers, and only works on pair
`301042` so far, because the other pairs have no
`<mls unit="Irish text line">` markers in the translation.

**How it works:**

- The anchor is the `<lb n="...">` in the original and the
  `<mls unit="Irish text line" n="...">` marker the translation carries to say
  which Irish line each English `<p>` starts on. A lookup table maps each
  translation `<p>`'s start line to that `<p>`.
- For the mapping, the first `<lb>` of an original `<p>` is looked up in that
  table, and the translation `<p>` whose range of lines contains it is the
  match. `_find_containing_translation_paragraph` uses `bisect_right` over the
  ascending start lines, so the lookup is `O(log n)` per original `<p>`
  instead of a linear scan.
- It only commits to a pair when the first `<lb>` genuinely marks the *start*
  of the original `<p>` (`_is_paragraph_start`). A `<p>` whose first `<lb>` is
  partway through already has running text before it, so using that line
  number as the `<p>`'s start would be wrong. Text inside non-printed tags
  such as `<note>` does not count as running text.
- One original `<p>` to several translation `<p>`s (one to many): the start
  of the translation `<p>`s is checked, and if the corresponding line inside
  the original is in the middle of a `<p>`, the original `<p>` was split into
  several translation `<p>`s.
- Several original `<p>`s merged into one translation `<p>` (many to one): the
  opposite case. The start of the original `<p>` falls in the middle of a
  translation `<p>`.
- Neither split case is implemented. The three `# TODO` branches (a `<p>` not
  starting on its first `<lb>`; a line number before every translation `<p>`'s
  start; the merge case) are left unhandled on purpose, see
  [Known limitations](#known-limitations).

### `Alignment_Refiner_Modules/` — refiners

`alignment_refiner_abc.py` defines `AlignmentRefiner`, the base class with one
abstract method, `refine(aligned_pairs) -> List[AlignedPair]`, which takes a
list of pairs and returns a refined list. Each refiner is its own file in
`Alignment_Refiner_Modules/`.

**Design choices / how it works:**
- `boundary_shift_merger.py` — `BoundaryShiftMerger` merges orphans caused by a
  moved paragraph boundary into one many-to-many pair. Orphans from both sides
  close together are far more likely one moved boundary than two separate
  omissions, so runs with orphans from both sides and at most
  `max_matched_between` matched pairs between them are merged. The merged pair
  is a guess, to be validated later (by the LLM pass). It returns a new list,
  see its own docstring for an example.

### `llm_based_verifier.py` — LLM verification pass

The LLM stage (renamed from `LLM_based_aligner.py` once its job settled on
checking an existing alignment rather than producing one). It sends the
paragraph pairs to an LLM for a semantic check and returns the fixes the LLM
suggests as `FixCommand`s, ready for
[`SuggestedFixApplier`](#suggested_fix_applierpy--suggestedfixapplier). The
pipeline calls `verify_aligned_pairs` from `main.py:align_files`; this file's
own `main` is a standalone test run on one sample. Importing the module
requires the repo root on `sys.path`
(`sys.path.append(str(Path(__file__).resolve().parent.parent))`) so the
top-level `Utils` package resolves alongside `Aligner`'s own modules, and
`main.py` relies on that side effect to import `Utils.setup_loggin` (see
[Known limitations](#known-limitations)). It also calls `load_dotenv()` on
import, and `verify_aligned_pairs` reads `ANTHROPIC_API_KEY` from the
environment when it is not given a client.

**Design choices / how it works:**
- `prepare_prompt` builds the prompt body by calling `pair.serialize(start_index
  + i, for_llm=True)` for each pair at its index `i` in the slice passed in,
  offset by `start_index` so `pair_number` still reflects the pair's real
  position in the full document even when only one segment's slice is being
  rendered (needed now that `verify_segment` prepares one segment's prompt at
  a time rather than the whole list at once — see
  [`AlignedPair.serialize()`](#alignedpair) below), JSON-encoding each one
  (`json.dumps(..., ensure_ascii=False)`, compact unless `indent=True`), and
  joining them with a `====...====` separator line before substituting the
  result into `ALIGN_PROMPT_TEMPLATE`'s `{string_pairs}` placeholder. It is
  now `async` so it can also `save_to_file` the formatted prompt it just
  built, as `formatted_prompt_template_segment_<start>-<end>_<date>_<time>.txt`
  under `Formatted_Prompts/` — one file per segment, so every segment's exact
  prompt is inspectable after a run even though `verify_segment` fires them
  concurrently.
- `verify_segment` sends one slice of `segment_size` pairs to the model
  (`MODEL = "claude-haiku-5-5"`, `max_tokens` set by the caller via
  `max_token` rather than a hardcoded constant, since a bigger segment needs
  more room for the model's `pair_checks`/`commands` output; `output_config`
  constrained to `ALIGN_RESPONSE_SCHEMA`) and retries on failure, up to
  `max_retry` times (default `2`, so 3 attempts total), distinguishing four
  failure modes:
  - `StopIteration` — raised by the `next(... if block.type == "text")` lookup
    when the model's response has no text block at all. In practice this
    means the model was cut off (most commonly `stop_reason == "max_tokens"`)
    before it produced any output block to parse. If
    `increase_max_token_retry` is set, `max_token` is bumped by
    `TOKEN_PER_PAIR` (`1024`) and the attempt is retried with more headroom;
    otherwise it just retries as-is. This case is logged but **not** currently
    dumped to `Error_Logs/` — the `save_to_file` call for it is present in the
    source but commented out.
  - `json.JSONDecodeError` — the model returned text that didn't parse,
    despite the schema constraint — retries immediately, since the cause is
    presumed to be the model, not the network, so there's nothing to wait
    out. The exception is dumped via `save_to_file` to `Error_Logs/verifier/`
    before giving up once `max_retry` is exhausted.
  - `anthropic.APIStatusError` (a request that reached the API and got back
    an error status) — dumped to `Error_Logs/verifier/`, then checked against
    `FATAL_STATUS_CODES` (`400, 401, 403, 404, 413` — bad request, auth,
    permissions, not-found, payload-too-large): these are configuration
    problems retrying can't fix, so they return `None` immediately. Any other
    status backs off first, for `base_delay * (2 ** (attempt - 1) +
    uniform(0, 0.5))` seconds — doubling per attempt with random jitter so
    concurrent segments don't all retry in lockstep — then retries.
  - `anthropic.APIError` (the general case, e.g. a connection failure, with
    no status code to judge fatal-vs-transient by) — dumped to
    `Error_Logs/verifier/` and returns `None` immediately, with no retry.

  Every path that gives up returns `None` rather than raising, so one bad
  segment doesn't abort the whole batch; every outcome is logged.
- `verify_aligned_pairs` splits `aligned_pairs` into consecutive
  `segment_size`-sized slices (default `3`; `main.py` passes `8`) and fires
  every segment's `verify_segment` concurrently via `asyncio.gather`, sizing
  each call's token budget as `max_token=segment_size*TOKEN_PER_PAIR`. It logs
  how many segments actually succeeded (`is not None`) against the total
  segment count.
- `verify_aligned_pairs` then **returns the fix commands, not the raw
  responses**: for every segment that succeeded, each entry of its
  `"commands"` list becomes a `FixCommand` (`OPCode(command["operation"])`
  plus the four id fields, which the response schema guarantees are present,
  as an id or `null`). The commands are ordered by segment, then by the order
  the LLM listed them in, because the prompt says the commands of a segment
  are applied one after another. A segment that failed (`None`) is logged as a
  warning with its pair range and contributes no commands, so its pairs go
  unchecked; there is no logic yet to re-split or retry it (see
  [Known limitations](#known-limitations)). The `"pair_checks"` part of the
  response (one verdict and note per pair) is dropped here, only the commands
  are kept.
- `main` (`async`, run via `asyncio.run(main())`) is a standalone test of this
  stage: `setup_logging()` (`Utils.setup_loggin`, a root `StreamHandler` to
  stdout, idempotent) → load sample `301042`'s `<div0>` paragraphs →
  `DistanceBasedAligner(...).align(...)` → `verify_aligned_pairs(...,
  segment_size=8)` → `save_dict_to_json` the commands (`dataclasses.asdict`,
  since a dataclass is not JSON-serializable) to
  `LLM_Responses/verified_pairs_301043.json` under the key
  `"suggested_fix_commands"`. It does not apply them. Every stage logs its own
  start/progress through `logger = logging.getLogger(__name__)`.

### `suggested_fix_applier.py` — `SuggestedFixApplier`

Applies the `FixCommand`s the LLM suggested to the flat list of pairs. It
was extracted out of `llm_based_verifier.py` into its own module (it has no
dependency on the LLM call machinery, only on `AlignedPair`/`Element`, so
keeping it there was coupling two unrelated concerns in one file).
`main.py:align_files` creates one instance over `aligned_elements` and calls
`apply_fix` for every command in order.

**Design choices / how it works:**
- `__init__` builds `element_pair_index_lookup`, a `dict[str, int]` mapping
  every element's serialized `id` (e.g. `"S4"`, `"T2"`) to the index of the
  `AlignedPair` it currently belongs to, by calling `element.serialize(side)`
  (default `for_llm=True`, since only the `id` field is read) for every
  source and target element of every pair. The LLM's commands name elements
  by id only, so this resolves an id back to a pair position without scanning
  the list. It is rebuilt after every applied command, which is
  `O(pairs + elements)` per command: patching it would be faster, but the
  list only changes by splices and the commands are few, so the simpler code
  was chosen. Ids never disappear, they only move, so the rebuild does not
  need to clear old entries. The ids have to be unique across the whole list
  (see [`main.py`](#mainpy--pipeline-entry-point)), or entries would
  overwrite each other.
- `apply_fix(command)` dispatches on `command.opcode` and returns a
  `CommandOutcome`. `KeyError` (an id that is not in the lookup),
  `ValueError` and any other exception are caught, logged with their
  traceback and turned into `CommandOutcome.ERROR`, so one bad command from
  the LLM never stops the rest of the run. An unknown opcode is `REJECTED`.
- `_do_merge(first_element_id, last_element_id)` replaces every pair from the
  one containing the first id through the one containing the last id with one
  pair holding all their source and target elements, in order. The merged
  pair takes the first non-`None` `section_label` among the pairs it joins.
- `_do_split(last_source_id_before_split, last_target_id_before_split)` cuts
  one pair into two: the elements up to and including each operand stay in
  the first pair, the rest go to the second. It compares the two operands'
  pairs with `is`, **not** `==`: `AlignedPair` is a `@dataclass` with no
  declared fields, so `==` is `True` for any two pairs, which made a split
  across two different pairs look valid and corrupt the list (an element lost,
  another duplicated, an empty pair added). Operands in different pairs are
  `REJECTED`, because the split cannot be put back into a list that keeps the
  document order on both sides; the long comment in that branch has the
  example.
- A split with one `null` operand is not handled yet; there is a `TODO` on the
  method with the plan. A split with both operands `null` raises `ValueError`,
  which `apply_fix` turns into an `ERROR`.
- The pairs the applier creates are new `AlignedPair` objects built with only
  the elements and the section label, so they get the defaults for the other
  fields (see [Known limitations](#known-limitations)).
- The class keeps `applied_command_count`, `rejected_command_count` and
  `errored_command_count` for the summary log in `align_files`; they are not
  reliable yet (see [Known limitations](#known-limitations)).

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

Only `SECTION_NUMBER` (`SectionNumberAligner`), `STRUCTURAL_SEQUENCE`
(`DistanceBasedAligner`, `BoundaryShiftMerger`, and `LineBreakAligner`'s
pairs via the `AlignedPair` default), and `POSITION` (`PositionAligner`, and as
the `AlignedPair.__init__` default) are produced by any class or function in
this folder today. `ELEMENT_ID` and `TEXT_LENGTH` are declared for alignment
strategies described in the `Element` docstring
(length-based matching for the `<p>`-splitting experiment) but have no
producing code yet — see [Known limitations](#known-limitations).

### `Element`

Wraps one BeautifulSoup `Tag` — in practice always a `<p>` or a `<div\d?>` —
with the metadata alignment needs:

```python
Element(
    name="p",                  # input_element.name
    tag=<Tag>,                 # the wrapped BeautifulSoup element itself
    order_index=3,              # running number per side, unique across the whole flat list (main.py's counters); None if not passed
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
# for_llm=True (default) — what llm_based_verifier.py actually sends
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
    # child_pairs: list[AlignedPair] = [] — populated one level down by
    # align_individual_section's recursion; stays empty at the lowest (paragraph) level
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
`0.0`) or passes `None` explicitly (`SectionNumberAligner`).

**`serialize(id, for_llm=True)`** turns a pair into the LLM-facing dict
`llm_based_verifier.py:prepare_prompt` sends in its prompt (not the frontend —
see the docstring note under
[`main.py`](#mainpy--pipeline-entry-point) above). `id` is required
(no default) and becomes `pair_number` in the output — it's whatever the
caller wants to label the pair with, not read from the instance; `prepare_prompt`
passes `start_index + i` for the pair at index `i` of the slice it was given,
so `pair_number` is the pair's position in the whole flat list even though
each prompt only carries one segment. Like `Element.serialize()`, `for_llm`
toggles how much detail comes back:

```python
# for_llm=True (default) — what llm_based_verifier.py actually sends
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

**Example.** Pair index 1 from a real `DistanceBasedAligner(...).align(..., 1)` run on
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
    "section_label": 1,   # not a div@n here — the caller passed the literal 1 as the
                           # section_label for this whole call, since this file pair's <div0> has no n
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
    "confidence_score": 0.0,     # DistanceBasedAligner never sets this; the AlignedPair default
    "anchor_method": "structural_sequence",
    "alignment_kind": "one_to_one",  # both sides have exactly 1 element; see AlignmentKind
    "child_pairs": [],            # always empty here — DistanceBasedAligner doesn't recurse
}
```

`alignment_kind` is included in the `for_llm=False` shape so a consumer
doesn't have to re-derive one-to-one/one-to-many/orphan from the two element
lists itself — the property already computes it from
`len(source_elements)`/`len(target_elements)` on the Python side. It's still
never written back onto the instance (see [`AlignedPair`](#alignedpair)
above) — only the serialized *dict* carries it, by calling the property at
`serialize()` time. `section_label` being a made-up value rather than a real
`div@n` string is specific to this call site: `llm_based_verifier.py:main`
calls `DistanceBasedAligner(...).align(..., "1")` on this file pair's direct
`<p>` children with no section/`div` grouping in between, so there is no real
section number to carry — contrast `SectionNumberAligner`, which labels each
pair with the real `div1@n` string. (The output above was produced when the
caller still passed the int `1`; it passes the string `"1"` now.)

### `FixCommand`

A `@dataclass` holding one fix the LLM suggested. It is built by
`verify_aligned_pairs` from one entry of the response's `"commands"` list and
consumed by `SuggestedFixApplier.apply_fix`. Which fields are filled depends on
the opcode, the other ones stay `None`:

```python
FixCommand(
    opcode=OPCode.MERGE,                # OPCode.MERGE or OPCode.SPLIT
    first_element_id="S2",              # merge: first element of the range; None for a split
    last_element_id="T3",               # merge: last element of the range; None for a split
    last_source_id_before_split=None,   # split: last source element that stays in the first pair
    last_target_id_before_split=None,   # split: last target element that stays in the first pair
)
```

For a split, the prompt allows either `last_*_id_before_split` to be `null`,
meaning nothing of that side stays in the first pair (the applier does not
handle that yet, see [Known limitations](#known-limitations)). The ids are
the `S<n>`/`T<n>` strings from `Element.serialize()`; the response schema
(`ALIGN_RESPONSE_SCHEMA` in `prompt_templates.py`) only accepts the pattern
`^[ST][0-9]+$` or `null` for them. `get_string(include_opcode=False)` renders
the operands for log messages.

### `OPCode` and `CommandOutcome`

Two `StrEnum`s of the fix step. `OPCode` is `SPLIT = "split"` or `MERGE =
"merge"`, the two values of the response schema's `operation` field, so
`OPCode(command["operation"])` converts the LLM's string directly and raises
`ValueError` for any other value. `CommandOutcome` is what `apply_fix`
returns: `APPLIED` (the list changed), `REJECTED` (a well-formed command that
cannot be applied, e.g. a split across two pairs) or `ERROR` (a bad operand or
an unexpected exception).

## Pipeline

`main.py:align_files` runs these stages in order. Only the last two touch the
network or the LLM.

1. **Load**: `utils.py:load_file_pair(code)` reads `G<code>.xml` and
   `T<code>.xml` (as `iso-8859-1`) into two `BeautifulSoup` trees. The caller
   picks the section `<div>`s of each (the `__main__` block uses
   `body/div0/div1`) and passes them to `align_files`.
2. **Sections**: `align_sections` wraps the `<div>`s in `Element`s numbered
   from `0` and picks a file-level aligner (`SectionNumberAligner`,
   `PositionAligner` or `OneBlockAligner`), producing the section pairs. They
   all implement `AlignerModule.align`, so they swap without changing the
   caller. These ids restart at `0` and never reach the LLM.
3. **Elements**: `align_individual_section` goes down each section pair
   recursively and appends the paragraph-level pairs to one flat list, with the
   running `S<n>`/`T<n>` numbering described under
   [`main.py`](#mainpy--pipeline-entry-point).
4. **Verify**: `verify_aligned_pairs(flat_list, segment_size=8)` sends the list
   to the LLM in windows of 8 pairs, all windows concurrently, and returns the
   fix commands.
5. **Apply**: one `SuggestedFixApplier` over the flat list applies the commands
   in order.

```python
aligned_elements, aligned_sections = asyncio.run(align_files(original_sections, translation_sections))
```

**Contracts between the stages** (hard contracts, not style choices):
- Element ids (`S<n>`/`T<n>`) are unique across the whole flat list. The prompt
  tells the LLM to refer to elements only by id, and the applier's lookup is
  keyed by id.
- `pair_number` in the prompt is a pair's index in the flat list, not in its
  segment, so the pair numbers of different segments never overlap.
- The commands of one segment are applied in the order the LLM listed them,
  and segments in list order. A command is written by the LLM against the
  pairs as they were sent; since ids move but never change, a later command
  still resolves after an earlier one merged or split pairs.
- The flat list changes only inside the applier, and only after every window
  has returned, so the verification never sees a half-fixed list.

**Early exits.** Nothing in the chain stops the whole run once it has started
the LLM stage: a section pair with an empty side is skipped, a failed segment
is logged and contributes no commands, and a command that is `REJECTED` or
`ERROR` is logged and skipped. A missing `ANTHROPIC_API_KEY` is the exception:
`verify_aligned_pairs` raises `KeyError` before any call is made.

**Scope guard.** Only the paragraph-level (leaf) pairs are verified and fixed.
The section pairs and their `child_pairs` are never sent to the LLM and never
changed by the applier. `LineBreakAligner` is not called by `align_files`.
`Element`, `AlignedPair` and `AnchorMethod` live in `data_classes.py` and are
reused as a dependency by every aligner and refiner module.

## Known limitations

- `OneBlockAligner` (`File_Aligner_Modules/one_block_aligner.py`) is not
  implemented and raises `NotImplementedError` — reached only when sections
  can't be matched by number or by equal count, which no current sample file
  pair triggers.
- `LineBreakAligner`'s three `# TODO` branches (paragraph not
  starting on its own first `<lb>`; an Irish line before every translation
  paragraph's start; one-to-many/many-to-one splits) are unhandled; the
  function silently omits those paragraphs from its output rather than
  raising, so a caller can't currently distinguish "nothing to align" from
  "an unhandled case was skipped."
- `AnchorMethod.ELEMENT_ID` and `AnchorMethod.TEXT_LENGTH` are declared but no
  function in this folder produces either yet.
- `IGNORE_LIST` in `distance_based_aligner.py` is defined but not read by any
  function in the file.
- `Element.__init__`'s `order_index: int = None` and `start_line_number: int =
  None` are typed as plain `int` with a `None` default rather than
  `int | None` — both are genuinely optional in practice (not every caller
  passes them), it's just that the type hints don't say so.
- `confidence_score` is threaded through every `AlignedPair` but has no
  producer; every pair in this folder's output currently carries either the
  default `0.0` or an explicit `None`, not a real computed value.
- `AlignedPair.serialize()`'s `for_llm=False` branch recurses into
  `child_pairs` with `pair.serialize()` — no `id` argument — even though
  `id` is a required parameter with no default. This raises a `TypeError`
  for any pair with non-empty `child_pairs`, and `align_files` now creates
  such pairs (the section pairs whose children are `<div>`s), so
  `serialize(..., for_llm=False)` on them fails. I confirmed it with a pair
  that has one child pair. The LLM path (`for_llm=True`) never reads
  `child_pairs`, so the pipeline itself is not affected.
- `AlignedPair` is a `@dataclass` with no declared fields (it has its own
  `__init__`), so the generated `__eq__` compares two empty tuples and is
  `True` for **any** two pairs. `==`, `in` and `list.index` on pairs are
  therefore meaningless; `SuggestedFixApplier` uses `is` for this reason.
- `verify_aligned_pairs` (`llm_based_verifier.py`) skips a segment that
  exhausted its retries: the failure is logged with the segment's pair range,
  but the caller gets no machine-readable list of which pairs were left
  unchecked, and there is no retry at a smaller segment size.
- All segments of `verify_aligned_pairs` are sent at the same moment (one
  `asyncio.gather`, no limit on concurrent requests). With many pairs this can
  hit the API rate limit; the retry and back-off in `verify_segment` then
  absorb it, but a cap on concurrent calls (a shared `asyncio.Semaphore`
  around the `client.messages.create` call) is not in place.
- `verify_segment`'s `StopIteration` branch (`llm_based_verifier.py`, hit when
  the model's response has no text block) has its `save_to_file` error-dump
  call present but commented out, so unlike the other three failure modes it
  handles, nothing lands in `Error_Logs/verifier/` for this case.
- `SuggestedFixApplier._do_split` does not handle a single `null` operand: the
  prompt tells the LLM it may set one of `last_source_id_before_split` /
  `last_target_id_before_split` to `null`, but the method looks both up in the
  id lookup, so `None` raises `KeyError` and the command ends as `ERROR`. Both
  `null` raises `ValueError`, also an `ERROR`. A `TODO` on the method has the
  plan.
- The applier's command counters are wrong: `apply_fix` adds one to
  `applied_command_count` after `_do_split`/`_do_merge` returns, whatever the
  outcome, so a `REJECTED` split (operands in different pairs) is counted as
  applied, and `rejected_command_count` only ever counts unknown opcodes. The
  `Applied / Errored / Rejected` summary that `align_files` logs is therefore
  not reliable. I confirmed it with a split across two pairs, which returned
  `rejected` and left `applied_command_count == 1`.
- Pairs created by the applier (the two halves of a split, the result of a
  merge) are built from the elements and the section label only, so they get
  the `AlignedPair` defaults: `anchor_method=AnchorMethod.POSITION` and
  `confidence_score=0.0`. A fixed pair is therefore labelled as a position
  match, which says nothing about where it came from.
- `_do_merge` does not check that `first_element_id` comes before
  `last_element_id`. If it does not, the slice between them is empty, and I
  expect the splice to insert an empty merged pair, but I have not run that
  case.
- `align_individual_section` skips, without logging, two cases whose elements
  then never reach the flat list. First, a pair missing a counterpart on one
  side (an orphan section): its content is not verified, and it appears only
  in `aligned_sections`. Second, a pair where only one side has child
  `<div>`s. Also, when both sides do have child `<div>`s, only the child
  `<div>`s are aligned, so any `<p>` that sits directly under the parent
  `<div>` next to them is not collected. I have read this from the code and
  have not checked whether any CELT sample file has such mixed content.
- `main.py` gets `Utils.setup_loggin` through a side effect: it imports
  `llm_based_verifier` first, which appends the repo root to `sys.path`. The
  import breaks if that order changes. The same `sys.path` line is why the
  verifier can import `Utils` at all; making the project a proper package, or
  setting the path in one place, would remove the dependency.
