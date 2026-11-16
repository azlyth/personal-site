# Edit in place: block editing that keeps the post's look

Date: 2026-11-15. Editor: `edit.cloudy.nyc` (`editor/web/editor.js`, `editor.css`).

## Why

Tapping a block to edit it changes what Peter is looking at. A paragraph turns
into a monospace code box; a pair (picture beside text) collapses into a small
thumbnail stacked over raw markdown with three rows of full-width buttons
under it; a photo row grows a screenful of controls. The block jumps, the
page reflows, and the thing being edited stops looking like the post.

## Goals (Peter's words, in priority order)

1. **The block stays generally where it is on the page.** Opening, typing in
   and closing a block does not move it or the blocks around it. (His most
   important constraint.)
2. **It keeps the post's look.** The text being edited is set like the
   published text, and a pair stays side by side.
3. **Fewer, smaller controls.** No stacked rows of full-width buttons that
   all look equally important.

## Non-goals

- Rich-text (WYSIWYG) editing. Markdown stays visible in the field.
- Live styling of markdown as you type (headings rendered big inside the
  field, as Platen does). Possible follow-up.
- Reworking per-photo controls on a row's thumbnails (arrows, ×, Split out,
  alt text). Peter didn't flag them; they stay as they are.
- Any change to what gets written to disk.

## Anti-goals

- Anything that reconstructs markdown from rendered HTML. Every edit stays a
  line splice into the source (repo CLAUDE.md, "How the editor edits").
- Losing typing. Every guarantee in CLAUDE.md's "Text editors close on Done,
  never on blur" section (flush, re-attach, localStorage drafts, tapping
  another block saves this one) must survive unchanged.
- Controls covering the text being edited.

## Approaches

- **A. Controls in a bottom bar (picked).** One slim bar fixed to the bottom
  of the window holds the open block's controls and Done/Cancel. Nothing is
  inserted into the page, so nothing reflows; Done is always reachable on a
  tall block. Same pattern as the Proofread review bar.
- B. A toolbar floating over the block's top edge. Closer to what it changes,
  but covers the end of the previous block and scrolls away on a tall one.
- C. Rich in-place editing. Ruled out: it needs HTML -> markdown, the
  anti-goal above.

Peter picked A.

## Design

### The edit bar

- One element, `#edit-bar`, fixed to the bottom of the viewport (respecting
  `env(safe-area-inset-bottom)`), shown only while a block editor is open.
  Hidden while the Proofread review bar is up (they can't both be: review
  locks blocks) and in move/placing mode.
- While it shows, `#blocks` gets bottom padding equal to the bar's measured
  height (ResizeObserver, same idea as the add-photo button's `top`), so the
  last block can scroll above it. This padding is below every block, so it
  moves nothing.
- Contents, left to right, in groups separated by space (no text labels
  above groups, no all-caps):
  - the block's own controls that today sit in `.block-controls` / the edit
    rail (`+`, photos, spacer, layout `◨`, stop-wrap `⊟`, move `⇅`, delete
    `×`), as 44px icon buttons, each with `aria-label` and `title`;
  - the block's settings, when it has them, as compact segmented toggles
    (icon or one short word each, 44px tall):
    - size: `S` `M` (pair), `S` `M` `Full` (row);
    - side: none / `◧` / `◨` (row), `◧` / `◨` (pair);
    - prose (pair only): centred / top / spread / evenly as four small
      icons;
  - pushed to the right end: `Cancel` (text-style button, where the editor
    has one today) and `Done` (the only filled button).
- The insert menu (`above` / `below`) that `+`, `␣`, `⊟` open today pops up
  from the bar, anchored above the button that opened it.
- The text editor's rail (`.edit-rail`, `rail-side`, `RAIL_ROOM`,
  sticky row) is removed; the bar replaces it in every window size.
- Look: white, a hairline top border, the blog's text face, toggles as quiet
  outlined segments whose active state fills with the post's ink colour;
  `Done` keeps the editor's existing blue. One accent, used once.

### The block stays put

- Opening a block keeps its top edge where it was. The editing state may not
  change the block's border width or padding (`.block.editing` changes colour
  only), and the editor's body (textarea or pair) opens at the height the
  rendered block had, then grows with the content as today (`fit()`).
- The text field uses the same font family, size, line-height and width as
  the rendered block, so text does not re-wrap on open. Where the source
  differs from the rendering (`## ` prefixes, `*`, link syntax) the height
  can differ by a line; that is accepted, the top edge must still not move.
- Closing restores the rendered block with no jump.
- The scroll position does not change on open or close, and no
  `scrollIntoView` runs unless the field would sit under the bar, in which
  case it scrolls just enough to clear it.

### The post's look

- The editor loads the blog's two families from Fontshare, one `<link>`
  each (Sentient for headings, Switzer for text; see CLAUDE.md "Typography"
  for why they must be separate links), and uses them for rendered blocks
  AND for the text fields. Monospace stays only where the editor shows raw
  HTML (the raw-markup fallback textarea for blocks that can't be parsed).
- A heading block's field is set in Sentient at that heading level's size.
- A pair opens as a pair: same flex layout, media column on the chosen side
  showing the real picture at its size, prose field in the text column.
  Changing size, side or prose position in the bar updates the open pair
  immediately. The pair's photo tools (alt text, preview star) are reached
  from a `Photo` button in the bar, which opens the existing thumbnail strip
  in a sheet above the bar.
- A photo or clip row keeps its thumbnail strip (unchanged), but its size and
  side rows move into the bar, so the open row is the strip and nothing else.

### Calls made after review (Claude's, for Peter to check)

1. **Closed blocks keep their hover controls unchanged.** Only an OPEN
   block's controls move into the bar. Deleting or moving a spacer or photo
   row still works without opening it.
2. **The `◨` layout strip is gone from the open block.** Its contents become
   bar controls: a row's side and size toggles, `Pair` (today's "⧉ Centre")
   or `Unpair`, and a spacer's `Everywhere / Desktop only`. Settings
   (size, side, prose position, desktop-only) are a working copy saved on
   Done, like the row editor's framing today. `Pair` / `Unpair` change the
   block's structure, so they act immediately, as they do now (after
   flushing the open editor). On a CLOSED block, `◨` is dropped from the
   hover controls; layout is changed by opening the block.
3. **"Stays put" means the block's top edge.** For text and pairs the next
   block must also stay within 2px. A photo or clip row's strip is taller
   than the row (alt fields, arrows, Split out), so for rows only the
   block's own top is pinned and blocks below may move. The strip itself is
   unchanged.
4. **The pair's `Photo` sheet holds alt text and the preview star only**
   (images only; a video pair gets no `Photo` button). Reorder, remove, add
   and Split out stay where they are: Unpair the section first. Alt edits
   count as changes for the pair editor's dirty check and are sent through
   the existing `PUT .../pair` media field.
5. **A paragraph beside a float edits at the narrow width** for its whole
   height (today's `flow-root` behaviour). Its top stays put; its text may
   re-wrap and the block may grow. The 2px check skips text blocks that sit
   beside a float.
6. **Soft keyboard.** The bar must stay above an on-screen keyboard: set
   `interactive-widget=resizes-content` on the editor's viewport meta and
   position the bar from `visualViewport` as a fallback. Headless checks
   can't prove this; it needs one manual check on Peter's tablet.

## Testing

- `scripts/verify-edit-tap.py` keeps every existing review case except the
  rail-position ones, which become bar cases. New checks at 1024x1366,
  1366x1024 and 820x1180:
  - opening a paragraph, a heading and a pair leaves that block's top and
    the next block's top within 2px of where they were; a photo row keeps
    its own top within 2px; `window.scrollY` unchanged;
  - the bar is visible, at the viewport bottom, with Done reachable, and no
    control overlaps the open field;
  - the field's computed font family matches the rendered block's;
  - a pair stays side by side while open, and flipping side in the bar flips
    it live; Done with unchanged media writes the same markdown the old pair editor wrote;
  - every bar button is a 44px target.
- `scripts/verify-proofread.py` and `scripts/verify-add-photo.py` still pass
  (both interact with the bar's neighbours).
- The pytest suite: the size-preset parity test still holds; add a test that
  `editor.css` and `templates/base.html` name the same two font families.

## Left to the builder

Icons for the prose-position toggles, the bar's exact spacing and wrap
behaviour on narrow windows (it may wrap to two rows below ~700px), and the
sheet's styling for the pair photo strip.
