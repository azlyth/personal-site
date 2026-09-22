// Editor front end. Blocks render as HTML; tapping one swaps in its raw
// markdown, so the source is always what gets edited and saved.
//
// `moveIndex` is null outside move mode, or the index (as the client
// currently sees the block list) of the block picked up by the Move
// control. While set, renderBlocks() renders drop targets instead of the
// normal editable blocks -- see renderMoveTargets().
const state = { slug: null, hash: null, blocks: [], moveIndex: null };

const els = {
  picker: document.getElementById('post-picker'),
  newPost: document.getElementById('new-post'),
  title: document.getElementById('post-title'),
  meta: document.getElementById('post-meta'),
  blocks: document.getElementById('blocks'),
  status: document.getElementById('status'),
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
  els.title.textContent = data.meta.title;
  renderMeta(data.meta);
  setStatus('saved');
  await refreshStatus();
}

function renderMeta(meta) {
  els.meta.innerHTML = '';

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

  els.meta.append(date, draftLabel, renameBtn);
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
  els.blocks.innerHTML = '';

  if (state.moveIndex !== null) {
    renderMoveTargets();
    return;
  }

  state.blocks.forEach((block) => {
    const el = document.createElement('div');
    el.className = 'block';
    el.dataset.index = block.index;

    // Content lives in its own child so the per-block editors below can
    // wipe and rebuild *just this* -- blockControls() (Move, delete, ...)
    // is appended to `el` as a sibling, not a descendant of `content`, so
    // opening an editor can never take the controls out with it. See
    // startEditing/startEditingImages/startEditingVideos.
    const content = document.createElement('div');
    content.className = 'block-content';
    content.innerHTML = block.html;
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
      if (block.images) {
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
    els.blocks.appendChild(el);

    if (canMergeWithNext(block.index)) {
      els.blocks.appendChild(mergeControl(block.index));
    }
  });
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
  add.title = 'Insert a paragraph here';
  add.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!(await flushPendingEdit())) return;
    insertBlock(block.index);
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

  const move = document.createElement('button');
  move.textContent = '⇅';
  move.title = 'Move this block';
  move.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!(await flushPendingEdit())) return;
    enterMoveMode(block.index);
  });

  bar.append(add, photo, move, del);
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
  state.moveIndex = null;
  renderBlocks();
}

function renderMoveTargets() {
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
  els.blocks.appendChild(banner);

  const dropTarget = (gapIndex) => {
    const target = document.createElement('button');
    target.type = 'button';
    target.className = 'move-target';
    target.textContent = 'Place here';
    target.addEventListener('click', () => submitMove(state.moveIndex, gapIndex));
    els.blocks.appendChild(target);
  };

  state.blocks.forEach((block, i) => {
    dropTarget(i);

    const el = document.createElement('div');
    el.className = 'block move-preview' + (i === state.moveIndex ? ' move-source' : '');
    el.innerHTML = block.html;
    els.blocks.appendChild(el);
  });
  dropTarget(state.blocks.length);
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

async function insertBlock(index) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index, source: 'New paragraph.', hash: state.hash }),
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
  renderBlocks();
  setStatus('saved');
  await refreshStatus();
  // Callers that need to know whether the write actually landed --
  // flushPendingEdit() is the one that matters here -- get an honest
  // answer instead of having to re-derive it from side effects.
  return true;
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
  let size = block.size;

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

  // Same Small/Medium/Full control as the video row editor -- server-side,
  // choosing a non-default size on a lone photo is what promotes it from
  // plain markdown to a wrapped, sized `.img-row` (see images.py's
  // markdown_for); the button UI itself doesn't need to know that.
  const sizes = document.createElement('div');
  sizes.className = 'size-buttons';
  [
    ['small', 'Small'],
    ['medium', 'Medium'],
    ['full', 'Full'],
  ].forEach(([value, label]) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = label;
    if (value === size) btn.classList.add('active');
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      size = value;
      sizes.querySelectorAll('button').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
    });
    sizes.appendChild(btn);
  });
  content.appendChild(sizes);

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
    saveBlockImages(block.index, images, size);
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

async function saveBlockImages(index, images, size) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}/images`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ images, size, hash: state.hash }),
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
  let size = block.size;

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
        splitBlockVideo(block.index, clips, size, i);
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

  const sizes = document.createElement('div');
  sizes.className = 'size-buttons';
  [
    ['small', 'Small'],
    ['medium', 'Medium'],
    ['full', 'Full'],
  ].forEach(([value, label]) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = label;
    if (value === size) btn.classList.add('active');
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      size = value;
      sizes.querySelectorAll('button').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
    });
    sizes.appendChild(btn);
  });
  content.appendChild(sizes);

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
    saveBlockVideos(block.index, clips, size);
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

async function saveBlockVideos(index, clips, size) {
  setStatus('saving…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}/videos`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ videos: clips, size, hash: state.hash }),
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
async function splitBlockVideo(index, clips, size, split) {
  setStatus('splitting…');
  let res;
  try {
    res = await fetch(`/api/posts/${state.slug}/blocks/${index}/videos/split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ videos: clips, size, split, hash: state.hash }),
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
