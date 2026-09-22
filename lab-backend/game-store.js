/**
 * Authoritative in-memory board state for the turn-based lab games.
 *
 * Same shape of problem the drawing canvas had, and the same answer: a board is
 * read out of persistence once, every mutation after that is SYNCHRONOUS so two
 * socket handlers can never load the same version and each save over the other,
 * and Redis is written behind the mutations on a short coalescing timer. The
 * rules themselves live in ./games/<id>.js as pure functions; this class only
 * owns "which board is current, and when does it reach Redis".
 *
 * One board per game id. Every visitor to the site shares it, which is the
 * whole point - the lab has always been one global Go board, not a lobby.
 */

// Bumped whenever a game's persisted shape changes. A board stored under a
// version this code cannot read is discarded rather than fed to a rule module
// that no longer understands it -- but a readable older shape is ADOPTED, not
// thrown away, because discarding it would wipe a game in progress on deploy.
// v1: { v, state }.  v2: { v, state, history }.
const STATE_VERSION = 2;

// How far back undo can walk. Undo is shared -- anyone on the board can press
// it -- so this is a depth, not a per-player allowance.
const MAX_HISTORY = 20;

class GameStore {
  constructor(persistence, games, { flushIntervalMs = 200 } = {}) {
    this.persistence = persistence;
    this.games = games; // { getGame(id) }
    this.flushIntervalMs = flushIntervalMs;

    this.states = new Map();
    this.histories = new Map(); // gameId -> prior states, oldest first
    this.loads = new Map();
    this.writes = new Map();
    this.timers = new Map();
    this.dirty = new Set();
  }

  async load(gameId) {
    const game = this.requireGame(gameId);
    if (this.states.has(gameId)) return this.states.get(gameId);
    if (this.loads.has(gameId)) return this.loads.get(gameId);

    const load = (async () => {
      const persisted = await this.persistence.loadGameState(gameId);
      // A concurrent load may have populated the board while we waited.
      if (!this.states.has(gameId)) {
        const readable = persisted && persisted.state
          && (persisted.v === 1 || persisted.v === STATE_VERSION);
        this.states.set(gameId, readable ? persisted.state : game.initialState());
        // A v1 board predates undo, so it arrives with nothing to undo to.
        this.histories.set(gameId, readable && Array.isArray(persisted.history)
          ? persisted.history.slice(-MAX_HISTORY)
          : []);
      }
      return this.states.get(gameId);
    })();

    this.loads.set(gameId, load);
    try {
      return await load;
    } finally {
      this.loads.delete(gameId);
    }
  }

  getState(gameId) {
    return this.states.get(gameId) || null;
  }

  /**
   * Synchronous by design - nothing may interleave between reading the current
   * board and installing the next one. Returns { state } or { error }.
   */
  applyMove(gameId, move) {
    const game = this.requireGame(gameId);
    const state = this.states.get(gameId);
    if (!state) return { error: 'That game is still loading. Try again.' };

    let result;
    try {
      result = game.applyMove(state, move);
    } catch (error) {
      console.error(`${gameId}: rule module threw on move`, move, error);
      return { error: 'That move confused the board.' };
    }

    if (!result || (!result.state && !result.error)) {
      console.error(`${gameId}: rule module returned nothing useful`, result);
      return { error: 'That move confused the board.' };
    }
    if (result.error) return { error: result.error };

    this.remember(gameId, state);
    this.states.set(gameId, result.state);
    this.touch(gameId);
    return { state: result.state };
  }

  reset(gameId) {
    const game = this.requireGame(gameId);
    // A reset is undoable on purpose: anybody on a shared board can wipe it,
    // and "someone just cleared the game I was playing" is exactly the moment
    // you want a way back.
    const previous = this.states.get(gameId);
    if (previous) this.remember(gameId, previous);
    const state = game.initialState();
    this.states.set(gameId, state);
    this.touch(gameId);
    return state;
  }

  /** Steps the board back one move. Returns { state } or { error }. */
  undo(gameId) {
    this.requireGame(gameId);
    const history = this.histories.get(gameId);
    if (!history || history.length === 0) return { error: 'Nothing to undo.' };

    const state = history.pop();
    this.states.set(gameId, state);
    this.touch(gameId);
    return { state };
  }

  canUndo(gameId) {
    const history = this.histories.get(gameId);
    return Boolean(history && history.length);
  }

  remember(gameId, state) {
    const history = this.histories.get(gameId) || [];
    history.push(state);
    if (history.length > MAX_HISTORY) history.splice(0, history.length - MAX_HISTORY);
    this.histories.set(gameId, history);
  }

  gameIds() {
    return Array.from(this.states.keys());
  }

  async flush(gameId) {
    const timer = this.timers.get(gameId);
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(gameId);
    }
    await this.writes.get(gameId);
    if (this.dirty.has(gameId)) await this.write(gameId);
  }

  async flushAll() {
    await Promise.all(this.gameIds().map((gameId) => this.flush(gameId)));
  }

  requireGame(gameId) {
    const game = this.games.getGame(gameId);
    if (!game) throw new Error(`unknown game ${gameId}`);
    return game;
  }

  touch(gameId) {
    this.dirty.add(gameId);
    this.scheduleWrite(gameId);
  }

  scheduleWrite(gameId) {
    if (this.timers.has(gameId) || this.writes.has(gameId)) return;
    const timer = setTimeout(() => {
      this.timers.delete(gameId);
      this.write(gameId).catch((error) => {
        console.error(`Failed to persist game ${gameId}:`, error);
      });
    }, this.flushIntervalMs);
    if (typeof timer.unref === 'function') timer.unref();
    this.timers.set(gameId, timer);
  }

  write(gameId) {
    const inFlight = this.writes.get(gameId);
    if (inFlight) return inFlight;

    const write = (async () => {
      try {
        // Loop rather than return: moves that land during a save mark the board
        // dirty again and must reach persistence too.
        while (this.dirty.has(gameId)) {
          this.dirty.delete(gameId);
          const state = this.states.get(gameId);
          if (!state) break;
          await this.persistence.saveGameState(gameId, {
            v: STATE_VERSION,
            state,
            history: this.histories.get(gameId) || []
          });
        }
      } finally {
        this.writes.delete(gameId);
      }
    })();

    this.writes.set(gameId, write);
    return write;
  }
}

module.exports = GameStore;
module.exports.STATE_VERSION = STATE_VERSION;
module.exports.MAX_HISTORY = MAX_HISTORY;
