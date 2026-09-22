const test = require('node:test');
const assert = require('node:assert');
const GameStore = require('../game-store');

const { STATE_VERSION, MAX_HISTORY } = GameStore;

// A deliberately trivial game: the board is a list of the moves played, so a
// test can see at a glance which position the store is holding. The rules of a
// real game are tested in test/games/; what is under test here is the history.
const counting = {
  id: 'counting',
  name: 'Counting',
  blurb: 'A test double.',
  seats: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }],
  initialState() {
    return { played: [], turn: 'a', over: false, result: null };
  },
  applyMove(state, move) {
    if (move && move.bad) return { error: 'No.' };
    return {
      state: {
        played: state.played.concat([move.n]),
        turn: state.turn === 'a' ? 'b' : 'a',
        over: false,
        result: null
      }
    };
  }
};

const registry = { getGame: (id) => (id === 'counting' ? counting : null) };

function fakePersistence(initial = null) {
  let stored = initial;
  return {
    get stored() { return stored; },
    async loadGameState() { return stored; },
    async saveGameState(gameId, payload) {
      stored = JSON.parse(JSON.stringify(payload));
      return true;
    }
  };
}

async function freshStore(initial = null) {
  const store = new GameStore(fakePersistence(initial), registry, { flushIntervalMs: 5 });
  await store.load('counting');
  return store;
}

test('a fresh board has nothing to undo', async () => {
  const store = await freshStore();
  assert.equal(store.canUndo('counting'), false);
  assert.deepEqual(store.undo('counting'), { error: 'Nothing to undo.' });
});

test('undo steps the board back one move', async () => {
  const store = await freshStore();
  store.applyMove('counting', { n: 1 });
  store.applyMove('counting', { n: 2 });
  assert.deepEqual(store.getState('counting').played, [1, 2]);

  const undone = store.undo('counting');
  assert.deepEqual(undone.state.played, [1]);
  assert.deepEqual(store.getState('counting').played, [1]);
});

test('undo walks back repeatedly, then runs out', async () => {
  const store = await freshStore();
  store.applyMove('counting', { n: 1 });
  store.applyMove('counting', { n: 2 });
  store.applyMove('counting', { n: 3 });

  assert.deepEqual(store.undo('counting').state.played, [1, 2]);
  assert.deepEqual(store.undo('counting').state.played, [1]);
  assert.deepEqual(store.undo('counting').state.played, []);
  assert.equal(store.canUndo('counting'), false);
  assert.ok(store.undo('counting').error);
});

test('undo restores whose turn it was, not just the board', async () => {
  const store = await freshStore();
  store.applyMove('counting', { n: 1 });
  assert.equal(store.getState('counting').turn, 'b');
  store.undo('counting');
  assert.equal(store.getState('counting').turn, 'a');
});

test('a rejected move does not become an undo step', async () => {
  const store = await freshStore();
  store.applyMove('counting', { n: 1 });
  assert.ok(store.applyMove('counting', { bad: true }).error);

  assert.deepEqual(store.undo('counting').state.played, []);
  assert.equal(store.canUndo('counting'), false);
});

test('a reset is undoable, because anyone on a shared board can trigger one', async () => {
  const store = await freshStore();
  store.applyMove('counting', { n: 1 });
  store.applyMove('counting', { n: 2 });

  store.reset('counting');
  assert.deepEqual(store.getState('counting').played, []);
  assert.equal(store.canUndo('counting'), true);

  assert.deepEqual(store.undo('counting').state.played, [1, 2]);
});

test('history is capped and drops the oldest positions first', async () => {
  const store = await freshStore();
  for (let n = 1; n <= MAX_HISTORY + 5; n++) store.applyMove('counting', { n });

  let steps = 0;
  while (store.canUndo('counting')) {
    store.undo('counting');
    steps++;
    assert.ok(steps <= MAX_HISTORY + 1, 'history grew past its cap');
  }
  assert.equal(steps, MAX_HISTORY);

  // Walking all the way back lands on the oldest position still remembered,
  // which is partway in rather than the empty board.
  assert.deepEqual(store.getState('counting').played, [1, 2, 3, 4, 5]);
});

test('history reaches persistence with the board', async () => {
  const store = await freshStore();
  store.applyMove('counting', { n: 1 });
  store.applyMove('counting', { n: 2 });
  await store.flush('counting');

  const written = store.persistence.stored;
  assert.equal(written.v, STATE_VERSION);
  assert.deepEqual(written.state.played, [1, 2]);
  assert.equal(written.history.length, 2);
});

test('a persisted board and its history come back after a restart', async () => {
  const first = await freshStore();
  first.applyMove('counting', { n: 1 });
  first.applyMove('counting', { n: 2 });
  await first.flush('counting');

  const second = new GameStore(fakePersistence(first.persistence.stored), registry);
  await second.load('counting');

  assert.deepEqual(second.getState('counting').played, [1, 2]);
  assert.equal(second.canUndo('counting'), true);
  assert.deepEqual(second.undo('counting').state.played, [1]);
});

test('a board saved before undo existed is adopted, not thrown away', async () => {
  // The v1 shape carried no history. Discarding it would have wiped every
  // game in progress the moment undo shipped.
  const legacy = { v: 1, state: { played: [7], turn: 'b', over: false, result: null } };
  const store = new GameStore(fakePersistence(legacy), registry);
  await store.load('counting');

  assert.deepEqual(store.getState('counting').played, [7]);
  assert.equal(store.canUndo('counting'), false);
});

test('a board saved under an unreadable version is discarded', async () => {
  const future = { v: 99, state: { played: [7], turn: 'b', over: false, result: null } };
  const store = new GameStore(fakePersistence(future), registry);
  await store.load('counting');

  assert.deepEqual(store.getState('counting').played, []);
});

test('undo does not hand back the same object the caller already holds', async () => {
  const store = await freshStore();
  const before = store.getState('counting');
  store.applyMove('counting', { n: 1 });
  const restored = store.undo('counting').state;

  assert.deepEqual(restored, before);
  restored.played.push(99);
  assert.deepEqual(store.getState('counting').played, [99],
    'the store holds exactly the object it returned, so callers must not mutate it');
});
