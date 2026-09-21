// Editor front end. Blocks render as HTML; tapping one swaps in its raw
// markdown, so the source is always what gets edited and saved.
const state = { slug: null, hash: null, blocks: [] };

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
  const res = await fetch('/api/posts');
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
  const res = await fetch(`/api/posts/${slug}`);
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
  const res = await fetch(`/api/posts/${state.slug}/meta`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...fields, hash: state.hash }),
  });

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
  const res = await fetch(`/api/posts/${current}/rename`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_slug: next, hash: state.hash }),
  });

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
  state.blocks.forEach((block) => {
    const el = document.createElement('div');
    el.className = 'block';
    el.dataset.index = block.index;
    el.innerHTML = block.html;
    el.addEventListener('click', () => {
      // A photo block (a standalone image or an .img-row) gets a thumbnail
      // strip -- add/remove/reorder/alt-text -- instead of raw markup in a
      // textarea. Everything else still edits its markdown source directly.
      if (block.kind === 'image' || block.kind === 'img_row') {
        startEditingImages(el, block);
      } else {
        startEditing(el, block);
      }
    });
    el.appendChild(blockControls(block));
    els.blocks.appendChild(el);
  });
}

function blockControls(block) {
  const bar = document.createElement('div');
  bar.className = 'block-controls';

  const add = document.createElement('button');
  add.textContent = '+';
  add.title = 'Insert a paragraph here';
  add.addEventListener('click', (e) => {
    e.stopPropagation();
    insertBlock(block.index);
  });

  const del = document.createElement('button');
  del.textContent = '×';
  del.title = 'Delete this block';
  del.addEventListener('click', (e) => {
    e.stopPropagation();
    if (confirm('Delete this block?')) removeBlock(block.index);
  });

  const photo = document.createElement('button');
  photo.textContent = '🖼';
  photo.title = 'Add photos here';
  photo.addEventListener('click', (e) => {
    e.stopPropagation();
    pickImages(block.index);
  });
  bar.append(add, photo, del);
  return bar;
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
    await applyWrite(await fetch(`/api/posts/${state.slug}/images`, {
      method: 'POST',
      body: form,
    }));
  });

  input.click();
}

async function insertBlock(index) {
  setStatus('saving…');
  const res = await fetch(`/api/posts/${state.slug}/blocks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ index, source: 'New paragraph.', hash: state.hash }),
  });
  await applyWrite(res);
}

async function removeBlock(index) {
  setStatus('saving…');
  const res = await fetch(`/api/posts/${state.slug}/blocks/${index}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ hash: state.hash }),
  });
  await applyWrite(res);
}

async function applyWrite(res) {
  if (res.status === 409) {
    setStatus('changed on disk — reload');
    return;
  }
  if (!res.ok) {
    // As in saveMeta: don't touch `state` or call renderBlocks() -- that
    // would wipe out whatever's still sitting in an open textarea with an
    // error body's `undefined` fields. Leave the editing UI exactly as is.
    setStatus(`save failed — ${await errorDetail(res)}`);
    return;
  }
  const data = await res.json();
  state.hash = data.hash;
  state.blocks = data.blocks;
  renderBlocks();
  setStatus('saved');
  await refreshStatus();
}

async function refreshStatus() {
  const data = await (await fetch('/api/status')).json();
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

  const res = await fetch('/api/publish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
  const data = await res.json();

  setStatus(data.message);
  await refreshStatus();
});

function startEditing(el, block) {
  if (el.classList.contains('editing')) return;
  el.classList.add('editing');
  el.innerHTML = '';

  const textarea = document.createElement('textarea');
  textarea.value = block.source;
  textarea.rows = Math.max(2, block.source.split('\n').length + 1);
  el.appendChild(textarea);
  textarea.focus();

  textarea.addEventListener('blur', async () => {
    el.classList.remove('editing');
    if (textarea.value === block.source) {
      el.innerHTML = block.html;
      return;
    }
    await saveBlock(block.index, textarea.value);
  });
}

async function saveBlock(index, source) {
  setStatus('saving…');
  const res = await fetch(`/api/posts/${state.slug}/blocks/${index}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, hash: state.hash }),
  });
  await applyWrite(res);
}

// Thumbnail editor for an `image`/`img_row` block. All markup generation
// (standalone vs. .img-row, alt-text escaping) stays server-side -- this
// only ever collects/reorders a list of {url, alt} and hands it to
// PUT .../blocks/{index}/images, which regenerates the source via the same
// markdown_for() the upload route uses.
function startEditingImages(el, block) {
  if (el.classList.contains('editing')) return;
  el.classList.add('editing');
  el.innerHTML = '';

  // A local working copy -- nothing here touches `state` until Done saves.
  const images = block.images.map((img) => ({ ...img }));

  const strip = document.createElement('div');
  strip.className = 'image-strip';
  el.appendChild(strip);

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
      left.addEventListener('click', () => {
        [images[i - 1], images[i]] = [images[i], images[i - 1]];
        renderThumbs();
      });

      const right = document.createElement('button');
      right.type = 'button';
      right.className = 'image-move';
      right.textContent = '→';
      right.title = 'Move right';
      right.disabled = i === images.length - 1;
      right.addEventListener('click', () => {
        [images[i], images[i + 1]] = [images[i + 1], images[i]];
        renderThumbs();
      });

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'image-remove';
      remove.textContent = '×';
      remove.title = 'Remove this photo';
      remove.addEventListener('click', () => {
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
    add.addEventListener('click', addPhotosToStrip);
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
      const res = await fetch(`/api/posts/${state.slug}/images/upload`, {
        method: 'POST',
        body: form,
      });
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

  const actions = document.createElement('div');
  actions.className = 'image-editor-actions';

  const done = document.createElement('button');
  done.type = 'button';
  done.className = 'image-done';
  done.textContent = 'Done';
  done.addEventListener('click', () => saveBlockImages(block.index, images));

  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'image-cancel';
  cancel.textContent = 'Cancel';
  cancel.addEventListener('click', () => {
    el.classList.remove('editing');
    el.innerHTML = block.html;
  });

  actions.append(done, cancel);
  el.appendChild(actions);

  renderThumbs();
}

async function saveBlockImages(index, images) {
  setStatus('saving…');
  const res = await fetch(`/api/posts/${state.slug}/blocks/${index}/images`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ images, hash: state.hash }),
  });
  // applyWrite re-renders every block from the fresh server response on
  // success, and on failure leaves the DOM untouched -- exactly right here
  // too: a failed save keeps the thumbnail editor open with the user's
  // reorder/remove/alt-text edits intact, not silently discarded.
  await applyWrite(res);
}

async function newPost() {
  const title = prompt('Title for the new post:');
  if (!title) return;

  setStatus('creating…');
  const res = await fetch('/api/posts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });

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
