// Editor front end. Blocks render as HTML; tapping one swaps in its raw
// markdown, so the source is always what gets edited and saved.
//
// `moveIndex` is null outside move mode, or the index (as the client
// currently sees the block list) of the block picked up by the Move
// control. While set, renderBlocks() renders the post exactly as normal and
// overlays the drop zones on top -- see renderMoveOverlay().
// `wrapOpen` holds the indices whose layout controls are showing. They're
// hidden by default: a picture usually just sits there, and an always-on
// strip under every one of them is noise in a post you're reading back.
// `pendingInsert` is null, or `{index, source, label}` for a block whose
// insert is waiting on an above-or-below answer.
const state = {
  slug: null, hash: null, url: null, blocks: [], moveIndex: null,
  wrapOpen: new Set(), pendingInsert: null, canUndo: false,
};

const els = {
  picker: document.getElementById('post-picker'),
  newPost: document.getElementById('new-post'),
  title: document.getElementById('post-title'),
  meta: document.getElementById('post-meta'),
  blocks: document.getElementById('blocks'),
  status: document.getElementById('status'),
  undo: document.getElementById('undo'),
  discard: document.getElementById('discard'),
  publish: document.getElementById('publish'),
};

function setStatus(text) {
  els.status.textContent = text;
}

// Every write route can answer with a non-2xx that isn't the 409
// staleness case -- a bad date, an unreadable image, oversized upload,
// malformed alts JSON, etc. Centralize pulling the server's `detail` out
// of that body (falling back to the status text) so every fetch call
// site handles it the same way instead of falling through the success
// path with an error body.
async function errorDetail(res, fallback) {
  try {
    const body = await res.json();
    return body.detail || fallback || res.statusText;
  } catch {
    // Body wasn't JSON (or was empty) -- fall back below.
  }
  return fallback || res.statusText;
}

async function loadPostList() {
  let res;
  try {
    res = await fetch('/api/posts');
  } catch (err) {
    setStatus(`couldn't load post list — network error: ${err.message}`);
    return [];
  }
  if (!res.ok) {
    setStatus("couldn't load post list");
    return [];
  }
  const posts = await res.json();
  els.picker.innerHTML = posts
    .map((p) => `<option value="${p.slug}">${p.title}${p.draft ? ' (draft)' : ''}</option>`)
    .join('');
  return posts;
}

async function loadPost(slug) {
  let res;
  try {
    res = await fetch(`/api/posts/${slug}`);
  } catch (err) {
    setStatus(`couldn't load ${slug} — network error: ${err.message}`);
    return;
  }
  if (!res.ok) {
    setStatus(`couldn't load ${slug} — ${await errorDetail(res)}`);
    return;
  }
  const data = await res.json();
  state.slug = data.slug;
  state.hash = data.hash;
  state.blocks = data.blocks;
  state.url = data.url;
  setCanUndo(data.can_undo);

  els.title.textContent = data.meta.title;
  renderMeta(data.meta);
  renderBlocks();
  setStatus('');
}

function startEditingTitle() {
  if (els.title.dataset.editing) return;
  els.title.dataset.editing = '1';

  const input = document.createElement('input');
  input.type = 'text';
  input.value = els.title.textContent;
  input.className = 'title-input';
  els.title.textContent = '';
  els.title.appendChild(input);
  input.focus();

  input.addEventListener('blur', async () => {
    delete els.title.dataset.editing;
    await saveMeta({ title: input.value });
  });
}

async function saveMeta(fields) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/meta`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...fields, hash: state.hash }),
    });
  } catch (err) {
    // Same rule as the non-OK branch below: don't touch `state`, just
    // report it -- there's no response body to have clobbered anything with.
    setStatus(`save failed — network error: ${err.message}`);
    return;
  }

  if (res.status === 409) {
    setStatus('changed on disk — reload');
    return;
  }
  if (!res.ok) {
    // Don't touch `state` or re-render -- an error body has no `hash` or
    // `meta`, and stomping state.hash with `undefined` would fail every
    // subsequent save. Leave the field exactly as the user left it.
    setStatus(`save failed — ${await errorDetail(res)}`);
    return;
  }

  const data = await res.json();
  state.hash = data.hash;
  setCanUndo(data.can_undo);
  els.title.textContent = data.meta.title;
  renderMeta(data.meta);
  setStatus('saved');
  await refreshStatus();
}

function renderMeta(meta) {
  els.meta.innerHTML = '';

  // The photo pinned as this post's link preview, "" for the default. Kept
  // on `state` because the star buttons live down in the block editors and
  // are built long after this runs -- see previewPickButton().
  state.previewImage = meta.preview_image || '';

  const date = document.createElement('input');
  date.type = 'date';
  date.value = meta.date;
  date.addEventListener('change', () => saveMeta({ date: date.value }));

  const draftLabel = document.createElement('label');
  const draft = document.createElement('input');
  draft.type = 'checkbox';
  draft.checked = meta.draft;
  draft.addEventListener('change', () => saveMeta({ draft: draft.checked }));
  draftLabel.append(draft, document.createTextNode(' draft'));

  // The slug isn't part of MetaEdit -- renaming a post's file is a separate
  // route (POST .../rename) because it moves the file via `git mv` instead
  // of just rewriting frontmatter, and it breaks the post's existing URL.
  // Surface that as a deliberate, separate action rather than folding it
  // into the date/draft row, and always show the warning it returns -- that
  // warning is the whole point of the confirm step, not decoration.
  const renameBtn = document.createElement('button');
  renameBtn.type = 'button';
  renameBtn.className = 'rename-slug';
  renameBtn.textContent = `/blog/${state.slug}/`;
  renameBtn.title = 'Change the URL slug';
  renameBtn.addEventListener('click', renameSlug);

  // Straight to the published page. A draft isn't built at all, so the link
  // would 404 -- say so in the title rather than hiding it, since "where is
  // my post" is exactly the question a draft raises.
  const live = document.createElement('a');
  live.className = 'live-link';
  live.href = state.url;
  live.target = '_blank';
  live.rel = 'noopener';
  live.textContent = '↗ View live';
  if (meta.draft) {
    live.classList.add('unpublished');
    live.title = "This post is a draft — it isn't on the live site yet, so this will 404";
  } else {
    live.title = 'Open the published post in a new tab';
  }

  els.meta.append(date, draftLabel, renameBtn, live);

  // The override, where you can see it. A pinned photo is otherwise only
  // visible by opening the block that holds it, and the whole point of an
  // override is that it is not the one the default rule would have picked.
  // Nothing shows when it isn't pinned: the default is "the last photo in
  // the post", which the templates derive from the RENDERED page, and
  // re-deriving it here from the source blocks would be a second
  // implementation to keep in step with the first.
  if (state.previewImage) {
    const chip = document.createElement('span');
    chip.className = 'preview-chip';

    const thumb = document.createElement('img');
    thumb.src = state.previewImage;
    thumb.alt = '';

    const label = document.createElement('span');
    label.textContent = 'preview';

    const clear = document.createElement('button');
    clear.type = 'button';
    clear.textContent = '×';
    clear.title = 'Stop pinning this photo — go back to the default (the last photo in the post)';
    clear.addEventListener('click', () => saveMeta({ preview_image: '' }));

    chip.append(thumb, label, clear);
    els.meta.append(chip);
  }

  refreshPreviewPicks();
}

// A star pinning one photo as the post's link preview -- the picture Reddit,
// iMessage and a feed reader show for it. Unpinned, the site falls back to
// the last photo in the post (templates/macros/preview.html), which is right
// often enough that this is an override rather than a required step.
//
// It commits immediately rather than joining the row editor's local working
// copy, for the same reason "Split out" does: it isn't a property of the row
// at all, it's a frontmatter field, and the row's Done would have no place
// to put it.
function previewPickButton(url) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'preview-pick';
  btn.dataset.url = url;
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    saveMeta({ preview_image: btn.dataset.url === state.previewImage ? '' : url });
  });
  paintPreviewPick(btn);
  return btn;
}

function paintPreviewPick(btn) {
  const pinned = btn.dataset.url === state.previewImage;
  btn.classList.toggle('is-pinned', pinned);
  btn.textContent = pinned ? '★' : '☆';
  btn.setAttribute('aria-pressed', String(pinned));
  btn.title = pinned
    ? "This is the post's link preview — tap to go back to the default"
    : "Use this photo as the post's link preview";
}

// Repaint in place rather than re-rendering the blocks: pinning happens from
// inside an OPEN photo editor, and renderBlocks() would close it and throw
// away every un-saved alt-text edit and reorder sitting in its working copy.
function refreshPreviewPicks() {
  document.querySelectorAll('.preview-pick').forEach(paintPreviewPick);
}

async function renameSlug() {
  const current = state.slug;
  const next = prompt('New URL slug:', current);
  if (!next || next === current) return;

  setStatus('renaming…');
  let res;
  try {
    res = await fetch(`/api/posts/${current}/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_slug: next, hash: state.hash }),
    });
  } catch (err) {
    setStatus(`rename failed — network error: ${err.message}`);
    return;
  }

  if (res.status === 409) {
    setStatus('changed on disk — reload');
    return;
  }
  if (!res.ok) {
    setStatus(`rename failed — ${await errorDetail(res)}`);
    return;
  }

  const data = await res.json();
  alert(data.warning);
  await loadPostList();
  els.picker.value = data.slug;
  await loadPost(data.slug);
}

function renderBlocks() {
  // The overlay's observer points at nodes that are about to be thrown away.
  stopWatchingLayout();
  els.blocks.innerHTML = '';
  // Move mode doesn't rebuild the list -- it renders exactly what you were
  // looking at and overlays the drop zones, so the page doesn't shift under
  // you the moment you pick a block up.
  els.blocks.classList.toggle('moving', state.moveIndex !== null);

  state.blocks.forEach((block) => {
    const el = document.createElement('div');
    el.className = 'block';
    el.dataset.index = block.index;

    // A floated row floats its whole BLOCK, not just the row inside it.
    // Letting the row escape its block left the block a full-width,
    // zero-height box lying across the picture: hovering the photo lit up
    // whichever paragraph's box happened to overlap it, that paragraph's
    // absolutely-positioned controls landed on top of the photo, and the
    // photo's own controls appeared far away at the top-right of its
    // invisible block. Floating the block gives it the picture's real
    // dimensions, so hover, click and controls all land where the picture is.
    if (isMediaRow(block) && block.side && block.side !== 'none') {
      el.classList.add(`beside-${block.side}`, `size-${block.size}`);
    }

    // The marker that ends a beside run renders as nothing on the published
    // page. Here it has to be legible, or an invisible block sits in the
    // middle of the post with no way to understand or remove it.
    if (block.kind === 'clear') el.classList.add('clear-block');
    if (block.kind === 'spacer') {
      el.classList.add('spacer-block');
      // Shown at its real height either way: the editor runs on a tablet,
      // above the breakpoint, so a desktop-only gap genuinely IS here. It
      // just has to say so -- see the label below and editor.css.
      if (block.desktop_only) el.classList.add('desktop-only');
    }

    // Dimmed and labelled in place: the block being moved stays exactly
    // where it is, which is the whole point of overlaying the drop zones
    // rather than rebuilding the list.
    if (state.moveIndex === block.index) el.classList.add('move-source');

    // Content lives in its own child so the per-block editors below can
    // wipe and rebuild *just this* -- blockControls() (Move, delete, ...)
    // is appended to `el` as a sibling, not a descendant of `content`, so
    // opening an editor can never take the controls out with it. See
    // startEditing/startEditingImages/startEditingVideos.
    const content = document.createElement('div');
    content.className = 'block-content';
    if (block.kind === 'clear') {
      content.textContent = 'text stops wrapping here';
    } else if (block.kind === 'spacer') {
      content.textContent = block.desktop_only ? 'space · desktop only' : 'space';
    } else {
      content.innerHTML = block.html;
    }
    el.appendChild(content);

    el.addEventListener('click', () => {
      // A photo block (a standalone image or an .img-row) gets a thumbnail
      // strip -- add/remove/reorder/alt-text -- instead of raw markup in a
      // textarea. Gate on `images` actually being present, not just
      // `kind`: the server omits it whenever the block's markup can't be
      // losslessly reproduced from a parsed list (a missing alt, an extra
      // element, hand-edited HTML the parser doesn't recognize, ...). For
      // those, falling into the thumbnail editor would show a wrong or
      // empty photo list, and Done would happily write that reduced list
      // back -- silently dropping whatever didn't parse. Raw source
      // editing is always safe, so that's the fallback.
      if (block.kind === 'pair' && block.text !== undefined) {
        startEditingPair(el, content, block);
      } else if (block.images) {
        startEditingImages(el, content, block);
      } else if (block.videos) {
        // Same gating rule as photos: only present when videos.parse_videos
        // could losslessly round-trip this block's markup (see
        // startEditingVideos below) -- otherwise raw source is the only
        // safe way to edit it.
        startEditingVideos(el, content, block);
      } else {
        startEditing(el, content, block);
      }
    });
    el.appendChild(blockControls(block));

    if (state.pendingInsert && state.pendingInsert.index === block.index) {
      el.appendChild(insertChoice(block));
    }

    // The wrap picker lives inside the block, so a floated row carries it
    // along; it's behind the ◨ toggle rather than always on, since a strip
    // under every picture is noise when reading a post back.
    if (state.wrapOpen.has(block.index)) {
      if (isMediaRow(block)) el.appendChild(wrapControl(block));
      else if (block.kind === 'pair' && block.text !== undefined) {
        el.appendChild(unpairControl(block));
      } else if (block.kind === 'spacer') el.appendChild(spacerControl(block));
    }

    els.blocks.appendChild(el);

    if (canMergeWithNext(block.index)) {
      els.blocks.appendChild(mergeControl(block.index));
    }
  });

  // Overlaid last, once every block is laid out: the zones are placed
  // from the blocks' measured positions.
  if (state.moveIndex !== null) renderMoveOverlay();
}

// The Small/Medium/Full and Beside-text controls are mutually constrained: a
// full-width row can't float, because a row capped at 100% leaves the text no
// column to flow into (editor/videos.py refuses the combination outright). So
// picking a side narrows a full-width row to medium, and picking Full drops
// the side. Both row editors show this pair, and the constraint has to live in
// one place or the two will drift apart.
//
// Returns the element plus live getters -- the callers read `.size`/`.side`
// when Done (or Split) fires, not when this is built.
function framingControls(initialSize, initialSide, options = {}) {
  let size = initialSize;
  let side = initialSide || 'none';
  // A pair is a picture BESIDE something, so it has no unfloated state and
  // no full width -- taking either away is what Unpair is for.
  const sideChoices = options.sides || ['none', 'left', 'right'];
  const sizeChoices = options.sides ? ['small', 'medium'] : ['small', 'medium', 'full'];

  const wrap = document.createElement('div');
  wrap.className = 'framing-controls';

  function buttonRow(className, options, isActive, onPick) {
    const row = document.createElement('div');
    row.className = className;
    options.forEach(([value, label]) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = label;
      btn.dataset.value = value;
      if (isActive(value)) btn.classList.add('active');
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        onPick(value);
        repaint();
      });
      row.appendChild(btn);
    });
    return row;
  }

  const sizes = buttonRow(
    'size-buttons',
    [['small', 'Small'], ['medium', 'Medium'], ['full', 'Full']]
      .filter(([v]) => sizeChoices.includes(v)),
    (v) => v === size,
    (v) => {
      size = v;
      // Nothing can float at full width -- see above.
      if (size === 'full') side = 'none';
    },
  );

  const sideLabel = document.createElement('span');
  sideLabel.className = 'framing-label';
  sideLabel.textContent = 'Beside text';

  const sides = buttonRow(
    'side-buttons',
    [['none', 'No'], ['left', '◧ Left'], ['right', 'Right ◨']]
      .filter(([v]) => sideChoices.includes(v)),
    (v) => v === side,
    (v) => {
      side = v;
      // Floating implies picking a width, and medium is the one that still
      // leaves a readable measure beside it -- same rule the server applies
      // in the one-tap "put beside this text" action.
      if (side !== 'none' && size === 'full') size = 'medium';
    },
  );

  function repaint() {
    sizes.querySelectorAll('button').forEach((b) => {
      b.classList.toggle('active', b.dataset.value === size);
    });
    sides.querySelectorAll('button').forEach((b) => {
      b.classList.toggle('active', b.dataset.value === side);
    });
  }

  wrap.append(sizes, sideLabel, sides);
  return {
    el: wrap,
    get size() { return size; },
    get side() { return side; },
  };
}

// A block's "family" for merge purposes -- `images`/`videos` are only
// present when the server's parse_images/parse_videos could losslessly
// round-trip this block's markup (same gate the click handler above uses to
// decide raw vs. structured editing), so keying off those fields here means
// the merge control can never appear for a block the server would refuse to
// merge anyway.
function mergeFamily(block) {
  if (block.images) return 'photo';
  if (block.videos) return 'video';
  return null;
}

function canMergeWithNext(index) {
  const upper = state.blocks[index];
  const lower = state.blocks[index + 1];
  if (!upper || !lower) return false;
  const family = mergeFamily(upper);
  return family !== null && family === mergeFamily(lower);
}

// A full-width, thumb-sized strip between two mergeable blocks -- distinct
// from the small icon buttons in blockControls() since this acts on a pair
// of blocks, not just the one it's attached to.
function mergeControl(index) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'merge-control';
  btn.textContent = '⇄ Merge with block below';
  btn.title = 'Combine this block and the one below into a single row';
  // Same reasoning as blockControls()'s bar-level mousedown guard: this can
  // be tapped while an unrelated block's textarea still has focus, and
  // without this, that tap's own mousedown-triggered blur can destroy this
  // button mid-click via renderBlocks().
  btn.addEventListener('mousedown', (e) => e.preventDefault());
  btn.addEventListener('click', async () => {
    // Neither merge candidate is ever a plain-textarea block (mergeFamily()
    // only fires for photo/video pairs), but some *other*, unrelated block
    // on the page can still have unsaved text open -- and mousedown above
    // suppressed the blur that would have saved it. Flush before merging,
    // same as every blockControls() action.
    if (!(await flushPendingEdit())) return;
    mergeBlock(index);
  });
  return btn;
}

// True for a media ROW the server could losslessly round-trip -- the same
// gate canMergeWithNext() uses, so a control can never appear for a row the
// server would refuse to touch.
//
// A pair is explicitly not one. It reports `images`/`videos` too (its media
// column holds an ordinary row, which is what lets the thumbnail editor
// drive it), but it is a self-contained section: it takes the Unpair control
// rather than the wrap picker, and it starts no wrap for anything after it.
function isMediaRow(block) {
  return block.kind !== 'pair' && mergeFamily(block) !== null;
}

// How the text flows around a media row. Just a side -- page widths are
// fluid, so how much text ends up beside a row isn't knowable when the post
// is written; the text simply wraps and returns to full width once it's past
// the picture. (This replaced a mode that had you select a fixed set of
// blocks to sit alongside, which couldn't survive a change of screen width.)
//
// It lives inside the row's own block, so when that block floats the picker
// floats with it and lands under the picture automatically.
function wrapControl(block) {
  const side = block.side || 'none';
  const wrap = document.createElement('div');
  wrap.className = 'wrap-control';
  // It sits inside the block, whose own click opens the row editor.
  wrap.addEventListener('click', (e) => e.stopPropagation());

  const label = document.createElement('span');
  label.textContent = 'Text wraps:';
  wrap.appendChild(label);

  [['none', 'No'], ['left', '◧ Left'], ['right', 'Right ◨']].forEach(([value, text]) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = text;
    btn.dataset.value = value;
    if (value === side) btn.classList.add('active');
    btn.title = value === 'none'
      ? 'Full width, on its own line'
      : `Sit on the ${value} with the text running past it`;
    btn.addEventListener('mousedown', (e) => e.preventDefault());
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (value === side) return;
      if (!(await flushPendingEdit())) return;
      setRowSide(block, value);
    });
    wrap.appendChild(btn);
  });

  // Only a floated row can become a paired section -- a pair is a picture
  // BESIDE something, and on an unfloated row the section boundary would
  // mean nothing. Offered here because this is where the author is already
  // deciding how the picture relates to the words.
  if (side !== 'none') {
    const pair = document.createElement('button');
    pair.type = 'button';
    pair.className = 'pair-button';
    pair.textContent = '⧉ Centre';
    pair.title = 'Pair the picture with the section beside it, vertically centred';
    pair.addEventListener('mousedown', (e) => e.preventDefault());
    pair.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!(await flushPendingEdit())) return;
      pairBlock(block.index);
    });
    wrap.appendChild(pair);
  }

  return wrap;
}

// Under a paired section: take it back apart into a floated row and loose
// blocks. The picture keeps its side and a stop marker goes back in, so the
// section's boundary survives the round trip.
function unpairControl(block) {
  const wrap = document.createElement('div');
  wrap.className = 'wrap-control';
  wrap.addEventListener('click', (e) => e.stopPropagation());

  const label = document.createElement('span');
  label.textContent = 'Paired section:';
  wrap.appendChild(label);

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.textContent = '⤢ Unpair';
  btn.title = 'Split back into a picture and separate text blocks';
  btn.addEventListener('mousedown', (e) => e.preventDefault());
  btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!(await flushPendingEdit())) return;
    unpairBlock(block.index);
  });
  wrap.appendChild(btn);
  return wrap;
}

// Under a spacer: where the gap applies. A phone renders the post as one
// narrow column, so a deliberate section break can read as a scroll of blank
// screen there while being exactly right on a wide screen -- this is how you
// say "only where there's room". Nothing needs a route of its own: the two
// shapes differ by a class, so the toggle is an ordinary block edit.
function spacerControl(block) {
  const wrap = document.createElement('div');
  wrap.className = 'wrap-control';
  // It sits inside the block, whose own click opens the raw source editor.
  wrap.addEventListener('click', (e) => e.stopPropagation());

  const label = document.createElement('span');
  label.textContent = 'Space shows:';
  wrap.appendChild(label);

  [[false, 'Everywhere', SPACER_SOURCE, 'A gap on every screen'],
   [true, 'Desktop only', DESKTOP_SPACER_SOURCE, 'A gap on wide screens, nothing on a phone'],
  ].forEach(([value, text, source, title]) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = text;
    btn.title = title;
    if (value === Boolean(block.desktop_only)) btn.classList.add('active');
    btn.addEventListener('mousedown', (e) => e.preventDefault());
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (value === Boolean(block.desktop_only)) return;
      if (!(await flushPendingEdit())) return;
      saveBlock(block.index, source);
    });
    wrap.appendChild(btn);
  });

  return wrap;
}

async function pairBlock(index) {
  await postBlockAction(index, 'pair', 'pairing…');
}

async function unpairBlock(index) {
  await postBlockAction(index, 'unpair', 'unpairing…');
}

// Both take nothing but the block and the staleness hash, so they share a
// single call site rather than two near-identical fetch blocks.
async function postBlockAction(index, action, status) {
  setStatus(status);
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hash: state.hash }),
    });
  } catch (err) {
    setStatus(`${action} failed — network error: ${err.message}`);
    return;
  }
  await applyWrite(res);
}

// Nothing here needs a route of its own: a side is an ordinary property of
// the row, so this is the same save the row editor performs. A full-width
// row can't float (the text would have no column left, and the server
// refuses the combination), so choosing a side narrows it to medium -- the
// same rule framingControls() applies.
function setRowSide(block, side) {
  const size = side !== 'none' && block.size === 'full' ? 'medium' : block.size;
  if (block.images) saveBlockImages(block.index, block.images, size, side);
  else if (block.videos) saveBlockVideos(block.index, block.videos, size, side);
}

async function mergeBlock(index) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}/merge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hash: state.hash }),
    });
  } catch (err) {
    setStatus(`save failed — network error: ${err.message}`);
    return;
  }
  await applyWrite(res);
}

// If a plain-paragraph block's textarea is open with unsaved changes, save
// it the way blurring it normally would -- and report whether that actually
// landed. Every control-bar action below calls this first: those buttons'
// mousedown now has preventDefault() on it (see the comment on `bar`
// below), which stops the browser's default blur, which is what used to
// trigger startEditing()'s save-on-blur. Without an explicit flush here,
// tapping a control -- even one that only inserts/moves/deletes some *other*
// block -- would silently sail past unsaved text and then wipe it out from
// under the user the moment the action's own renderBlocks() call rebuilds
// the page from `state`, which never saw the edit. Only a plain textarea
// needs this: the photo/video thumbnail editors have no field that
// autosaves-on-blur (their local `images`/`clips` working copy only ever
// gets written on an explicit Done), so there's nothing to flush there.
async function flushPendingEdit() {
  const textarea = document.querySelector('.block.editing textarea');
  if (!textarea) return true;
  const el = textarea.closest('.block');
  const index = Number(el.dataset.index);
  const block = state.blocks[index];
  if (!block || textarea.value === block.source) return true;
  return await saveBlock(index, textarea.value);
}

// The stop-wrap marker's exact source -- must match blocks.py's _CLEAR_RE,
// which is what promotes it to the `clear` kind (and so to a labelled
// divider here rather than an invisible empty block).
const CLEAR_SOURCE = '<div class="clear-beside"></div>';
// Plain breathing room between sections. Same shape rule as CLEAR_SOURCE:
// must match blocks.py's _SPACER_RE to come back as the `spacer` kind.
const SPACER_SOURCE = '<div class="post-spacer"></div>';
// The same gap, kept off phones -- base.html collapses it to nothing inside
// the same 700px query that unfloats rows. Inserted only by the toggle under
// an existing spacer, never by the ␣ button: which spacer you want is a thing
// you see once the gap is there, not before.
const DESKTOP_SPACER_SOURCE = '<div class="post-spacer desktop-only"></div>';

// True when a float is still wrapping text at this point in the post: scan
// back for a media row with a side, stopping at any marker that already
// ended one. Used to offer the stop-wrap control only where it would
// actually do something, rather than on every block in every post.
function wrapIsActiveAt(index) {
  for (let i = index - 1; i >= 0; i--) {
    const block = state.blocks[i];
    if (block.kind === 'clear') return false;
    if (isMediaRow(block) && block.side && block.side !== 'none') return true;
  }
  return false;
}

function blockControls(block) {
  const bar = document.createElement('div');
  bar.className = 'block-controls';

  // These controls are now reachable while a *different* block's textarea
  // still has focus (that's the whole point of keeping them alive during
  // editing -- see renderBlocks()). A real tap's mousedown blurs whatever
  // textarea is focused before its own click fires; startEditing()'s blur
  // handler reacts to that by calling renderBlocks() synchronously, which
  // replaces this exact button out from under the in-flight click. The
  // browser then has no element to fire 'click' on, so the tap silently
  // does nothing -- reproduced live via CDP (mousePressed/mouseReleased),
  // not just theorized. preventDefault() on mousedown is the standard fix
  // (how toolbar buttons coexist with a focused text field): it suppresses
  // the browser's default "blur the focused element" behavior without
  // suppressing the click that follows.
  //
  // That trade requires flushPendingEdit() below: suppressing the blur
  // also suppresses the save startEditing()'s blur handler used to trigger,
  // so every handler here does that save itself, explicitly, before acting.
  bar.addEventListener('mousedown', (e) => e.preventDefault());

  const add = document.createElement('button');
  add.textContent = '+';
  add.title = 'Insert a paragraph';
  add.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!(await flushPendingEdit())) return;
    askWhereToInsert(block.index, 'New paragraph.', 'a paragraph');
  });

  const del = document.createElement('button');
  del.textContent = '×';
  del.title = 'Delete this block';
  del.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!confirm('Delete this block?')) return;
    if (!(await flushPendingEdit())) return;
    removeBlock(block.index);
  });

  const photo = document.createElement('button');
  photo.textContent = '🖼';
  photo.title = 'Add photos here';
  photo.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!(await flushPendingEdit())) return;
    pickImages(block.index);
  });

  // Shows/hides this block's layout controls. Only on the things that HAVE
  // any: a picture, a clip, a paired section, or a spacer.
  let layout = null;
  const isPair = block.kind === 'pair' && block.text !== undefined;
  if (isMediaRow(block) || isPair || block.kind === 'spacer') {
    layout = document.createElement('button');
    layout.textContent = '◨';
    // A spacer has no text to wrap -- its one choice is which screens the
    // gap applies to -- so the button says what it opens.
    layout.title = block.kind === 'spacer' ? 'Where this space applies' : 'Text wrapping';
    if (state.wrapOpen.has(block.index)) layout.classList.add('active');
    layout.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!(await flushPendingEdit())) return;
      if (state.wrapOpen.has(block.index)) state.wrapOpen.delete(block.index);
      else state.wrapOpen.add(block.index);
      renderBlocks();
    });
  }

  const spacer = document.createElement('button');
  spacer.textContent = '␣';
  spacer.title = 'Insert a spacer — blank space between sections';
  spacer.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!(await flushPendingEdit())) return;
    askWhereToInsert(block.index, SPACER_SOURCE, 'a spacer');
  });

  // Only where a float is still wrapping -- elsewhere it would insert a
  // block that does nothing.
  let stop = null;
  if (wrapIsActiveAt(block.index)) {
    stop = document.createElement('button');
    stop.textContent = '⊟';
    stop.title = 'Stop the text wrapping here — start a new full-width section';
    stop.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (!(await flushPendingEdit())) return;
      askWhereToInsert(block.index, CLEAR_SOURCE, 'the stop');
    });
  }

  const move = document.createElement('button');
  move.textContent = '⇅';
  move.title = 'Move this block';
  move.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!(await flushPendingEdit())) return;
    enterMoveMode(block.index);
  });

  bar.append(...[add, photo, spacer, layout, stop, move, del].filter(Boolean));
  return bar;
}

// Move mode: every block, plus a target above the first and below the
// last (N+1 targets for N blocks), gets a big tappable "place here" drop
// zone. `state.moveIndex` names the block the client is moving -- gap `i`
// in this render is exactly `to_index` in the move route, the same "gap
// in the block list as the client currently sees it" convention
// move_block() uses server-side, so no translation happens on the way in.
function enterMoveMode(index) {
  state.moveIndex = index;
  renderBlocks();
}

function cancelMove() {
  stopWatchingLayout();
  state.moveIndex = null;
  renderBlocks();
}

// The drop zones and the banner are OVERLAID, never inserted: both are
// absolutely/fixed positioned, so they occupy no space and picking a block
// up doesn't reflow a single thing. The blocks themselves are the ones
// already on screen -- move mode used to swap in its own previews, and even
// small differences between those and the real blocks moved the page around
// just when you were trying to aim at it.
// Watches the blocks while move mode is open so the zones can follow them.
// Disconnected whenever the overlay is torn down or rebuilt.
let moveResize = null;

function stopWatchingLayout() {
  if (moveResize) moveResize.disconnect();
  moveResize = null;
}

// Lay each zone on the boundary it names. `offsetTop` is measured against
// #blocks, which is the layer's own containing block, so this needs no
// arithmetic about margins or floats.
//
// Called again whenever anything resizes, because at first render the
// pictures have not loaded: an <img> with no intrinsic size yet is zero
// pixels tall, so every block below it measures too high and the bars end up
// scattered across the post instead of between its blocks.
function positionMoveZones() {
  const layer = els.blocks.querySelector('.move-layer');
  if (!layer) return;
  const blocks = [...els.blocks.querySelectorAll('.block')];
  const zones = [...layer.children];
  blocks.forEach((el, i) => {
    if (zones[i]) zones[i].style.top = `${el.offsetTop}px`;
  });
  const last = blocks[blocks.length - 1];
  if (last && zones[blocks.length]) {
    zones[blocks.length].style.top = `${last.offsetTop + last.offsetHeight}px`;
  }
}

function renderMoveOverlay() {
  stopWatchingLayout();

  const banner = document.createElement('div');
  banner.className = 'move-banner';
  const label = document.createElement('span');
  label.textContent = 'Moving a block — tap where it should land';
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'move-cancel';
  cancel.textContent = 'Cancel';
  cancel.title = 'Leave move mode without moving anything';
  cancel.addEventListener('click', cancelMove);
  banner.append(label, cancel);
  // Sits directly under the sticky toolbar. Measured rather than hard-coded:
  // the bar's height depends on its own contents and the font, and a guess
  // that drifts would either cover the toolbar or float below it.
  const bar = document.querySelector('.bar');
  banner.style.top = `${bar ? Math.round(bar.getBoundingClientRect().height) : 0}px`;
  els.blocks.appendChild(banner);

  const layer = document.createElement('div');
  layer.className = 'move-layer';
  const blocks = [...els.blocks.querySelectorAll('.block')];
  for (let gap = 0; gap <= blocks.length; gap++) {
    const target = document.createElement('button');
    target.type = 'button';
    target.className = 'move-target';
    target.title = 'Place the block here';
    target.addEventListener('click', () => submitMove(state.moveIndex, gap));
    layer.appendChild(target);
  }
  els.blocks.appendChild(layer);
  positionMoveZones();

  // A ResizeObserver rather than image `load` handlers: it catches every
  // reason the layout can move -- pictures arriving, a video's metadata
  // landing, fonts swapping in, the window changing width -- with one
  // mechanism instead of a list of them.
  moveResize = new ResizeObserver(() => requestAnimationFrame(positionMoveZones));
  blocks.forEach((el) => moveResize.observe(el));
  moveResize.observe(els.blocks);
}

async function submitMove(fromIndex, toIndex) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${fromIndex}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to_index: toIndex, hash: state.hash }),
    });
  } catch (err) {
    // A thrown network error, not a non-2xx response -- there's no
    // response to hand to applyWrite. Nothing was written, but leaving the
    // drop-target UI up with a stuck "saving…" would strand the user
    // mid-move with no way out but Cancel; drop back to the normal view
    // the same way a successful move would, just without the reorder.
    state.moveIndex = null;
    renderBlocks();
    setStatus(`save failed — network error: ${err.message}`);
    return;
  }
  // Only leave move mode on success. applyWrite already leaves `state` and
  // the DOM untouched on a 409 or any other failure -- `moveIndex` gets
  // exactly the same treatment, so a failed move doesn't silently drop the
  // user back into normal view with nothing actually moved.
  if (res.ok) state.moveIndex = null;
  await applyWrite(res);
}

function pickImages(index) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.multiple = true;

  input.addEventListener('change', async () => {
    if (!input.files.length) return;

    const alts = [];
    for (const file of input.files) {
      alts.push(prompt(`Alt text for ${file.name} (describes the photo):`, '') || '');
    }

    const form = new FormData();
    for (const file of input.files) form.append('files', file);
    form.append('alts', JSON.stringify(alts));
    form.append('index', index);
    form.append('hash', state.hash);

    setStatus(`uploading ${input.files.length} photo(s)…`);
    let res;
    try {
      res = await fetch(`/api/posts/${state.slug}/images`, {
        method: 'POST',
        body: form,
      });
    } catch (err) {
      setStatus(`upload failed — network error: ${err.message}`);
      return;
    }
    await applyWrite(res);
  });

  input.click();
}

// Both inserting controls ask which side of the block they meant, rather
// than silently picking one. "Above" was the old behaviour and was wrong
// about half the time -- and with the picture and the divider both hanging
// off a block, guessing wrong means an undo and a retry every other go.
function askWhereToInsert(index, source, label) {
  state.pendingInsert = { index, source, label };
  renderBlocks();
}

function insertChoice(block) {
  const { index, source, label } = state.pendingInsert;

  const wrap = document.createElement('div');
  wrap.className = 'insert-choice';
  wrap.addEventListener('click', (e) => e.stopPropagation());

  const title = document.createElement('span');
  title.textContent = `Insert ${label}:`;
  wrap.appendChild(title);

  // `insert_block` inserts BEFORE the index it's given, and accepts the
  // block count itself as "append" -- so "below the last block" needs no
  // special case.
  [['↑ Above', index], ['↓ Below', index + 1]].forEach(([text, at]) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = text;
    btn.addEventListener('mousedown', (e) => e.preventDefault());
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      state.pendingInsert = null;
      insertBlock(at, source);
    });
    wrap.appendChild(btn);
  });

  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'insert-cancel';
  cancel.textContent = 'Cancel';
  cancel.addEventListener('mousedown', (e) => e.preventDefault());
  cancel.addEventListener('click', (e) => {
    e.stopPropagation();
    state.pendingInsert = null;
    renderBlocks();
  });
  wrap.appendChild(cancel);

  return wrap;
}

async function insertBlock(index, source = 'New paragraph.') {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index, source, hash: state.hash }),
    });
  } catch (err) {
    setStatus(`save failed — network error: ${err.message}`);
    return;
  }
  await applyWrite(res);
}

async function removeBlock(index) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hash: state.hash }),
    });
  } catch (err) {
    setStatus(`save failed — network error: ${err.message}`);
    return;
  }
  await applyWrite(res);
}

async function applyWrite(res) {
  if (res.status === 409) {
    setStatus('changed on disk — reload');
    return false;
  }
  if (!res.ok) {
    // As in saveMeta: don't touch `state` or call renderBlocks() -- that
    // would wipe out whatever's still sitting in an open textarea with an
    // error body's `undefined` fields. Leave the editing UI exactly as is.
    setStatus(`save failed — ${await errorDetail(res)}`);
    return false;
  }
  const data = await res.json();
  state.hash = data.hash;
  state.blocks = data.blocks;
  setCanUndo(data.can_undo);
  renderBlocks();
  setStatus('saved');
  await refreshStatus();
  // Callers that need to know whether the write actually landed --
  // flushPendingEdit() is the one that matters here -- get an honest
  // answer instead of having to re-derive it from side effects.
  return true;
}

// The Undo button is only as honest as `can_undo`, which every post payload
// carries -- including each write's own response, since the client renders
// from that rather than reloading.
function setCanUndo(canUndo) {
  state.canUndo = Boolean(canUndo);
  els.undo.disabled = !state.canUndo;
}

async function undoEdit() {
  if (!state.canUndo) return;
  // Same reason every control-bar action flushes: the bar's mousedown
  // preventDefault suppresses the blur that would have saved an open
  // textarea, so without this an Undo would step back past text that was
  // never written in the first place.
  if (!(await flushPendingEdit())) return;

  setStatus('undoing…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/undo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hash: state.hash }),
    });
  } catch (err) {
    setStatus(`undo failed — network error: ${err.message}`);
    return;
  }
  await applyWrite(res);
}

async function discardEdits() {
  if (!confirm(
    'Throw away every change to this post since the last publish?\n\n'
    + 'You can still get it back with Undo.'
  )) return;
  if (!(await flushPendingEdit())) return;

  setStatus('discarding…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/discard`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hash: state.hash }),
    });
  } catch (err) {
    setStatus(`discard failed — network error: ${err.message}`);
    return;
  }
  await applyWrite(res);
}

async function refreshStatus() {
  let data;
  try {
    data = await (await fetch('/api/status')).json();
  } catch (err) {
    // This only drives the publish button's label/enabled state, and every
    // caller has already set its own status line for whatever it just did
    // -- don't stomp that with a network-error message over a "saved" that
    // already happened. The button just keeps its previous state.
    console.error('refreshStatus failed:', err);
    return;
  }
  els.publish.disabled = data.clean;
  if (data.clean) {
    els.publish.textContent = 'Published';
  } else if (data.dirty.length > 0) {
    els.publish.textContent = `Publish (${data.dirty.length})`;
  } else {
    // Tree is clean but a prior commit never made it live (push or the S3
    // publish failed) -- leave the button live so there's a way to retry
    // without needing to make a throwaway edit first.
    els.publish.textContent = 'Retry publish';
  }
}

// Both sit next to a focusable title field and the block textareas, so they
// need the same mousedown guard the block control bar carries -- see
// blockControls() for why suppressing the blur is what keeps the tap alive.
els.undo.addEventListener('mousedown', (e) => e.preventDefault());
els.undo.addEventListener('click', undoEdit);
els.discard.addEventListener('mousedown', (e) => e.preventDefault());
els.discard.addEventListener('click', discardEdits);

els.publish.addEventListener('click', async () => {
  const message = prompt('Commit message:', `Update ${state.slug}`);
  if (message === null) return;

  els.publish.disabled = true;
  setStatus('publishing…');

  let res;
  try {
    res = await fetch('/api/publish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });
  } catch (err) {
    // Without this, a thrown network error here leaves the button
    // disabled and the status stuck on "publishing…" forever with no way
    // to tell anything went wrong or to retry.
    setStatus(`publish failed — network error: ${err.message}`);
    await refreshStatus();
    return;
  }
  const data = await res.json();

  setStatus(data.message);
  await refreshStatus();
});

function startEditing(el, content, block) {
  if (el.classList.contains('editing')) return;
  el.classList.add('editing');
  content.innerHTML = '';

  const textarea = document.createElement('textarea');
  textarea.value = block.source;
  textarea.rows = Math.max(2, block.source.split('\n').length + 1);
  content.appendChild(textarea);
  textarea.focus();

  textarea.addEventListener('blur', async () => {
    if (textarea.value === block.source) {
      // Nothing changed, so there's nothing to save -- restore this block
      // (controls included) the same robust way every other exit path
      // does: a full renderBlocks() from current state, which can't drift
      // from what renderBlocks() actually builds.
      renderBlocks();
      return;
    }
    // Don't clear `editing` here -- saveBlock()/applyWrite() renders fresh
    // from the server on success (which drops the class along with
    // everything else), and on a 409/failed save leaves the DOM untouched
    // on purpose so the textarea and its edits survive. Clearing the class
    // up front used to desync the `.editing` style from that: a failed
    // save left the textarea open but visually "not editing".
    await saveBlock(block.index, textarea.value);
  });
}

async function saveBlock(index, source) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, hash: state.hash }),
    });
  } catch (err) {
    setStatus(`save failed — network error: ${err.message}`);
    return false;
  }
  return await applyWrite(res);
}

// Thumbnail editor for an `image`/`img_row` block. All markup generation
// (standalone vs. .img-row, alt-text escaping) stays server-side -- this
// only ever collects/reorders a list of {url, alt} and hands it to
// PUT .../blocks/{index}/images, which regenerates the source via the same
// markdown_for() the upload route uses.
function startEditingImages(el, content, block) {
  if (el.classList.contains('editing')) return;
  el.classList.add('editing');
  content.innerHTML = '';

  // A local working copy -- nothing here touches `state` until Done saves.
  const images = block.images.map((img) => ({ ...img }));

  const strip = document.createElement('div');
  strip.className = 'image-strip';
  content.appendChild(strip);

  function renderThumbs() {
    strip.innerHTML = '';
    images.forEach((img, i) => {
      const thumb = document.createElement('div');
      thumb.className = 'image-thumb';

      const preview = document.createElement('img');
      preview.src = img.url;
      preview.alt = img.alt;
      thumb.appendChild(preview);

      // Overlaid on the picture rather than added to the controls row below
      // it: that row is already three 44px buttons across a 140px thumb, and
      // the comment on "Split out" spells out what a fourth one costs.
      thumb.appendChild(previewPickButton(img.url));

      const altInput = document.createElement('input');
      altInput.type = 'text';
      altInput.className = 'image-alt-input';
      altInput.placeholder = 'alt text';
      altInput.value = img.alt;
      altInput.addEventListener('input', () => {
        img.alt = altInput.value;
      });
      thumb.appendChild(altInput);

      const controls = document.createElement('div');
      controls.className = 'image-thumb-controls';

      const left = document.createElement('button');
      left.type = 'button';
      left.className = 'image-move';
      left.textContent = '←';
      left.title = 'Move left';
      left.disabled = i === 0;
      left.addEventListener('click', (e) => {
        e.stopPropagation();
        [images[i - 1], images[i]] = [images[i], images[i - 1]];
        renderThumbs();
      });

      const right = document.createElement('button');
      right.type = 'button';
      right.className = 'image-move';
      right.textContent = '→';
      right.title = 'Move right';
      right.disabled = i === images.length - 1;
      right.addEventListener('click', (e) => {
        e.stopPropagation();
        [images[i], images[i + 1]] = [images[i + 1], images[i]];
        renderThumbs();
      });

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'image-remove';
      remove.textContent = '×';
      remove.title = 'Remove this photo';
      remove.addEventListener('click', (e) => {
        e.stopPropagation();
        images.splice(i, 1);
        renderThumbs();
      });

      controls.append(left, right, remove);
      thumb.appendChild(controls);

      // Its own full-width row rather than a fourth button beside the other
      // three: at thumbnail width a fourth would squeeze each below the 44px
      // touch target the rest of these controls are sized to. Same shape and
      // same reasoning as the video row's Split out.
      const split = document.createElement('button');
      split.type = 'button';
      split.className = 'image-thumb-split';
      split.textContent = 'Split out';
      split.title = 'Move this photo into a row of its own, below';
      // A one-photo row already is its own row, and the server rejects it --
      // disable rather than let the tap fail.
      split.disabled = images.length < 2;
      split.addEventListener('click', (e) => {
        e.stopPropagation();
        splitBlockImage(block.index, images, framing.size, framing.side, i);
      });
      thumb.appendChild(split);
      strip.appendChild(thumb);
    });

    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'image-add';
    add.textContent = '+ Add photo';
    add.addEventListener('click', (e) => {
      e.stopPropagation();
      addPhotosToStrip();
    });
    strip.appendChild(add);
  }

  function addPhotosToStrip() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.multiple = true;

    input.addEventListener('change', async () => {
      if (!input.files.length) return;

      const alts = [];
      for (const file of input.files) {
        alts.push(prompt(`Alt text for ${file.name} (describes the photo):`, '') || '');
      }

      const form = new FormData();
      for (const file of input.files) form.append('files', file);
      form.append('alts', JSON.stringify(alts));

      setStatus(`uploading ${input.files.length} photo(s)…`);
      let res;
      try {
        res = await fetch(`/api/posts/${state.slug}/images/upload`, {
          method: 'POST',
          body: form,
        });
      } catch (err) {
        setStatus(`upload failed — network error: ${err.message}`);
        return;
      }
      if (!res.ok) {
        // Same rule as applyWrite: an error body has no `images` field, so
        // leave the strip exactly as the user left it rather than pushing
        // `undefined`.
        setStatus(`upload failed — ${await errorDetail(res)}`);
        return;
      }
      const data = await res.json();
      images.push(...data.images);
      renderThumbs();
      setStatus('');
    });

    input.click();
  }

  // Same Small/Medium/Full + Beside-text control as the video row editor --
  // server-side, choosing a non-default size (or a side) on a lone photo is
  // what promotes it from plain markdown to a wrapped, sized `.img-row` (see
  // images.py's markdown_for); the button UI itself doesn't need to know that.
  const framing = framingControls(block.size, block.side);
  content.appendChild(framing.el);

  const actions = document.createElement('div');
  actions.className = 'image-editor-actions';

  const done = document.createElement('button');
  done.type = 'button';
  done.className = 'image-done';
  done.textContent = 'Done';
  done.addEventListener('click', (e) => {
    e.stopPropagation();
    // Removing the last thumbnail and hitting Done deletes the whole block
    // (PUT .../images with an empty list -- see the server route). That's
    // a legitimate action, but unlike deleting a paragraph it's easy to
    // reach by just clearing thumbnails one at a time without meaning to
    // lose the block's placement and alt text (the photo itself is still
    // in S3, but nothing here points at it anymore). Confirm first.
    if (images.length === 0 && !confirm('Remove this photo block?')) return;
    saveBlockImages(block.index, images, framing.size, framing.side);
  });

  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'image-cancel';
  cancel.textContent = 'Cancel';
  cancel.addEventListener('click', (e) => {
    e.stopPropagation();
    // Re-render from current state instead of hand-patching `content` --
    // nothing was saved, so state.blocks is exactly what it was before
    // editing started, and a full renderBlocks() restores this block
    // (controls included) by construction rather than by trying to
    // remember everything renderBlocks() itself sets up.
    renderBlocks();
  });

  actions.append(done, cancel);
  content.appendChild(actions);

  renderThumbs();
}

async function saveBlockImages(index, images, size, side) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}/images`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ images, size, side, hash: state.hash }),
    });
  } catch (err) {
    setStatus(`save failed — network error: ${err.message}`);
    return;
  }
  // applyWrite re-renders every block from the fresh server response on
  // success, and on failure leaves the DOM untouched -- exactly right here
  // too: a failed save keeps the thumbnail editor open with the user's
  // reorder/remove/alt-text edits intact, not silently discarded.
  await applyWrite(res);
}

// Editor for a paired section. Its picture is an ordinary row stored inside
// the pair, so the existing thumbnail strip drives it unchanged; what's new
// is the prose, which is edited as markdown in one textarea rather than as
// separate blocks. That's the trade the pair makes: a section becomes one
// thing, so it is edited as one thing.
function startEditingPair(el, content, block) {
  if (el.classList.contains('editing')) return;
  el.classList.add('editing');
  content.innerHTML = '';

  const media = block.images
    ? { images: block.images.map((i) => ({ ...i })) }
    : { videos: block.videos.map((v) => ({ ...v })) };

  const preview = document.createElement('div');
  preview.className = 'pair-edit-media';
  // Built as nodes rather than one innerHTML string so a photo can carry the
  // preview star. A pair's picture needs it as much as a row's does -- the
  // photos in guerilla-gardening are mostly inside pairs -- and a <video>
  // deliberately doesn't get one: og:image has to be a picture a crawler can
  // fetch, not a frame nobody has rendered.
  (block.images || block.videos || []).forEach((item) => {
    const cell = document.createElement('div');
    cell.className = 'pair-edit-thumb';
    if (block.images) {
      const img = document.createElement('img');
      img.src = item.url;
      img.alt = '';
      cell.append(img, previewPickButton(item.url));
    } else {
      const clip = document.createElement('video');
      clip.src = item.url;
      clip.muted = true;
      clip.playsInline = true;
      cell.appendChild(clip);
    }
    preview.appendChild(cell);
  });
  content.appendChild(preview);

  const area = document.createElement('textarea');
  area.className = 'pair-text-input';
  area.value = block.text;
  area.rows = Math.max(6, block.text.split('\n').length + 1);
  content.appendChild(area);

  const framing = framingControls(block.size, block.side, { sides: ['left', 'right'] });
  content.appendChild(framing.el);

  // How the prose sits against the picture. Its own row rather than a fourth
  // state on the side buttons: side and justify are independent, and a
  // spread section is still a left- or right-hand one.
  const justifyLabel = document.createElement('span');
  justifyLabel.className = 'framing-label';
  justifyLabel.textContent = 'Prose sits';
  const justify = document.createElement('div');
  justify.className = 'side-buttons';
  let chosen = block.justify || 'center';
  [['center', 'Centred'], ['top', 'Top'], ['spread', 'Spread'], ['evenly', 'Evenly']]
    .forEach(([value, text]) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = text;
    btn.dataset.value = value;
    if (value === chosen) btn.classList.add('active');
    btn.title = {
      center: 'Centred against the picture',
      top: 'Aligned with the top of the picture',
      spread: 'Flush top and bottom, all the slack between the blocks',
      evenly: 'Equal gaps everywhere, including above and below',
    }[value];
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      chosen = value;
      justify.querySelectorAll('button').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
    });
    justify.appendChild(btn);
  });
  content.append(justifyLabel, justify);

  const actions = document.createElement('div');
  actions.className = 'image-editor-actions';

  const done = document.createElement('button');
  done.type = 'button';
  done.className = 'image-done';
  done.textContent = 'Done';
  done.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!area.value.trim()) {
      alert('A paired section needs some text. Unpair it if you want just the picture.');
      return;
    }
    saveBlockPair(block.index, area.value, framing.size, framing.side, chosen, media);
  });

  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'image-cancel';
  cancel.textContent = 'Cancel';
  cancel.addEventListener('click', (e) => {
    e.stopPropagation();
    renderBlocks();
  });

  actions.append(done, cancel);
  content.appendChild(actions);
  area.focus();
}

async function saveBlockPair(index, text, size, side, justify, media) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}/pair`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, size, side, justify, ...media, hash: state.hash }),
    });
  } catch (err) {
    setStatus(`save failed — network error: ${err.message}`);
    return;
  }
  await applyWrite(res);
}

// Row editor for a `video` block. Same shape as startEditingImages above --
// a local working copy of {url, sync_loop} clips plus a `size` preset,
// nothing touching `state` until Done saves via
// PUT .../blocks/{index}/videos, which regenerates the source server-side
// through videos.markdown_for(). No alt-text input (a <video> carries
// none); sync_loop is preserved as opaque data, not user-editable here.
function startEditingVideos(el, content, block) {
  if (el.classList.contains('editing')) return;
  el.classList.add('editing');
  content.innerHTML = '';

  const clips = block.videos.map((v) => ({ ...v }));

  const strip = document.createElement('div');
  strip.className = 'video-strip';
  content.appendChild(strip);

  function renderThumbs() {
    strip.innerHTML = '';
    clips.forEach((clip, i) => {
      const thumb = document.createElement('div');
      thumb.className = 'video-thumb';

      const preview = document.createElement('video');
      preview.src = clip.url;
      preview.muted = true;
      preview.playsInline = true;
      preview.controls = true;
      thumb.appendChild(preview);

      const controls = document.createElement('div');
      controls.className = 'video-thumb-controls';

      const left = document.createElement('button');
      left.type = 'button';
      left.className = 'video-move';
      left.textContent = '←';
      left.title = 'Move left';
      left.disabled = i === 0;
      left.addEventListener('click', (e) => {
        e.stopPropagation();
        [clips[i - 1], clips[i]] = [clips[i], clips[i - 1]];
        renderThumbs();
      });

      const right = document.createElement('button');
      right.type = 'button';
      right.className = 'video-move';
      right.textContent = '→';
      right.title = 'Move right';
      right.disabled = i === clips.length - 1;
      right.addEventListener('click', (e) => {
        e.stopPropagation();
        [clips[i], clips[i + 1]] = [clips[i + 1], clips[i]];
        renderThumbs();
      });

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'video-remove';
      remove.textContent = '×';
      remove.title = 'Remove this clip';
      remove.addEventListener('click', (e) => {
        e.stopPropagation();
        clips.splice(i, 1);
        renderThumbs();
      });

      controls.append(left, right, remove);
      thumb.appendChild(controls);

      // Its own full-width row rather than a fourth button beside the other
      // three: at 140px a fourth would squeeze each below the 44px touch
      // target the rest of these controls are sized to.
      const split = document.createElement('button');
      split.type = 'button';
      split.className = 'video-thumb-split';
      split.textContent = 'Split out';
      split.title = 'Move this clip into a row of its own, below';
      // A one-clip row already is its own row, and the server rejects it --
      // disable rather than let the tap fail.
      split.disabled = clips.length < 2;
      split.addEventListener('click', (e) => {
        e.stopPropagation();
        splitBlockVideo(block.index, clips, framing.size, framing.side, i);
      });
      thumb.appendChild(split);

      strip.appendChild(thumb);
    });

    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'video-add';
    add.textContent = '+ Add clip';
    add.addEventListener('click', (e) => {
      e.stopPropagation();
      addVideosToStrip();
    });
    strip.appendChild(add);
  }

  function addVideosToStrip() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'video/*';
    input.multiple = true;

    input.addEventListener('change', async () => {
      if (!input.files.length) return;

      const form = new FormData();
      for (const file of input.files) form.append('files', file);

      setStatus(`uploading ${input.files.length} clip(s)…`);
      let res;
      try {
        res = await fetch(`/api/posts/${state.slug}/videos/upload`, {
          method: 'POST',
          body: form,
        });
      } catch (err) {
        setStatus(`upload failed — network error: ${err.message}`);
        return;
      }
      if (!res.ok) {
        // Same rule as the photo strip's addPhotosToStrip: an error body
        // has no `videos` field, so leave the strip exactly as the user
        // left it rather than pushing `undefined`.
        setStatus(`upload failed — ${await errorDetail(res)}`);
        return;
      }
      const data = await res.json();
      clips.push(...data.videos);
      renderThumbs();
      setStatus('');
    });

    input.click();
  }

  const framing = framingControls(block.size, block.side);
  content.appendChild(framing.el);

  const actions = document.createElement('div');
  actions.className = 'image-editor-actions';

  const done = document.createElement('button');
  done.type = 'button';
  done.className = 'image-done';
  done.textContent = 'Done';
  done.addEventListener('click', (e) => {
    e.stopPropagation();
    // Same confirm-before-delete rule as the photo strip: clearing every
    // clip and hitting Done deletes the whole block.
    if (clips.length === 0 && !confirm('Remove this video row?')) return;
    saveBlockVideos(block.index, clips, framing.size, framing.side);
  });

  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'image-cancel';
  cancel.textContent = 'Cancel';
  cancel.addEventListener('click', (e) => {
    e.stopPropagation();
    // Same reasoning as the photo strip's Cancel: re-render from current
    // state (nothing was saved) instead of hand-patching `content`, so
    // this block -- controls included -- comes back exactly as
    // renderBlocks() would build it fresh, not as a manual reconstruction
    // that can drift from that.
    renderBlocks();
  });

  actions.append(done, cancel);
  content.appendChild(actions);

  renderThumbs();
}

// Commits immediately rather than waiting for Done, for the same reason the
// video split does: it changes the block LIST, and this editor's local
// `images` array has no way to represent a photo that now lives in a
// different block. The row's current photos ride along so an unsaved
// reorder or alt-text edit lands in the same write.
async function splitBlockImage(index, images, size, side, split) {
  setStatus('splitting…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}/images/split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ images, size, side, split, hash: state.hash }),
    });
  } catch (err) {
    setStatus(`split failed — network error: ${err.message}`);
    return;
  }
  await applyWrite(res);
}

async function saveBlockVideos(index, clips, size, side) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}/videos`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ videos: clips, size, side, hash: state.hash }),
    });
  } catch (err) {
    setStatus(`save failed — network error: ${err.message}`);
    return;
  }
  await applyWrite(res);
}

// Unlike the strip's other controls, splitting commits immediately instead of
// waiting for Done: it changes the block LIST, and this editor's local `clips`
// array has no way to represent a clip that now lives in a different block.
// The row's current clips ride along so an unsaved reorder lands in the same
// write rather than being discarded. applyWrite() then re-renders from server
// state, which closes this editor -- the new row is already on screen below.
async function splitBlockVideo(index, clips, size, side, split) {
  setStatus('splitting…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}/videos/split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ videos: clips, size, side, split, hash: state.hash }),
    });
  } catch (err) {
    setStatus(`split failed — network error: ${err.message}`);
    return;
  }
  await applyWrite(res);
}

async function newPost() {
  const title = prompt('Title for the new post:');
  if (!title) return;

  setStatus('creating…');
  let res;
  try {
    res = await fetch('/api/posts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
  } catch (err) {
    setStatus(`could not create — network error: ${err.message}`);
    return;
  }

  if (!res.ok) {
    setStatus(await errorDetail(res, 'could not create'));
    return;
  }

  const data = await res.json();
  await loadPostList();
  els.picker.value = data.slug;
  await loadPost(data.slug);
  setStatus('created (draft)');
}

els.picker.addEventListener('change', () => loadPost(els.picker.value));
els.newPost.addEventListener('click', newPost);
els.title.addEventListener('click', startEditingTitle);

(async function main() {
  try {
    const posts = await loadPostList();
    const fromPath = location.pathname.startsWith('/edit/')
      ? location.pathname.slice('/edit/'.length)
      : null;
    const slug = fromPath || (posts[0] && posts[0].slug);
    if (slug) {
      els.picker.value = slug;
      await loadPost(slug);
    }
    await refreshStatus();
  } catch (err) {
    setStatus(`error: ${err.message}`);
  }
})();
