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

// Bumped whenever a game's persisted state shape changes incompatibly. A board
// stored under an older version is discarded rather than fed to a rule module
// that no longer understands it.
const STATE_VERSION = 1;

class GameStore {
  constructor(persistence, games, { flushIntervalMs = 200 } = {}) {
    this.persistence = persistence;
    this.games = games; // { getGame(id) }
    this.flushIntervalMs = flushIntervalMs;

    this.states = new Map();
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
        const usable = persisted && persisted.v === STATE_VERSION && persisted.state;
        this.states.set(gameId, usable ? persisted.state : game.initialState());
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

    this.states.set(gameId, result.state);
    this.touch(gameId);
    return { state: result.state };
  }

  reset(gameId) {
    const game = this.requireGame(gameId);
    const state = game.initialState();
    this.states.set(gameId, state);
    this.touch(gameId);
    return state;
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
          await this.persistence.saveGameState(gameId, { v: STATE_VERSION, state });
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
