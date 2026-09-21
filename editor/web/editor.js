// Editor front end. Blocks render as HTML; tapping one swaps in its raw
// markdown, so the source is always what gets edited and saved.
const state = { slug: null, hash: null, blocks: [] };

const els = {
  picker: document.getElementById('post-picker'),
  title: document.getElementById('post-title'),
  meta: document.getElementById('post-meta'),
  blocks: document.getElementById('blocks'),
  status: document.getElementById('status'),
  publish: document.getElementById('publish'),
};

function setStatus(text) {
  els.status.textContent = text;
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
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      // response body wasn't JSON; fall back to statusText above
    }
    setStatus(`couldn't load ${slug} — ${detail}`);
    return;
  }
  const data = await res.json();
  state.slug = data.slug;
  state.hash = data.hash;
  state.blocks = data.blocks;

  els.title.textContent = data.meta.title;
  els.meta.textContent = data.meta.date + (data.meta.draft ? ' · draft' : '');
  renderBlocks();
  setStatus('');
}

function renderBlocks() {
  els.blocks.innerHTML = '';
  state.blocks.forEach((block) => {
    const el = document.createElement('div');
    el.className = 'block';
    el.dataset.index = block.index;
    el.innerHTML = block.html;
    el.addEventListener('click', () => startEditing(el, block));
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

  bar.append(add, del);
  return bar;
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

els.picker.addEventListener('change', () => loadPost(els.picker.value));

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
