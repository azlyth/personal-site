/**
 * Authoritative in-memory drawing state with coalesced persistence.
 *
 * The drawing canvas receives one packet per pointer move, and pointer moves
 * arrive faster than a Redis round trip. Reading the canvas back out of Redis
 * inside each packet handler meant two handlers could load the same version and
 * each save its own stroke on top of it, so every stroke in a batch but the
 * last was silently dropped. Here memory is the source of truth: a session is
 * read from persistence once, every mutation is synchronous (so a handler can
 * never be interleaved mid-update), and Redis is written behind the mutations
 * on a short timer.
 */
class DrawingStore {
  constructor(persistence, { flushIntervalMs = 250, maxStrokes = 20000 } = {}) {
    this.persistence = persistence;
    this.flushIntervalMs = flushIntervalMs;
    this.maxStrokes = maxStrokes;

    this.states = new Map();
    this.loads = new Map();
    this.writes = new Map();
    this.timers = new Map();
    this.dirty = new Set();
  }

  async load(sessionId) {
    if (this.states.has(sessionId)) return this.states.get(sessionId);
    if (this.loads.has(sessionId)) return this.loads.get(sessionId);

    const load = (async () => {
      const persisted = await this.persistence.loadDrawingSession(sessionId);
      // A concurrent load may have populated the session while we waited.
      if (!this.states.has(sessionId)) {
        this.states.set(sessionId, hydrate(persisted));
      }
      return this.states.get(sessionId);
    })();

    this.loads.set(sessionId, load);
    try {
      return await load;
    } finally {
      this.loads.delete(sessionId);
    }
  }

  getState(sessionId) {
    return this.states.get(sessionId);
  }

  getStrokes(sessionId) {
    const state = this.states.get(sessionId);
    return state ? state.strokes : [];
  }

  playerCount(sessionId) {
    const state = this.states.get(sessionId);
    return state ? state.players.size : 0;
  }

  sessionIds() {
    return Array.from(this.states.keys());
  }

  /** Appends segments and returns the stored strokes, in drawing order. */
  appendSegments(sessionId, segments) {
    const state = this.requireState(sessionId);
    const now = Date.now();
    const strokes = segments.map((segment) => ({
      fromX: segment.fromX,
      fromY: segment.fromY,
      toX: segment.toX,
      toY: segment.toY,
      color: segment.color,
      lineWidth: segment.lineWidth,
      timestamp: now
    }));

    state.strokes.push(...strokes);
    if (state.strokes.length > this.maxStrokes) {
      state.strokes.splice(0, state.strokes.length - this.maxStrokes);
    }
    this.touch(sessionId, state);
    return strokes;
  }

  clear(sessionId) {
    const state = this.requireState(sessionId);
    state.strokes = [];
    this.touch(sessionId, state);
  }

  addPlayer(sessionId, playerId) {
    const state = this.requireState(sessionId);
    state.players.set(playerId, { id: playerId, joinedAt: new Date() });
    this.touch(sessionId, state);
    return state.players.size;
  }

  removePlayer(sessionId, playerId) {
    const state = this.states.get(sessionId);
    if (!state) return 0;
    state.players.delete(playerId);
    this.touch(sessionId, state);
    return state.players.size;
  }

  async flush(sessionId) {
    const timer = this.timers.get(sessionId);
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(sessionId);
    }
    await this.writes.get(sessionId);
    if (this.dirty.has(sessionId)) await this.write(sessionId);
  }

  async flushAll() {
    await Promise.all(this.sessionIds().map((sessionId) => this.flush(sessionId)));
  }

  async delete(sessionId) {
    const timer = this.timers.get(sessionId);
    if (timer) clearTimeout(timer);
    this.timers.delete(sessionId);
    this.dirty.delete(sessionId);
    this.states.delete(sessionId);
    await this.persistence.deleteDrawingSession(sessionId);
  }

  requireState(sessionId) {
    const state = this.states.get(sessionId);
    if (!state) throw new Error(`drawing session ${sessionId} is not loaded`);
    return state;
  }

  touch(sessionId, state) {
    state.lastActivity = new Date();
    this.dirty.add(sessionId);
    this.scheduleWrite(sessionId);
  }

  scheduleWrite(sessionId) {
    if (this.timers.has(sessionId) || this.writes.has(sessionId)) return;
    const timer = setTimeout(() => {
      this.timers.delete(sessionId);
      this.write(sessionId).catch((error) => {
        console.error(`Failed to persist drawing session ${sessionId}:`, error);
      });
    }, this.flushIntervalMs);
    if (typeof timer.unref === 'function') timer.unref();
    this.timers.set(sessionId, timer);
  }

  write(sessionId) {
    const inFlight = this.writes.get(sessionId);
    if (inFlight) return inFlight;

    const write = (async () => {
      try {
        // Loop rather than return: mutations that land during a save mark the
        // session dirty again and must reach persistence too.
        while (this.dirty.has(sessionId)) {
          this.dirty.delete(sessionId);
          const state = this.states.get(sessionId);
          if (!state) break;
          await this.persistence.saveDrawingSession(
            sessionId,
            this.persistence.serializeDrawingState(state)
          );
        }
      } finally {
        this.writes.delete(sessionId);
      }
    })();

    this.writes.set(sessionId, write);
    return write;
  }
}

function hydrate(persisted) {
  if (!persisted) {
    return {
      strokes: [],
      players: new Map(),
      createdAt: new Date(),
      lastActivity: new Date()
    };
  }

  return {
    strokes: Array.isArray(persisted.strokes) ? persisted.strokes : [],
    players: persisted.players instanceof Map ? persisted.players : new Map(persisted.players || []),
    createdAt: persisted.createdAt || new Date(),
    lastActivity: persisted.lastActivity || new Date()
  };
}

module.exports = DrawingStore;
