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
  // Whether the Links panel (the post's primary URL and its redirects) is
  // open. Survives re-renders so adding a link doesn't snap it shut.
  linksOpen: false,
  // Whether the primary row in the Links panel is showing its editor
  // (an input + Save/Cancel) instead of the plain "primary" badge.
  editingPrimary: false,
  // Null, or the proofread review in progress -- see the Proofread section.
  // While set, blocks show their red/green marks and none can be edited.
  review: null,
  // Null, or the Add photo placement in progress -- see the Add photo
  // section. While set, the post is overlaid with move mode's drop lines.
  placing: null,
};

const els = {
  picker: document.getElementById('post-picker'),
  newPost: document.getElementById('new-post'),
  title: document.getElementById('post-title'),
  meta: document.getElementById('post-meta'),
  links: document.getElementById('post-links'),
  blocks: document.getElementById('blocks'),
  status: document.getElementById('status'),
  undo: document.getElementById('undo'),
  discard: document.getElementById('discard'),
  publish: document.getElementById('publish'),
  signOut: document.getElementById('sign-out'),
  proofread: document.getElementById('proofread'),
  proofProgress: document.getElementById('proof-progress'),
  proofCancel: document.getElementById('proof-cancel'),
  reviewBar: document.getElementById('review-bar'),
  addPhoto: document.getElementById('add-photo'),
  addPhotoInput: document.getElementById('add-photo-input'),
};

// A note that has to survive the statuses that follow it for a moment --
// "Photo not added" when another action cancels a placement, which that
// action's own "saving…"/"saved" would otherwise overwrite at once.
let statusNote = null;
let statusText = '';

function setStatus(text) {
  statusText = text;
  const note = statusNote && Date.now() < statusNote.until ? statusNote.text : '';
  els.status.textContent = [text, note].filter(Boolean).join(' ');
}

// Added after whatever the status says now, and kept after the statuses
// that follow for `ms`.
function noteStatus(text, ms = 8000) {
  statusNote = { text, until: Date.now() + ms };
  setStatus(statusText);
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
  if (data.slug !== state.slug) state.linksOpen = false;
  applyPost(data);
  setStatus('');
  offerDrafts();
}

// Render a whole post payload -- the initial load, and any write whose
// response can change more than the blocks (links, Make primary, Undo).
function applyPost(data) {
  // A review belongs to one post: its indices, hashes and marks mean
  // nothing on another one (Delete draft, a rename, a stray load). The
  // callers leave it first; this is the backstop.
  if (data.slug !== state.slug) closeReview();
  // Any other write lands a new block list, so the gaps a placement is
  // aiming at (and any line already tapped) no longer mean what they did.
  cancelPlacing({ render: false, dropped: true });
  const renamed = state.slug !== null && data.slug !== state.slug;
  state.slug = data.slug;
  state.hash = data.hash;
  state.blocks = data.blocks;
  state.url = data.url;
  setCanUndo(data.can_undo);

  if (!els.title.dataset.editing) els.title.textContent = data.meta.title;
  renderMeta(data.meta);
  renderBlocks();
  if (renamed) rememberSlugInUrl(data.slug);
}

// A tab opened at /edit/<slug> reloads to that slug, so once the post moves
// (Make primary) or goes (Delete draft) the address bar has to follow.
function rememberSlugInUrl(slug) {
  if (!location.pathname.startsWith('/edit/')) return;
  history.replaceState(null, '', slug ? `/edit/${slug}` : '/');
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

// The meta write in flight, if any. A title edit saves on blur, which fires
// just before a tap on a placement line -- placeAt waits for it, or the
// place would go out on the hash the meta write is about to replace.
let metaWrite = null;

function saveMeta(fields) {
  const write = saveMetaNow(fields);
  metaWrite = write;
  write.finally(() => { if (metaWrite === write) metaWrite = null; });
  return write;
}

async function saveMetaNow(fields) {
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

  // Where the post lives. Tapping it opens the Links panel underneath:
  // the primary URL plus any others that redirect to it. Behind a toggle
  // for the same reason as the ◨ layout controls -- most posts have one
  // link and nothing to do about it.
  const aliases = meta.aliases || [];
  const linksBtn = document.createElement('button');
  linksBtn.type = 'button';
  linksBtn.className = 'links-toggle';
  linksBtn.classList.toggle('is-open', state.linksOpen);
  linksBtn.setAttribute('aria-expanded', String(state.linksOpen));
  linksBtn.textContent = `/blog/${state.slug}/`;
  if (aliases.length) {
    const more = document.createElement('span');
    more.className = 'links-count';
    more.textContent = `+${aliases.length}`;
    linksBtn.append(more);
  }
  linksBtn.title = 'Links: change the URL, or add others that redirect here';
  linksBtn.addEventListener('click', () => {
    state.linksOpen = !state.linksOpen;
    renderMeta(meta);
  });

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

  els.meta.append(date, draftLabel, linksBtn, live);

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

  // Only a draft can be thrown away; the server refuses anything else.
  if (meta.draft) {
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'bar-action danger delete-draft';
    del.textContent = 'Delete draft';
    del.title = 'Delete this draft for good';
    del.addEventListener('mousedown', (e) => e.preventDefault());
    del.addEventListener('click', deleteDraft);
    els.meta.append(del);
  }

  renderLinks(aliases);
  refreshPreviewPicks();
}

// The Links panel. The primary is the post's filename and can't be removed;
// every other link is a Zola alias -- a redirect page pointing at the
// primary. "Make primary" swaps one in, and the old primary becomes a
// redirect in the same step, so no link ever stops working.
function renderLinks(aliases) {
  els.links.innerHTML = '';
  els.links.hidden = !state.linksOpen;
  if (!state.linksOpen) return;

  const heading = document.createElement('div');
  heading.className = 'links-heading';
  heading.textContent = 'Links';
  const note = document.createElement('span');
  note.className = 'links-note';
  note.textContent = 'Others redirect to the primary. Changes go live on Publish.';
  heading.append(note);
  els.links.append(heading);

  els.links.append(state.editingPrimary ? primaryEditRow(aliases) : primaryRow(aliases));
  for (const alias of aliases) els.links.append(linkRow(alias));

  const add = document.createElement('form');
  add.className = 'link-add';
  const prefix = document.createElement('span');
  prefix.className = 'link-prefix';
  prefix.textContent = '/blog/';
  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = 'another-link';
  input.autocapitalize = 'none';
  input.autocomplete = 'off';
  input.spellcheck = false;
  input.setAttribute('aria-label', 'New link slug');
  const suffix = document.createElement('span');
  suffix.className = 'link-prefix';
  suffix.textContent = '/';
  const button = document.createElement('button');
  button.type = 'submit';
  button.className = 'link-action';
  button.textContent = 'Add';
  add.append(prefix, input, suffix, button);
  add.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!input.value.trim()) return;
    linkWrite(`/api/posts/${state.slug}/links`, 'POST', { slug: input.value }, 'adding link');
  });
  els.links.append(add);

  if (state.editingPrimary) {
    const input = els.links.querySelector('.link-row-edit input[type="text"]');
    input?.focus();
    input?.select();
  }
}

// The primary row as plain display: its URL, the "primary" badge, and an
// Edit button that swaps this same row for primaryEditRow()'s input.
function primaryRow(aliases) {
  const row = document.createElement('div');
  row.className = 'link-row is-primary';

  const path = document.createElement('span');
  path.className = 'link-path';
  path.textContent = `/blog/${state.slug}/`;

  const badge = document.createElement('span');
  badge.className = 'link-badge';
  badge.textContent = 'primary';

  const edit = document.createElement('button');
  edit.type = 'button';
  edit.className = 'link-action';
  edit.textContent = 'Edit';
  edit.title = "Change this post's primary URL";
  edit.addEventListener('click', () => {
    state.editingPrimary = true;
    renderLinks(aliases);
  });

  row.append(path, badge, edit);
  return row;
}

// The primary row swapped for an editor: /blog/ [input] /, Save, Cancel.
// Save posts the same rename route Make primary already uses under the
// hood; Cancel (or Escape) drops back to primaryRow() untouched.
function primaryEditRow(aliases) {
  const row = document.createElement('form');
  row.className = 'link-row is-primary link-row-edit';

  const prefix = document.createElement('span');
  prefix.className = 'link-prefix';
  prefix.textContent = '/blog/';

  const input = document.createElement('input');
  input.type = 'text';
  input.value = state.slug;
  input.autocapitalize = 'none';
  input.autocomplete = 'off';
  input.spellcheck = false;
  input.setAttribute('aria-label', 'Edit primary link slug');

  const suffix = document.createElement('span');
  suffix.className = 'link-prefix';
  suffix.textContent = '/';

  const save = document.createElement('button');
  save.type = 'submit';
  save.className = 'link-action';
  save.textContent = 'Save';

  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'link-action';
  cancel.textContent = 'Cancel';
  cancel.addEventListener('click', () => {
    state.editingPrimary = false;
    renderLinks(aliases);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      state.editingPrimary = false;
      renderLinks(aliases);
    }
  });

  row.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!input.value.trim()) return;
    state.editingPrimary = false;
    linkWrite(`/api/posts/${state.slug}/rename`, 'POST', { new_slug: input.value }, 'editing primary link');
  });

  row.append(prefix, input, suffix, save, cancel);
  return row;
}

// A non-primary link row: its URL plus Make primary / Remove.
function linkRow(slug) {
  const row = document.createElement('div');
  row.className = 'link-row';

  const path = document.createElement('span');
  path.className = 'link-path';
  path.textContent = `/blog/${slug}/`;
  row.append(path);

  const makePrimary = document.createElement('button');
  makePrimary.type = 'button';
  makePrimary.className = 'link-action';
  makePrimary.textContent = 'Make primary';
  makePrimary.title = `Move the post to /blog/${slug}/; /blog/${state.slug}/ will redirect to it`;
  makePrimary.addEventListener('click', () => linkWrite(
    `/api/posts/${state.slug}/links/${encodeURIComponent(slug)}/primary`, 'POST', {},
    'making primary',
  ));

  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'link-action danger';
  remove.textContent = 'Remove';
  remove.title = `Stop redirecting /blog/${slug}/ — it will 404 once published`;
  remove.addEventListener('click', () => linkWrite(
    `/api/posts/${state.slug}/links/${encodeURIComponent(slug)}`, 'DELETE', {},
    'removing link',
  ));

  row.append(makePrimary, remove);
  return row;
}

async function linkWrite(url, method, fields, doing) {
  // Make primary renames the post, which a review can't follow. Every link
  // write leaves it, since which ones rename isn't known until they land.
  await leaveReview();
  await leavePlacing();
  if (!(await flushPendingEdit())) return;
  setStatus(`${doing}…`);
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...fields, hash: state.hash }),
    });
  } catch (err) {
    setStatus(`${doing} failed — network error: ${err.message}`);
    return;
  }
  if (!res.ok) {
    // A 409 here is as likely to be "that link is taken" as a stale hash,
    // and the detail says which -- so show it rather than a generic reload.
    setStatus(`${doing} failed — ${await errorDetail(res)}`);
    return;
  }
  const data = await res.json();
  const renamed = data.slug !== state.slug;
  applyPost(data);
  if (renamed) {
    await loadPostList();
    els.picker.value = data.slug;
  }
  setStatus('saved');
  await refreshStatus();
}

async function deleteDraft() {
  const title = els.title.textContent.trim() || state.slug;
  if (!confirm(`Delete the draft "${title}"?\n\nThis can't be undone.`)) return;
  await leaveReview();
  await leavePlacing();
  if (!(await flushPendingEdit())) return;

  setStatus('deleting…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hash: state.hash }),
    });
  } catch (err) {
    setStatus(`delete failed — network error: ${err.message}`);
    return;
  }
  if (!res.ok) {
    setStatus(`delete failed — ${await errorDetail(res)}`);
    return;
  }

  const posts = await loadPostList();
  state.slug = null;
  state.linksOpen = false;
  rememberSlugInUrl(null);
  if (posts.length) {
    els.picker.value = posts[0].slug;
    await loadPost(posts[0].slug);
  } else {
    els.title.textContent = '';
    els.meta.innerHTML = '';
    els.links.hidden = true;
    state.blocks = [];
    cancelPlacing({ render: false });
    renderBlocks();
  }
  setStatus('draft deleted');
  await refreshStatus();
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

function renderBlocks() {
  // An open text editor survives a rebuild (a menu opening or cancelling,
  // its own save landing) -- see captureOpenText().
  const resume = captureOpenText();
  // The overlay's observer points at nodes that are about to be thrown away.
  stopWatchingLayout();
  els.blocks.innerHTML = '';
  // Move mode doesn't rebuild the list -- it renders exactly what you were
  // looking at and overlays the drop zones, so the page doesn't shift under
  // you the moment you pick a block up.
  els.blocks.classList.toggle('moving', state.moveIndex !== null || Boolean(state.placing));
  els.blocks.classList.toggle('placing', Boolean(state.placing));

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
      // During a proofread review a block with suggestions shows the
      // server's marked-up copy; its source is untouched until Accept.
      const marked = state.review && state.review.blocks.get(block.index);
      content.innerHTML = marked ? marked.review_html : block.html;
    }
    el.appendChild(content);

    el.addEventListener('click', async () => {
      if (el.classList.contains('editing')) return;
      // The review's marks and hashes are for the text as it was
      // proofread; an edit under them would make every later Accept miss.
      if (reviewing()) {
        setStatus('Close proofreading to edit.');
        return;
      }
      // One editor at a time: tapping another block saves the open one
      // first (or, for a photo/clip strip with changes, asks), then opens
      // this one. A save that fails leaves the open one as it is.
      if (openEditor && openEditor.el !== el) {
        const from = openEditor.index;
        const count = state.blocks.length;
        if (!(await closeEditor())) return;
        // A blank line typed into the saved block splits it into several,
        // which shifts every block after it.
        const target = block.index > from ? block.index + state.blocks.length - count : block.index;
        const fresh = els.blocks.querySelector(`.block[data-index="${target}"]`);
        if (fresh) fresh.click();
        return;
      }
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
    // No controls while reviewing: every one of them changes the block
    // list, which would shift the indices the review's suggestions name.
    if (!reviewing()) el.appendChild(blockControls(block));

    if (state.pendingInsert && state.pendingInsert.index === block.index) {
      el.appendChild(insertChoice(block));
    }

    // The wrap picker lives inside the block, so a floated row carries it
    // along; it's behind the ◨ toggle rather than always on, since a strip
    // under every picture is noise when reading a post back.
    if (state.wrapOpen.has(block.index) && !reviewing()) {
      if (isMediaRow(block)) el.appendChild(wrapControl(block));
      else if (block.kind === 'pair' && block.text !== undefined) {
        el.appendChild(unpairControl(block));
      } else if (block.kind === 'spacer') el.appendChild(spacerControl(block));
    }

    els.blocks.appendChild(el);

    if (canMergeWithNext(block.index) && !reviewing()) {
      els.blocks.appendChild(mergeControl(block.index));
    }
  });

  if (resume) restoreOpenText(resume);
  // Off while a review is up (one at a time) or with nothing to read.
  els.proofread.disabled = reviewing() || Boolean(state.placing)
    || !state.blocks.some((b) => PROSE_KINDS.has(b.kind));
  syncAddPhoto();

  // Overlaid last, once every block is laid out: the zones are placed
  // from the blocks' measured positions.
  if (state.moveIndex !== null) renderMoveOverlay();
  else if (state.placing) renderPlaceOverlay();
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
  const source = state.blocks[index].source;
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
    const at = await flushThenFind(index, source);
    if (at < 0) return;
    mergeBlock(at);
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

// If an editor is open with unsaved changes, save it -- and report whether
// that actually landed. A text editor stays open (the save re-renders the
// list and renderBlocks() puts it back); a pair editor closes, as on its own
// Done. A photo/clip strip has no route to save from here and no typing to
// lose, so it asks before its changes are dropped.
//
// Every control-bar action calls this first, as do Publish, Undo, switching
// posts and the tab going away. Blur saves nothing, so without it an
// action's own renderBlocks() would rebuild the page from `state`, which
// never saw the edit.
//
// It reads `openEditor`, never "a textarea inside .block.editing": that
// selector also matched a paired section's prose field, and saved the prose
// over the WHOLE pair block -- deleting its picture.
//
// It loops because a save can be in flight already (started by another
// flush): awaiting that one isn't enough when typing carried on after it
// started, so it checks again and saves again until nothing is left.
let saveInFlight = null;

async function flushPendingEdit(options = {}) {
  for (let round = 0; round < 8; round++) {
    if (saveInFlight) {
      if (!(await saveInFlight)) return false;
      continue;
    }
    const ed = openEditor;
    if (!ed || !ed.el.isConnected) return true;
    if (!ed.dirty()) return true;
    if (!ed.save) {
      if (options.keepalive) return true;
      return confirm(`Discard your unsaved changes to this ${ed.kind === 'videos' ? 'clip' : 'photo'} row?`);
    }
    saveInFlight = ed.save(options);
    let ok;
    try {
      ok = await saveInFlight;
    } finally {
      saveInFlight = null;
    }
    if (!ok) return false;
  }
  return false;
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

  // preventDefault() on mousedown keeps the open textarea focused (and the
  // tablet's keyboard up) through a tap on a control. It began as the fix
  // for a blur handler that re-rendered synchronously and replaced the
  // button mid-click; blur no longer does anything, but losing focus on
  // every control tap would still drop the keyboard.
  //
  // Nothing saves on blur, so every handler here calls flushPendingEdit()
  // itself before acting -- otherwise the action's own renderBlocks()
  // would rebuild the page from `state`, which never saw the typing.
  bar.addEventListener('mousedown', (e) => e.preventDefault());

  const add = document.createElement('button');
  add.textContent = '+';
  add.title = 'Insert a paragraph';
  add.addEventListener('click', async (e) => {
    e.stopPropagation();
    const at = await flushThenFind(block.index, block.source);
    if (at < 0) return;
    askWhereToInsert(at, 'New paragraph.', 'a paragraph');
  });

  const del = document.createElement('button');
  del.textContent = '×';
  del.title = 'Delete this block';
  del.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!confirm('Delete this block?')) return;
    // Deleting the open block closes it first (saved, so Undo has it).
    // Deleting another one saves the open one, then finds this block again
    // -- that save can split, merge or remove the open block, shifting
    // every index after it.
    if (openEditor && openEditor.el.contains(del)) {
      const count = state.blocks.length;
      if (!(await closeEditor())) return;
      // Its own save may have split, merged or removed it: then "this
      // block" is no longer one thing to delete.
      if (state.blocks.length !== count) {
        renderBlocks();
        setStatus('the post changed under that tap — nothing deleted, try again');
        return;
      }
      removeBlock(block.index);
      return;
    }
    const at = await flushThenFind(block.index, block.source);
    if (at < 0) return;
    removeBlock(at);
  });

  const photo = document.createElement('button');
  photo.textContent = '🖼';
  photo.title = 'Add photos here';
  photo.addEventListener('click', async (e) => {
    e.stopPropagation();
    const at = await flushThenFind(block.index, block.source);
    if (at < 0) return;
    pickImages(at);
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
      const at = await flushThenFind(block.index, block.source);
      if (at < 0) return;
      if (state.wrapOpen.has(at)) state.wrapOpen.delete(at);
      else state.wrapOpen.add(at);
      renderBlocks();
    });
  }

  const spacer = document.createElement('button');
  spacer.textContent = '␣';
  spacer.title = 'Insert a spacer — blank space between sections';
  spacer.addEventListener('click', async (e) => {
    e.stopPropagation();
    const at = await flushThenFind(block.index, block.source);
    if (at < 0) return;
    askWhereToInsert(at, SPACER_SOURCE, 'a spacer');
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
      const at = await flushThenFind(block.index, block.source);
      if (at < 0) return;
      askWhereToInsert(at, CLEAR_SOURCE, 'the stop');
    });
  }

  const move = document.createElement('button');
  move.textContent = '⇅';
  move.title = 'Move this block';
  move.addEventListener('click', async (e) => {
    e.stopPropagation();
    const at = await flushThenFind(block.index, block.source);
    if (at < 0) return;
    enterMoveMode(at);
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
  const label = document.createElement('span');
  label.textContent = 'Moving a block — tap where it should land';
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'move-cancel';
  cancel.textContent = 'Cancel';
  cancel.title = 'Leave move mode without moving anything';
  cancel.addEventListener('click', cancelMove);
  renderDropOverlay([label, cancel], 'Place the block here',
    (gap) => submitMove(state.moveIndex, gap));
}

// The banner plus one drop line per gap (N+1 for N blocks), shared by move
// mode and Add photo's placement. `onPick(gap)` gets the gap in the block
// list as currently rendered -- the index both the move and place routes
// take.
function renderDropOverlay(bannerContent, targetTitle, onPick) {
  stopWatchingLayout();

  const banner = document.createElement('div');
  banner.className = 'move-banner';
  banner.append(...bannerContent);
  // Sits directly under the sticky toolbar. Measured rather than hard-coded:
  // the bar's height depends on its own contents and the font, and a guess
  // that drifts would either cover the toolbar or float below it.
  banner.style.top = `${barHeight()}px`;
  els.blocks.appendChild(banner);

  const layer = document.createElement('div');
  layer.className = 'move-layer';
  const blocks = [...els.blocks.querySelectorAll('.block')];
  for (let gap = 0; gap <= blocks.length; gap++) {
    const target = document.createElement('button');
    target.type = 'button';
    target.className = 'move-target';
    target.title = targetTitle;
    target.dataset.gap = gap;
    target.addEventListener('click', () => onPick(gap));
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
  return banner;
}

function barHeight() {
  const bar = document.querySelector('.bar');
  return bar ? Math.round(bar.getBoundingClientRect().height) : 0;
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
    await applyWrite(res, { at: index, delta: 1 });
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
  [['↑ Above', 0], ['↓ Below', 1]].forEach(([text, offset]) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = text;
    btn.addEventListener('mousedown', (e) => e.preventDefault());
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      // Typing since the menu opened is saved first, which can move this
      // block; find it again rather than insert at a stale index.
      const found = await flushThenFind(index, block.source);
      if (found < 0) return;
      state.pendingInsert = null;
      insertBlock(found + offset, source);
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
  await applyWrite(res, { at: index, delta: 1 });
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
  await applyWrite(res, { at: index, delta: -1 });
}

// `change` says how this write moves the open text block, so the rebuild
// can find it: {at, delta} for an insert/delete at `at`, {own: ...} for the
// editor's own save. It rides on the write and is only read once the write
// landed -- a failed write (network error, 409) leaves nothing behind for a
// later, unrelated render to misread. Whatever it says is still verified
// against the block's text before the editor re-attaches (restoreOpenText).
async function applyWrite(res, change = null) {
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
  // See applyPost: a new block list voids the placement's gaps. Its own
  // write clears state.placing before it gets here.
  cancelPlacing({ render: false, dropped: true });
  const before = state.blocks.length;
  state.blocks = data.blocks;
  setCanUndo(data.can_undo);
  const ed = openEditor;
  if (ed && ed.kind === 'text') {
    if (!change) ed.expect = null;
    else if (change.own) ed.expect = { ...change.own, count: before };
    else {
      const moves = change.delta > 0 ? change.at <= ed.index : change.at < ed.index;
      ed.expect = { index: ed.index + (moves ? change.delta : 0) };
    }
  }
  // Undo and Discard can change the frontmatter too (a title, a link), so
  // the meta row and Links panel re-render from the payload as well.
  if (data.meta) {
    if (!els.title.dataset.editing) els.title.textContent = data.meta.title;
    renderMeta(data.meta);
  }
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
  await leaveReview();
  await leavePlacing();
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
  await leaveReview();
  await leavePlacing();
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
  if (!(await flushPendingEdit())) return;
  const message = prompt('Commit message:', `Update ${state.slug}`);
  if (message === null) return; // cancelled: the review stays up
  await leaveReview();

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

// The one open editor, or null. Every kind -- text, pair, photo strip, clip
// strip -- registers here, so "save or ask before going on" is one call
// (flushPendingEdit) and only one is ever open:
//   {kind, el, index, dirty(), save(options) | null, draftKey, expect}
// `save` resolves true once the write landed. Photo/clip strips have none:
// their changes are a list, not typing, and flushPendingEdit asks first.
// `expect` is set by whoever is about to change the block list, naming the
// index the open text block will have afterwards (see restoreOpenText).
let openEditor = null;

// Room the side rail needs: its 72px column (editor.css) plus the 8px gap
// to the block.
const RAIL_ROOM = 80;

function isTextEditable(block) {
  return block && !block.images && !block.videos
    && !(block.kind === 'pair' && block.text !== undefined);
}

// Save whatever is open, then find again the block a control was built
// for: that save can split, merge or remove the open block, which shifts
// every index after it. Returns the block's index now, or -1 -- after
// re-rendering and saying so -- when it can't be verified, so a tap never
// acts on a block other than the one it was aimed at.
async function flushThenFind(index, source) {
  const count = state.blocks.length;
  const ed = openEditor;
  const from = ed ? ed.index : -1;
  const wasOpen = ed && ed.kind === 'text' && ed.index === index;
  if (!(await flushPendingEdit())) return -1;
  // The open block itself: its own save just changed its text, so it is
  // verified by the editor having re-attached to it.
  if (wasOpen && state.blocks.length === count && openEditor
      && openEditor.kind === 'text' && openEditor.index === index) {
    return index;
  }
  const at = index > from ? index + state.blocks.length - count : index;
  const block = state.blocks[at];
  if (block && block.source === source) return at;
  renderBlocks();
  setStatus('the post changed under that tap — nothing done, try again');
  return -1;
}

// --- unsaved text survives a reload ------------------------------------
// Typing is mirrored into localStorage, keyed by post + block index + the
// block's source as it was opened, until it is saved. A 409 ("changed on
// disk -- reload") would otherwise lose it on the reload, and iOS can kill
// a backgrounded tab before a keepalive save lands. Offered back on load.
const DRAFT_PREFIX = 'editor-draft:';
// Per page load, so opening a block never overwrites (or, while clean,
// clears) a draft an earlier load left behind and hasn't offered back yet.
const DRAFT_SESSION = Math.random().toString(36).slice(2, 8);

function draftKey(slug, index, original) {
  let h = 5381;
  for (let i = 0; i < original.length; i++) h = ((h * 33) ^ original.charCodeAt(i)) >>> 0;
  return `${DRAFT_PREFIX}${slug}:${index}:${h.toString(36)}:${DRAFT_SESSION}`;
}

function rememberDraft(ed, text, original) {
  try {
    if (ed.dirty()) {
      localStorage.setItem(ed.draftKey, JSON.stringify({
        kind: ed.kind, index: ed.index, original, text, at: Date.now(),
      }));
    } else {
      localStorage.removeItem(ed.draftKey);
    }
  } catch {
    // Private mode or a full quota: the editor still works, just without
    // the net under it.
  }
}

function forgetDraft(key) {
  try { if (key) localStorage.removeItem(key); } catch { /* see above */ }
}

function savedDrafts(slug) {
  const out = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key.startsWith(`${DRAFT_PREFIX}${slug}:`)) continue;
      try {
        out.push({ key, ...JSON.parse(localStorage.getItem(key)) });
      } catch {
        localStorage.removeItem(key);
      }
    }
  } catch { /* see above */ }
  return out;
}

// A small strip above the post for each draft left behind: Restore reopens
// its block with the text, Discard drops it. If the block has changed since
// (so it can't be found), the text is shown to copy rather than lost.
function offerDrafts() {
  document.querySelectorAll('.draft-offer').forEach((n) => n.remove());
  savedDrafts(state.slug).forEach((draft) => {
    const box = document.createElement('div');
    box.className = 'draft-offer';
    const when = new Date(draft.at).toLocaleString();
    const target = findDraftBlock(draft);
    const msg = document.createElement('span');
    msg.textContent = target
      ? `Unsaved text from ${when}, for block ${draft.index + 1}.`
      : `Unsaved text from ${when}. Its block has changed since, so copy what you need:`;
    box.appendChild(msg);
    if (!target) {
      const text = document.createElement('textarea');
      text.readOnly = true;
      text.value = draft.text;
      box.appendChild(text);
    }
    const buttons = document.createElement('div');
    buttons.className = 'draft-offer-buttons';
    if (target) {
      const restore = document.createElement('button');
      restore.type = 'button';
      restore.textContent = `Restore into block ${draft.index + 1}`;
      restore.addEventListener('click', async () => {
        if (reviewing()) {
          setStatus('Close proofreading to edit.');
          return;
        }
        await leavePlacing();
        if (!(await closeEditor())) return;
        const block = findDraftBlock(draft);
        const el = block && els.blocks.querySelector(`.block[data-index="${block.index}"]`);
        if (!el) return;
        const content = el.querySelector(':scope > .block-content');
        if (draft.kind === 'pair') startEditingPair(el, content, block, draft.text);
        else startEditing(el, content, block, {
          value: draft.text, start: draft.text.length, end: draft.text.length, focused: true,
        });
        // The editor now owns it under the same key; this only drops a key
        // left over from a different index.
        if (openEditor && openEditor.draftKey !== draft.key) forgetDraft(draft.key);
        box.remove();
      });
      buttons.appendChild(restore);
    }
    const discard = document.createElement('button');
    discard.type = 'button';
    discard.textContent = 'Discard';
    discard.addEventListener('click', () => {
      forgetDraft(draft.key);
      box.remove();
    });
    buttons.appendChild(discard);
    box.appendChild(buttons);
    els.blocks.before(box);
  });
}

function findDraftBlock(draft) {
  const same = (b) => b && b.source.trimEnd() === draft.original.trimEnd()
    && (draft.kind === 'pair' ? b.kind === 'pair' && b.text !== undefined : isTextEditable(b));
  // Only where it was typed. Another block with the same text (a second
  // "New paragraph.") is not this one; then the text is shown to copy.
  return same(state.blocks[draft.index]) ? state.blocks[draft.index] : null;
}

// An open text block stays open until its Done button (or opening another
// block, which saves it first). Blur used to close it, and on a tablet
// almost any tap blurs: the block's own padding, a menu's Cancel, the line
// under a short field. See "Text editors close on Done" in CLAUDE.md.
//
// `resume` is set when the editor is being put back after renderBlocks()
// rebuilt the list (a menu opened or cancelled, a save landed), or from a
// saved draft: it carries the in-progress text, caret and focus.
function startEditing(el, content, block, resume = null) {
  if (el.classList.contains('editing')) return;
  el.classList.add('editing', 'text-editing');
  content.innerHTML = '';

  const textarea = document.createElement('textarea');
  textarea.className = 'block-source';
  textarea.value = resume ? resume.value : block.source;
  textarea.rows = 2;
  content.appendChild(textarea);

  const ed = {
    kind: 'text', el, index: block.index, textarea,
    original: block.source,
    blocks: state.blocks,
    draftKey: draftKey(state.slug, block.index, block.source),
    expect: resume && resume.expect ? resume.expect : null,
    savingSource: resume ? resume.savingSource || null : null,
    // parse_blocks stores each block rstripped, so "Hello " saved comes
    // back as "Hello": compare without trailing whitespace on both sides.
    dirty: () => textarea.value.trimEnd() !== block.source.trimEnd(),
    save: (options) => {
      const source = textarea.value;
      ed.savingSource = source;
      // The PUT targets this index, so that is where the block is after
      // it -- if it is still there (see restoreOpenText).
      return saveBlock(ed.index, source, options, { own: { index: ed.index, own: true, source } });
    },
  };
  openEditor = ed;

  // The block's controls, a Done button and any menu those controls open
  // move into one rail: a column beside the block when the window has room
  // for one, a row under the field (sticky to the bottom of the window)
  // when it doesn't. Either way nothing sits on top of the text.
  const rail = document.createElement('div');
  rail.className = 'edit-rail';
  const inner = document.createElement('div');
  inner.className = 'edit-rail-inner';
  const done = document.createElement('button');
  done.type = 'button';
  done.className = 'edit-done';
  done.textContent = 'Done';
  done.title = 'Save and stop editing';
  done.addEventListener('click', (e) => {
    e.stopPropagation();
    closeEditor();
  });
  inner.appendChild(done);
  const bar = el.querySelector(':scope > .block-controls');
  if (bar) inner.appendChild(bar);
  const menu = el.querySelector(':scope > .insert-choice');
  if (menu) inner.appendChild(menu);
  rail.appendChild(inner);
  el.appendChild(rail);

  // Beside the block only when the window has the room AND the block spans
  // the whole column: a block narrowed by a floated picture would put the
  // rail on top of the picture.
  const placeRail = () => {
    const r = el.getBoundingClientRect();
    const column = els.blocks.getBoundingClientRect();
    const full = r.right >= column.right;
    const room = document.documentElement.clientWidth - r.right;
    const side = full && room >= RAIL_ROOM;
    el.classList.toggle('rail-side', side);
    // Stick below the toolbar, whose height depends on its own contents.
    const toolbar = document.querySelector('.bar');
    inner.style.top = side ? `${(toolbar ? toolbar.offsetHeight : 0) + 8}px` : '';
  };

  // Sized to its content, not to its count of source lines. A paragraph is
  // usually ONE source line that wraps to a dozen on screen, so `rows` from
  // the line count gave a two-row box that scrolled: the block collapsed,
  // the next blocks slid up into the space the text had filled, and the
  // next tap "on the text" landed outside the field (reproduced over CDP:
  // scripts/verify-edit-tap.py). Re-fit on input and on resize: a narrower
  // window (rotation, the keyboard on browsers that resize the layout)
  // rewraps the text. The `auto` step briefly shrinks the page, which near
  // the end of a long post clamps the scroll position -- so put it back.
  const fit = () => {
    if (!textarea.isConnected) {
      window.removeEventListener('resize', fit);
      return;
    }
    placeRail();
    const y = window.scrollY;
    textarea.style.height = 'auto';
    textarea.style.height = `${textarea.scrollHeight}px`;
    if (window.scrollY !== y) window.scrollTo(window.scrollX, y);
  };
  fit();
  textarea.addEventListener('input', () => {
    fit();
    rememberDraft(ed, textarea.value, block.source);
  });
  window.addEventListener('resize', fit);
  rememberDraft(ed, textarea.value, block.source);

  if (!resume || resume.focused) {
    textarea.focus({ preventScroll: Boolean(resume) });
    if (resume) textarea.setSelectionRange(resume.start, resume.end);
  }

  // A tap on the open block that misses the field -- its padding, the rail
  // around the buttons -- keeps the focus, and so the keyboard, where it
  // is. Same mousedown-preventDefault trick the control bar uses (which
  // handles its own, so it's left alone).
  el.addEventListener('mousedown', (e) => {
    if (!el.classList.contains('editing') || !textarea.isConnected) return;
    if (e.target === textarea || e.target.closest('.block-controls')) return;
    e.preventDefault();
    textarea.focus({ preventScroll: true });
  });
}

// Save the open editor if it changed, then close it. Resolves false,
// leaving it open with its text, when the save didn't land (a 409, a
// network error) or a photo strip's changes were kept -- the caller must
// not go on as if it had closed.
async function closeEditor() {
  if (!openEditor) return true;
  if (!(await flushPendingEdit())) return false;
  // A text save put the editor back around the saved text; a pair save
  // already closed it. Either way, whatever is still open is now clean.
  const ed = openEditor;
  if (ed) {
    forgetDraft(ed.draftKey);
    openEditor = null;
    renderBlocks();
  }
  return true;
}

// What renderBlocks() needs to put the open text editor back after it
// rebuilds the list, or null. Any other kind of editor is simply closed by
// the rebuild -- every path that rebuilds with one open flushed it first.
function captureOpenText() {
  const ed = openEditor;
  openEditor = null;
  if (!ed || ed.kind !== 'text' || !ed.textarea.isConnected || state.moveIndex !== null) {
    return null;
  }
  const ta = ed.textarea;
  return {
    index: ed.index, original: ed.original, blocks: ed.blocks,
    expect: ed.expect, savingSource: ed.savingSource,
    draftKey: ed.draftKey,
    value: ta.value,
    start: ta.selectionStart,
    end: ta.selectionEnd,
    focused: document.activeElement === ta,
  };
}

// Never re-attach to a block that hasn't been verified as this one. When it
// can't be, the editor closes and its localStorage draft (if the typing
// isn't on the server) stays, to be offered back by the Restore strip.
// Losing the open editor is fine; writing over the wrong block is not.
function restoreOpenText(resume) {
  const trim = (v) => (v === null || v === undefined ? null : v.trimEnd());
  let block = null;
  let value = resume.value;
  let saved = null; // text the server now holds for this editor, if known
  const expect = resume.expect;
  resume.expect = null;
  if (state.blocks === resume.blocks) {
    // Nothing was written: the list is the one it was opened on.
    const b = state.blocks[resume.index];
    if (b && b.source === resume.original) block = b;
  } else if (expect && expect.own) {
    // Its own save landed. The PUT went to expect.index, but a save can
    // also remove the block (saved empty) or merge it into a neighbour
    // ("- x" typed after a list): then nothing at that index is this block.
    const b = state.blocks[expect.index];
    const sent = trim(expect.source);
    saved = expect.source;
    if (b && state.blocks.length === expect.count && trim(b.source) === sent) {
      block = b;
    } else if (b && state.blocks.length > expect.count && sent.startsWith(trim(b.source))
               && trim(b.source) !== '') {
      // Split ("# Heading" + a paragraph): the rest is blocks of its own
      // below, so keep editing the first piece -- plus anything typed after
      // the save started, which no block has yet. Typing anywhere else in
      // it can't be placed, so that closes (draft kept).
      if (value.startsWith(expect.source)) {
        block = b;
        value = b.source + value.slice(expect.source.length);
      }
    }
  } else if (expect) {
    // An insert or delete elsewhere said where it went; check the text.
    const b = state.blocks[expect.index];
    if (b && [resume.original, resume.savingSource, resume.value]
      .some((t) => t !== null && trim(t) === trim(b.source))) block = b;
  } else {
    // A write that didn't say (merge, Undo, pair...): only the same index,
    // and only if it still holds this text. Undo putting older text back
    // closes it -- the text was flushed before Undo ran.
    const b = state.blocks[resume.index];
    if (b && [resume.original, resume.savingSource, resume.value]
      .some((t) => t !== null && trim(t) === trim(b.source))) block = b;
  }
  if (!isTextEditable(block)) {
    // Closed under it. Keep the draft unless what was typed is known to be
    // on the server.
    const onServer = trim(resume.value) === trim(resume.original)
      || (saved !== null && resume.value === saved);
    if (onServer) forgetDraft(resume.draftKey);
    if (!onServer) setStatus('closed the editor — your text is kept, see the note above the post');
    if (!onServer) offerDrafts();
    return;
  }
  const el = els.blocks.querySelector(`.block[data-index="${block.index}"]`);
  if (!el) return;
  startEditing(el, el.querySelector(':scope > .block-content'), block, { ...resume, value });
  // A save moves the draft to a new key (new source) or clears it.
  if (openEditor && openEditor.draftKey !== resume.draftKey) forgetDraft(resume.draftKey);
}

async function saveBlock(index, source, { keepalive = false } = {}, change = null) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, hash: state.hash }),
      // So a save started as the tab goes away still reaches the server.
      keepalive,
    });
  } catch (err) {
    setStatus(`save failed — network error: ${err.message}`);
    return false;
  }
  return await applyWrite(res, change);
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

  const before = JSON.stringify([images, framing.size, framing.side]);
  openEditor = {
    kind: 'images', el, index: block.index, save: null,
    dirty: () => JSON.stringify([images, framing.size, framing.side]) !== before,
  };

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
function startEditingPair(el, content, block, draftText = null) {
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
  area.value = draftText === null ? block.text : draftText;
  area.rows = Math.max(6, area.value.split('\n').length + 1);
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
    closeEditor();
  });

  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'image-cancel';
  cancel.textContent = 'Cancel';
  cancel.addEventListener('click', (e) => {
    e.stopPropagation();
    // Cancel is the one way to throw the prose away on purpose.
    forgetDraft(ed.draftKey);
    openEditor = null;
    renderBlocks();
  });

  actions.append(done, cancel);
  content.appendChild(actions);

  // Registered like the text editor, so every flush path saves the prose
  // through the PAIR route -- never the plain block PUT, which would write
  // the prose over the whole pair and drop its picture.
  const ed = {
    kind: 'pair', el, index: block.index,
    draftKey: draftKey(state.slug, block.index, block.source),
    dirty: () => area.value.trimEnd() !== block.text.trimEnd()
      || framing.size !== block.size || framing.side !== block.side
      || chosen !== (block.justify || 'center'),
    save: async (options) => {
      // An empty section is refused by the server; keep the editor open
      // rather than let an action go on without the save.
      if (!area.value.trim()) {
        if (!options.keepalive) {
          alert('A paired section needs some text. Unpair it if you want just the picture.');
        }
        return false;
      }
      const text = area.value;
      const ok = await saveBlockPair(block.index, text, framing.size, framing.side, chosen, media, options);
      // Saved, so the editor closed with the re-render; clear the draft
      // unless typing carried on while the save was in flight.
      if (ok && area.value === text) forgetDraft(ed.draftKey);
      return ok;
    },
  };
  openEditor = ed;
  area.addEventListener('input', () => rememberDraft(ed, area.value, block.source));
  if (draftText !== null) rememberDraft(ed, area.value, block.source);
  area.focus();
}

async function saveBlockPair(index, text, size, side, justify, media, { keepalive = false } = {}) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}/pair`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, size, side, justify, ...media, hash: state.hash }),
      keepalive,
    });
  } catch (err) {
    setStatus(`save failed — network error: ${err.message}`);
    return false;
  }
  return await applyWrite(res);
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

  const before = JSON.stringify([clips, framing.size, framing.side]);
  openEditor = {
    kind: 'videos', el, index: block.index, save: null,
    dirty: () => JSON.stringify([clips, framing.size, framing.side]) !== before,
  };

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

// --- Add photo -----------------------------------------------------------
// The round 📷 button: pick photos, then tap one of move mode's blue lines
// to say where they go. The upload starts the moment the picker closes and
// runs while you aim, so a tap usually places at once; a tap that beats the
// upload marks its line and places when the upload lands. The insert is its
// own route (`/images/place`), so nothing is written until a line is tapped,
// and Cancel leaves the post as it was (uploaded objects stay in S3, as an
// abandoned photo-strip upload's do).
//
// `state.placing` is {slug, files, thumbs, images, error, gap, busy}: the
// object URLs for the banner's thumbnails, the uploaded {url, alt} list once
// it's back, the gap tapped before it was, and whether the place write is on
// the wire.

function syncAddPhoto() {
  // Not while anything else owns the screen: a review (its indices would
  // shift), a placement already running, or move mode.
  els.addPhoto.hidden = !state.slug || reviewing() || Boolean(state.placing)
    || state.moveIndex !== null;
}

// Just under the toolbar, which wraps to two lines on a portrait tablet --
// so measured, like the move banner, and kept up to date as it changes.
function positionAddPhoto() {
  els.addPhoto.style.top = `${barHeight() + 12}px`;
}
new ResizeObserver(positionAddPhoto).observe(document.querySelector('.bar'));

function canAddPhoto() {
  return Boolean(state.slug) && !reviewing() && !state.placing && state.moveIndex === null;
}

// The picker opens INSIDE the tap, synchronously: a browser only opens a
// file picker during the tap's user activation, and Safari's and Chrome's
// windows can run out across an awaited save or a confirm(). So nothing is
// saved before it opens -- the open editor is closed (and saved) once files
// have been chosen, and cancelling the picker leaves it exactly as it was.
function openAddPhotoPicker() {
  if (!canAddPhoto()) return;
  els.addPhotoInput.value = ''; // so picking the same photo again still fires `change`
  els.addPhotoInput.click();
}

async function addPhotoPicked() {
  const files = [...els.addPhotoInput.files];
  els.addPhotoInput.value = '';
  if (!files.length || !canAddPhoto()) return;
  // Same rule as every bar action: save what's open first, and stop if that
  // save didn't land (its own status says why).
  if (!(await closeEditor())) {
    noteStatus('Photo not added. Pick it again.');
    return;
  }
  if (!canAddPhoto()) return;
  // An open "insert above or below?" menu is dropped; beginPlacing's
  // render takes it off the screen.
  state.pendingInsert = null;
  beginPlacing(files);
}

function beginPlacing(files) {
  if (state.moveIndex !== null) cancelMove();
  const placing = {
    slug: state.slug, files, thumbs: files.map((f) => URL.createObjectURL(f)),
    images: null, gap: null, busy: false,
  };
  state.placing = placing;
  setStatus('');
  renderBlocks();
  uploadForPlacing(placing);
}

async function uploadForPlacing(placing) {
  const form = new FormData();
  for (const file of placing.files) form.append('files', file);
  // Alt text is added afterwards in the photo editor, which opens on the new
  // block -- one prompt per photo before you'd even chosen where they go was
  // the old flow's worst part.
  form.append('alts', JSON.stringify(placing.files.map(() => '')));
  let failure = null;
  let data = null;
  try {
    const res = await fetch(`/api/posts/${placing.slug}/images/upload`, { method: 'POST', body: form });
    if (res.ok) data = await res.json();
    else failure = await errorDetail(res);
  } catch (err) {
    failure = `network error: ${err.message}`;
  }
  if (state.placing !== placing) return; // cancelled while it was out
  if (failure) {
    // Nothing was written; say why, and give the screen back.
    cancelPlacing();
    setStatus(`upload failed — ${failure}`);
    return;
  }
  placing.images = data.images;
  if (placing.gap !== null) placeAt(placing.gap);
  else renderPlaceBanner();
}

function tapPlacement(gap) {
  const placing = state.placing;
  if (!placing || placing.busy) return;
  if (!placing.images) {
    // Beat the upload: remember the line (a second tap moves it) and place
    // as soon as the upload is back.
    placing.gap = gap;
    renderPlaceBanner();
    return;
  }
  placeAt(gap);
}

// The place write in flight, if any. leavePlacing() waits for it, so a bar
// action never acts on the hash it is about to replace.
let placeWrite = null;

function placeAt(gap) {
  const write = placeAtNow(gap);
  placeWrite = write;
  write.finally(() => { if (placeWrite === write) placeWrite = null; });
  return write;
}

async function placeAtNow(gap) {
  const placing = state.placing;
  placing.gap = gap;
  placing.busy = true;
  renderPlaceBanner();
  // A title edit saved on blur, just before this tap, changes the hash.
  if (metaWrite) await metaWrite;
  let res;
  try {
    res = await fetch(`/api/posts/${placing.slug}/images/place`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index: gap, hash: state.hash, images: placing.images }),
    });
  } catch (err) {
    if (state.placing === placing) cancelPlacing();
    setStatus(`save failed — network error: ${err.message}`);
    noteStatus('Photo not added. Pick it again.');
    return;
  }
  if (state.placing !== placing) {
    // Something else ended the placement while this was out. A write that
    // landed on this post still has to be applied (its hash is the post's
    // now); one that didn't must not vanish without a word.
    if (res.ok && placing.slug === state.slug) await applyWrite(res, { at: gap, delta: 1 });
    else if (!res.ok) noteStatus('Photo not added. Pick it again.');
    return;
  }
  // Leave placement either way: a 409 means the gaps were stale, and
  // applyWrite says "changed on disk — reload" for it, as for any write.
  cancelPlacing({ render: !res.ok });
  if (!(await applyWrite(res, { at: gap, delta: 1 }))) return;
  // Straight into the new block's photo editor, for the alt text.
  const el = els.blocks.querySelector(`.block[data-index="${gap}"]`);
  const block = state.blocks[gap];
  if (el && block && block.images) {
    startEditingImages(el, el.querySelector(':scope > .block-content'), block);
    el.scrollIntoView({ block: 'center' });
    setStatus(placing.images.length > 1 ? 'photos added — add alt text' : 'photo added — add alt text');
  }
}

// For the bar actions that change the post (Undo, Discard, Links, Delete
// draft, + New, switching posts, Restore): let a place already on the wire
// land, then drop a placement that hasn't been placed -- its gaps are about
// to stop meaning anything -- and say so.
async function leavePlacing() {
  if (placeWrite) await placeWrite;
  cancelPlacing({ dropped: true });
}

// `dropped`: something other than the person's own Cancel ended it, so the
// photos they picked were not added and the status has to say so.
function cancelPlacing({ render = true, dropped = false } = {}) {
  const placing = state.placing;
  if (!placing) return;
  state.placing = null;
  placing.thumbs.forEach((url) => URL.revokeObjectURL(url));
  if (dropped) noteStatus('Photo not added. Pick it again.');
  if (render) renderBlocks();
}

function renderPlaceOverlay() {
  const placing = state.placing;
  const thumbs = document.createElement('div');
  thumbs.className = 'place-thumbs';
  placing.thumbs.forEach((url) => {
    const img = document.createElement('img');
    img.src = url;
    img.alt = '';
    thumbs.appendChild(img);
  });
  const text = document.createElement('span');
  text.className = 'place-text';
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'move-cancel';
  cancel.textContent = 'Cancel';
  cancel.title = 'Stop without adding the photos';
  cancel.addEventListener('click', () => {
    cancelPlacing();
    setStatus('');
  });
  const banner = renderDropOverlay([thumbs, text, cancel],
    placing.files.length > 1 ? 'Put the photos here' : 'Put the photo here', tapPlacement);
  banner.classList.add('place-banner');
  renderPlaceBanner();
}

// The banner's words and the tapped line's mark, updated in place: a full
// renderBlocks() for every step of an upload would rebuild the post.
function renderPlaceBanner() {
  const placing = state.placing;
  const text = els.blocks.querySelector('.place-banner .place-text');
  if (!placing || !text) return;
  const many = placing.files.length > 1;
  let main = many ? `Tap where the ${placing.files.length} photos go` : 'Tap where the photo goes';
  let sub = placing.images ? 'Uploaded.' : 'Uploading…';
  if (placing.busy) {
    main = many ? 'Placing the photos…' : 'Placing the photo…';
    sub = '';
  } else if (placing.gap !== null) {
    main = 'Placing when the upload finishes';
    sub = 'Tap another line to change it.';
  }
  // Once the place write is on the wire, Cancel can't take it back -- and
  // dropping the placement then would leave this page on the old hash.
  const cancel = els.blocks.querySelector('.place-banner .move-cancel');
  if (cancel) cancel.disabled = placing.busy;
  text.innerHTML = '';
  const strong = document.createElement('strong');
  strong.textContent = main;
  text.appendChild(strong);
  if (sub) {
    const small = document.createElement('small');
    small.textContent = sub;
    text.appendChild(small);
  }
  els.blocks.querySelectorAll('.move-target').forEach((t) => {
    const on = placing.gap !== null && Number(t.dataset.gap) === placing.gap;
    t.classList.toggle('pending', on);
    t.querySelector('.place-pending')?.remove();
    if (on) {
      const label = document.createElement('span');
      label.className = 'place-pending';
      label.textContent = placing.busy ? 'Placing…' : 'Placing when the upload finishes';
      t.appendChild(label);
    }
  });
}

els.addPhoto.addEventListener('click', openAddPhotoPicker);
els.addPhotoInput.addEventListener('change', addPhotoPicked);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && state.placing && !state.placing.busy) {
    cancelPlacing();
    setStatus('');
  }
});

// --- Proofread ---------------------------------------------------------------
// The server (editor/proofread.py) owns the prompt, the guardrails and the
// red/green marks; this only batches, shows progress and steps through what
// comes back. Nothing is written until Accept, and each Accept goes through
// the apply route, which re-checks the fix against the block as it is now.
//
// No editor is open during a review, and none can be opened: starting one
// closes (saving) whatever is open, and the block click handler, the block
// controls and the draft Restore strip all refuse while reviewing(). That
// keeps the editor's re-attach and draft logic out of it entirely -- every
// write here lands with `openEditor` null. Undo, Discard, the post picker,
// + New and Publish close the review before they act.
const PROSE_KINDS = new Set(['paragraph', 'heading', 'list', 'blockquote', 'pair']);
const PROOF_BATCH = 5; // the route takes at most five indices
// Null, or the batch loop in flight: {cancelled, abort: AbortController}.
let proofRun = null;
// True while an Accept is being written, so a second tap waits.
let reviewBusy = false;
// The Accept write in flight, if any. leaveReview() waits for it so Undo,
// Discard, Publish and switching posts never act on a stale hash.
let reviewWrite = null;

function reviewing() {
  return Boolean(state.review || proofRun);
}

function showProofProgress(done, total) {
  els.proofread.hidden = true;
  els.proofProgress.hidden = false;
  els.proofProgress.querySelector('.proof-fill').style.width = `${total ? (100 * done) / total : 0}%`;
  els.proofProgress.querySelector('.proof-text').textContent = `Proofreading ${done} of ${total} paragraphs`;
}

function hideProofProgress() {
  els.proofProgress.hidden = true;
  els.proofread.hidden = false;
}

// "paragraph 3", "paragraphs 1–5", "paragraphs 1–5 and 11",
// "paragraphs 1, 4–5 and 9": runs of consecutive block numbers, 1-based.
function rangeText(indices) {
  const nums = [...new Set(indices)].sort((a, b) => a - b).map((i) => i + 1);
  const runs = [];
  for (const n of nums) {
    const last = runs[runs.length - 1];
    if (last && n === last[1] + 1) last[1] = n;
    else runs.push([n, n]);
  }
  const parts = runs.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`));
  const list = parts.length > 1
    ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
    : parts[0];
  return nums.length === 1 ? `paragraph ${list}` : `paragraphs ${list}`;
}

async function startProofread() {
  if (reviewing() || state.placing) return;
  // Same path as switching posts: save whatever is open, and stop if that
  // save didn't land (the editor stays open with its text).
  if (state.moveIndex !== null) cancelMove();
  state.pendingInsert = null;
  if (!(await closeEditor())) return;
  const targets = state.blocks.filter((b) => PROSE_KINDS.has(b.kind)).map((b) => b.index);
  if (!targets.length) {
    setStatus('Nothing to proofread.');
    return;
  }
  const run = { cancelled: false, abort: new AbortController() };
  // `seen` counts every suggestion that ever arrived, so a run whose
  // suggestions were all resolved before it finished says so, rather than
  // "no issues found".
  const review = { blocks: new Map(), items: [], current: 0, seen: 0 };
  const slug = state.slug;
  proofRun = run;
  state.review = review;
  const failed = [];
  setStatus('');
  showProofProgress(0, targets.length);
  renderBlocks(); // drops the block controls for the duration
  for (let i = 0; i < targets.length && !run.cancelled; i += PROOF_BATCH) {
    const batch = targets.slice(i, i + PROOF_BATCH);
    let data = null;
    try {
      const res = await fetch(`/api/posts/${slug}/proofread`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ indices: batch }),
        signal: run.abort.signal,
      });
      if (!res.ok) throw new Error(String(res.status));
      data = await res.json();
    } catch (err) {
      if (run.cancelled) break;
      failed.push(...batch);
    }
    // Closed (or replaced) while that batch was out: drop what came back.
    if (state.review !== review) break;
    const hadItems = review.items.length > 0;
    if (data) {
      for (const b of data.blocks) {
        if (!b.suggestions.length) continue;
        review.blocks.set(b.index, { block_hash: b.block_hash, review_html: b.review_html });
        for (const s of b.suggestions) review.items.push({ ...s, index: b.index });
        review.seen += b.suggestions.length;
      }
      for (const e of data.errors) failed.push(...e.indices);
    }
    // Stable sort: within a block, the server's order (by position).
    review.items.sort((a, b) => a.index - b.index);
    if (!run.cancelled) showProofProgress(Math.min(i + PROOF_BATCH, targets.length), targets.length);
    renderBlocks();
    renderReviewBar(!hadItems && review.items.length > 0);
  }
  // Let a full bar actually paint before it goes: hiding it in the same task
  // that filled it meant "7 of 7" was never on screen.
  if (!run.cancelled && state.review === review) await new Promise((r) => setTimeout(r, 400));
  if (proofRun === run) proofRun = null;
  if (state.review !== review) return; // closed: closeReview tidied up
  hideProofProgress();
  const stopped = run.cancelled ? 'Stopped. ' : '';
  const couldnt = failed.length ? `Couldn't check ${rangeText(failed)}.` : '';
  if (!review.items.length) {
    closeReview();
    let done;
    if (review.seen) done = 'All suggestions reviewed.';
    else if (stopped) done = 'No issues found so far.';
    else if (!couldnt) done = 'No spelling or grammar issues found.';
    setStatus(`${stopped}${couldnt}${couldnt && done ? ' ' : ''}${done || ''}`.trim());
    return;
  }
  setStatus(`${stopped}${couldnt}`.trim());
  renderReviewBar();
}

function currentItem() {
  return state.review && state.review.items[state.review.current];
}

function renderReviewBar(scroll = false) {
  const bar = els.reviewBar;
  if (!state.review || !state.review.items.length) {
    bar.hidden = true;
    bar.innerHTML = '';
    return;
  }
  const { items, current } = state.review;
  const item = items[current];
  bar.hidden = false;
  bar.innerHTML = '';
  const mk = (label, cls, fn, title) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = cls;
    b.textContent = label;
    if (title) b.title = title;
    b.disabled = reviewBusy;
    b.addEventListener('click', () => { if (!reviewBusy) fn(); });
    return b;
  };
  const count = document.createElement('span');
  count.className = 'review-count';
  count.textContent = `${current + 1} of ${items.length}`;
  const kind = document.createElement('span');
  kind.className = 'review-kind';
  kind.textContent = item.kind;
  // The change itself, as text, so a mark that's hard to spot (a comma, a
  // space) is still readable before Accept.
  const change = document.createElement('span');
  change.className = 'review-change';
  change.textContent = `${clip(item.before)} → ${clip(item.after)}`;
  change.title = `${item.before} → ${item.after}`;
  bar.append(
    mk('↑', 'review-nav', () => step(-1), 'Previous suggestion'),
    mk('↓', 'review-nav', () => step(1), 'Next suggestion'),
    count, kind, change,
    mk('Accept', 'review-accept', () => accept(item)),
    mk('Reject', 'review-reject', () => reject(item)),
    mk('Accept all', 'review-all', acceptAll),
    mk('Close', 'review-close', () => { closeReview(); setStatus(''); }),
  );
  focusCurrent(scroll);
}

function clip(text, max = 32) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function focusCurrent(scroll) {
  document.querySelectorAll('.pr-current').forEach((n) => n.classList.remove('pr-current'));
  const item = currentItem();
  if (!item) return;
  const marks = els.blocks.querySelectorAll(`[data-sid="${CSS.escape(item.id)}"]`);
  marks.forEach((n) => n.classList.add('pr-current'));
  if (scroll && marks[0]) marks[0].scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function step(delta) {
  const r = state.review;
  r.current = (r.current + delta + r.items.length) % r.items.length;
  renderReviewBar(true);
}

// Accepting keeps the new text; rejecting keeps the old.
function resolveMark(htmlText, sid, keepNew) {
  const t = document.createElement('template');
  t.innerHTML = htmlText;
  const sel = (tag) => t.content.querySelector(`${tag}[data-sid="${CSS.escape(sid)}"]`);
  const drop = sel(keepNew ? 'del' : 'ins');
  const keep = sel(keepNew ? 'ins' : 'del');
  if (drop) drop.remove();
  if (keep) keep.replaceWith(document.createTextNode(keep.textContent));
  return t.innerHTML;
}

// Takes one suggestion out of the review (state only; callers render).
function dropItem(item, keepNew) {
  const r = state.review;
  const at = r.items.indexOf(item);
  if (at !== -1) r.items.splice(at, 1);
  if (at !== -1 && at < r.current) r.current -= 1;
  const blk = r.blocks.get(item.index);
  if (blk) {
    blk.review_html = resolveMark(blk.review_html, item.id, keepNew);
    // Its last suggestion gone: render the block from the server's html.
    if (!r.items.some((i) => i.index === item.index)) r.blocks.delete(item.index);
  }
  if (r.current >= r.items.length) r.current = 0;
}

// After an Accept/Reject: step on, or end the review once nothing is left
// (and the batches have all come back).
function afterResolve() {
  if (!state.review) return;
  if (!state.review.items.length && !proofRun) {
    closeReview();
    setStatus('All suggestions reviewed.');
    return;
  }
  renderBlocks();
  renderReviewBar(true);
}

// Resolves true when the review can carry on (applied, or skipped because
// that one fix no longer fits), false when it can't (the whole post is
// stale, or the network is down) -- Accept all stops there.
async function accept(item) {
  if (reviewWrite) return false;
  reviewWrite = acceptOne(item);
  try {
    return await reviewWrite;
  } finally {
    reviewWrite = null;
  }
}

async function acceptOne(item) {
  const review = state.review;
  const blk = review && review.blocks.get(item.index);
  if (!blk) return false;
  const slug = state.slug;
  reviewBusy = true;
  renderReviewBar();
  try {
    let res;
    try {
      res = await fetch(`/api/posts/${slug}/proofread/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          index: item.index, block_hash: blk.block_hash,
          before: item.before, after: item.after, kind: item.kind, hash: state.hash,
        }),
      });
    } catch (err) {
      setStatus(`Network error. Nothing was changed: ${err.message}`);
      return false;
    }
    const open = state.review === review; // false: closed while it was out
    if (res.status === 409) {
      if (!open) return false;
      const detail = await errorDetail(res, 'That fix no longer fits its paragraph.');
      // _write_body's staleness 409s ("...; reload before saving") are about
      // the whole post: every later Accept would hit the same wall.
      if (/reload/.test(detail)) {
        setStatus('changed on disk — reload');
        return false;
      }
      dropItem(item, false);
      setStatus(`${detail} Skipped.`);
      afterResolve();
      return true;
    }
    if (!res.ok) {
      setStatus(`couldn't apply — ${await errorDetail(res)}`);
      return false;
    }
    // The block's new hash rides on the post payload; applyWrite (the same
    // path every other write takes) consumes the body, so read a copy.
    // Landed on the server either way, so `state` must take it (its new
    // hash) even if the review was closed while it was out.
    // ...unless `state` is another post by now (only the applyPost
    // backstop can get here; leaveReview waits for this write).
    if (state.slug !== slug) return false;
    const data = await res.clone().json();
    if (open) {
      blk.block_hash = data.block_hash;
      dropItem(item, true);
    }
    if (!(await applyWrite(res))) return false;
    if (open) afterResolve();
    return open;
  } finally {
    reviewBusy = false;
    if (state.review) renderReviewBar();
  }
}

function reject(item) {
  dropItem(item, false);
  setStatus('');
  afterResolve();
}

// Keeps going until the run has finished and nothing is left: suggestions
// from batches that arrive while it works are accepted too. Stops at the
// first write that can't go on (see accept), or when the review closes.
async function acceptAll() {
  const review = state.review;
  while (state.review === review && (review.items.length || proofRun)) {
    if (!review.items.length) {
      // Caught up with the batches that are back; wait for the next one.
      await new Promise((r) => setTimeout(r, 200));
      continue;
    }
    // Progress is suggestions resolved, not items left: a batch landing
    // mid-accept can refill the list, which isn't a stall.
    const resolved = () => review.seen - review.items.length;
    const before = resolved();
    if (!(await accept(review.items[0]))) return;
    if (resolved() <= before) return; // no progress
  }
}

function closeReview() {
  if (!reviewing()) return;
  if (proofRun) {
    proofRun.cancelled = true;
    proofRun.abort.abort();
    proofRun = null;
  }
  state.review = null;
  hideProofProgress();
  renderReviewBar();
  renderBlocks();
}

// For the bar actions that leave a review: close it, then let an Accept
// already on the wire land (applyWrite takes its new hash) before acting.
async function leaveReview() {
  closeReview();
  if (reviewWrite) await reviewWrite;
}

els.proofread.addEventListener('click', startProofread);
// Stops after the batch in flight is abandoned; what already came back
// stays up for review.
els.proofCancel.addEventListener('click', () => {
  if (!proofRun) return;
  proofRun.cancelled = true;
  proofRun.abort.abort();
});

async function newPost() {
  const title = prompt('Title for the new post:');
  if (!title) return;
  await leaveReview();
  await leavePlacing();
  if (!(await closeEditor())) return;

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

els.picker.addEventListener('change', async () => {
  const next = els.picker.value;
  await leaveReview();
  await leavePlacing();
  if (!(await closeEditor())) {
    els.picker.value = state.slug;
    return;
  }
  loadPost(next);
});
els.newPost.addEventListener('click', newPost);
els.title.addEventListener('click', startEditingTitle);

// The session cookie is HttpOnly, so this can't check "am I signed in" --
// it just asks the server to drop the session and reloads. A signed-out
// reload lands back on the sign-in card via editor_page's own check.
els.signOut.addEventListener('click', async () => {
  if (!(await flushPendingEdit())) return;
  try {
    await fetch('/auth/logout', { method: 'POST' });
  } catch {
    // Reload regardless -- a failed logout still lands wherever the
    // current session actually is.
  }
  location.reload();
});

// Typing that hasn't been saved yet goes out as the tab is hidden or closed
// (switching apps on the tablet, a reload). keepalive lets the request
// outlive the page.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') flushPendingEdit({ keepalive: true });
});
window.addEventListener('pagehide', () => flushPendingEdit({ keepalive: true }));

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
