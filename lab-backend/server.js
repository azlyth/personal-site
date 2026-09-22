const express = require('express');
const http = require('http');
const socketIo = require('socket.io');
const cors = require('cors');
const PersistenceLayer = require('./persistence');
const DrawingStore = require('./drawing-store');
const GameStore = require('./game-store');
const games = require('./games');

const app = express();
const server = http.createServer(app);

// Initialize persistence layer
const persistence = new PersistenceLayer();

// The drawing canvas keeps its state in memory and writes through to Redis on a
// timer -- see drawing-store.js for why it can't read-modify-write per packet.
const drawingStore = new DrawingStore(persistence);

// The turn-based games do the same thing for the same reason -- see
// game-store.js. Their rules live in games/<id>.js as pure functions.
const gameStore = new GameStore(persistence, games);

// Configure CORS
const corsOptions = {
  origin: [
    'http://localhost:1111',
    'http://127.0.0.1:1111',
    'http://0.0.0.0:1111',
    'http://192.168.1.191:1111',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://0.0.0.0:3000',
    'http://192.168.1.191:3000',
    'https://peter.direct',
    /\.peter\.direct$/,
    'https://cloudy.nyc',
    /\.cloudy\.nyc$/
  ],
  credentials: true
};

app.use(cors(corsOptions));

const io = socketIo(server, {
  cors: corsOptions
});

// Global Drawing session ID
const GLOBAL_DRAWING_SESSION = 'global-drawing-canvas';

const MAX_SEGMENTS_PER_PACKET = 256;

function isDrawableSegment(segment) {
  return segment
    && ['fromX', 'fromY', 'toX', 'toY'].every((key) => Number.isFinite(segment[key]))
    && typeof segment.color === 'string'
    && Number.isFinite(segment.lineWidth);
}

// Go game helper functions

// Which side each socket is bound to, per game. Sides are SHARED: several
// people can be on White at once. Binding holds YOU to a side, it does not
// reserve that side from anybody else -- so there is no ownership to track,
// nothing to release on a timer, and nobody can squat a seat on a public board.
const seatChoices = new Map(); // gameId -> Map(socketId -> seat id)

function seatLabel(gameId, seatId) {
  const game = games.getGame(gameId);
  const seat = game && game.seats.find((candidate) => candidate.id === seatId);
  return seat ? seat.label : seatId;
}

function setSeat(gameId, socketId, seat) {
  const game = games.getGame(gameId);
  const valid = game && game.seats.some((candidate) => candidate.id === seat) ? seat : null;

  let choices = seatChoices.get(gameId);
  if (!choices) {
    choices = new Map();
    seatChoices.set(gameId, choices);
  }
  // Anything that isn't one of this game's seats means "both sides", which is
  // the default and is stored as absence rather than as a value.
  if (valid) choices.set(socketId, valid);
  else choices.delete(socketId);
  return valid;
}

function seatOf(gameId, socketId) {
  const choices = seatChoices.get(gameId);
  return (choices && choices.get(socketId)) || null;
}

function seatCounts(gameId) {
  const game = games.getGame(gameId);
  if (!game) return {};
  const counts = Object.fromEntries(game.seats.map((seat) => [seat.id, 0]));
  const choices = seatChoices.get(gameId);
  if (choices) {
    for (const seat of choices.values()) {
      if (seat in counts) counts[seat] += 1;
    }
  }
  return counts;
}

function forgetSeats(socketId) {
  for (const choices of seatChoices.values()) choices.delete(socketId);
}

// One Socket.IO room per game. Everyone on the site shares one board per game,
// so the room is both the broadcast target and the player count.
function roomFor(gameId) {
  return `game:${gameId}`;
}

function playerCount(gameId) {
  return io.sockets.adapter.rooms.get(roomFor(gameId))?.size || 0;
}

function allPlayerCounts() {
  const counts = Object.fromEntries(games.GAMES.map((game) => [game.id, playerCount(game.id)]));
  // The drawing canvas isn't a turn-based game and keeps its own player list,
  // but it is a tile on the same menu, so it reports into the same count.
  counts.drawing = drawingStore.playerCount(GLOBAL_DRAWING_SESSION);
  return counts;
}

// The menu shows a live count on every tile, so a join or leave anywhere is
// news to everybody, not just the room being joined.
function broadcastPlayerCounts() {
  io.emit('game-counts', { counts: allPlayerCounts() });
}

// Every board update is shaped in one place, so a new field can't reach some
// clients and not others depending on which handler sent it.
function stateFor(gameId, state) {
  return {
    gameId,
    state,
    players: playerCount(gameId),
    canUndo: gameStore.canUndo(gameId),
    seatCounts: seatCounts(gameId)
  };
}

function broadcastSeats(gameId) {
  io.to(roomFor(gameId)).emit('game-seats', { gameId, seatCounts: seatCounts(gameId) });
}

// Initialize server with Redis connection and data loading
async function initializeServer() {
  console.log('Initializing server...');

  // Connect to Redis
  const redisConnected = await persistence.connect();
  if (redisConnected) {
    console.log('Redis connected, loading persisted data...');
  } else {
    console.warn('Redis connection failed, using in-memory storage only');
  }

  // Warm every board up front. Loading is the only asynchronous step in a
  // game's life; doing it here means a move handler is purely synchronous.
  for (const game of games.GAMES) {
    const state = await gameStore.load(game.id);
    console.log(`Loaded ${game.id} board (turn: ${state.turn}, over: ${state.over})`);
  }

  // Warm the shared drawing canvas; other drawing sessions load on demand
  const drawingState = await drawingStore.load(GLOBAL_DRAWING_SESSION);
  console.log(`Loaded drawing canvas with ${drawingState.strokes.length} strokes`);
}

// Clean up abandoned ad-hoc drawing sessions (older than 24 hours). The shared
// canvas and the game boards are permanent.
setInterval(async () => {
  const now = Date.now();
  const maxAge = 24 * 60 * 60 * 1000; // 24 hours

  for (const sessionId of drawingStore.sessionIds()) {
    if (sessionId === GLOBAL_DRAWING_SESSION) continue; // the shared canvas persists
    const drawingState = drawingStore.getState(sessionId);
    if (now - new Date(drawingState.lastActivity).getTime() > maxAge) {
      console.log(`Cleaning up old Drawing session: ${sessionId}`);
      await drawingStore.delete(sessionId);
    }
  }
}, 60 * 60 * 1000); // Check every hour

// Socket.IO connection handling
io.on('connection', (socket) => {
  console.log('Client connected:', socket.id);

  // Turn-based Game Socket Handlers
  //
  // One set of events for every game; which rules apply is decided by gameId.
  // Adding a game is a file in games/ and a tile on the menu, not more wiring.

  socket.on('game-list', () => {
    socket.emit('game-catalog', {
      games: games.GAMES.map(({ id, name, blurb, seats }) => ({ id, name, blurb, seats })),
      counts: allPlayerCounts()
    });
  });

  socket.on('game-join', async ({ gameId, seat } = {}) => {
    if (!games.getGame(gameId)) {
      socket.emit('game-error', { gameId, reason: 'No such game.' });
      return;
    }

    // Leave whatever was open before: the client shows one game at a time, so
    // a stale room would keep counting a player who has walked away.
    if (socket.gameId && socket.gameId !== gameId) {
      socket.leave(roomFor(socket.gameId));
    }

    const state = await gameStore.load(gameId);
    socket.join(roomFor(gameId));
    socket.gameId = gameId;
    setSeat(gameId, socket.id, seat);

    console.log(`Player joined ${gameId} as ${seatOf(gameId, socket.id) || 'both sides'} `
      + `(${playerCount(gameId)} watching)`);
    socket.emit('game-state', stateFor(gameId, state));
    broadcastSeats(gameId);
    broadcastPlayerCounts();
  });

  socket.on('game-seat', ({ gameId, seat } = {}) => {
    if (!games.getGame(gameId)) {
      socket.emit('game-error', { gameId, reason: 'No such game.' });
      return;
    }
    setSeat(gameId, socket.id, seat);
    broadcastSeats(gameId);
  });

  socket.on('game-leave', ({ gameId } = {}) => {
    const leaving = gameId || socket.gameId;
    if (!leaving) return;
    socket.leave(roomFor(leaving));
    if (socket.gameId === leaving) socket.gameId = null;
    setSeat(leaving, socket.id, null);
    broadcastSeats(leaving);
    broadcastPlayerCounts();
  });

  socket.on('game-move', ({ gameId, move } = {}) => {
    if (!games.getGame(gameId)) {
      socket.emit('game-error', { gameId, reason: 'No such game.' });
      return;
    }

    // A player bound to a side may only move on that side's turn. Unbound --
    // the default -- still moves for whoever is to play, which is what makes
    // playing both sides by yourself work.
    const seat = seatOf(gameId, socket.id);
    const current = gameStore.getState(gameId);
    if (seat && current && current.turn && current.turn !== seat) {
      socket.emit('game-error', {
        gameId,
        reason: `You are playing ${seatLabel(gameId, seat)}. `
          + `It is ${seatLabel(gameId, current.turn)}'s move.`
      });
      return;
    }

    // Synchronous from here, same discipline as the drawing canvas: nothing can
    // interleave between reading the board and installing the next one.
    const result = gameStore.applyMove(gameId, move);
    if (result.error) {
      socket.emit('game-error', { gameId, reason: result.error });
      return;
    }

    io.to(roomFor(gameId)).emit('game-state', stateFor(gameId, result.state));
  });

  // Undo is deliberately not seat-checked: on a board anyone can reset, anyone
  // can also step it back.
  socket.on('game-undo', ({ gameId } = {}) => {
    if (!games.getGame(gameId)) {
      socket.emit('game-error', { gameId, reason: 'No such game.' });
      return;
    }

    const result = gameStore.undo(gameId);
    if (result.error) {
      socket.emit('game-error', { gameId, reason: result.error });
      return;
    }

    console.log(`${gameId} stepped back by ${socket.id}`);
    io.to(roomFor(gameId)).emit('game-state', stateFor(gameId, result.state));
  });

  socket.on('game-reset', ({ gameId } = {}) => {
    if (!games.getGame(gameId)) {
      socket.emit('game-error', { gameId, reason: 'No such game.' });
      return;
    }

    const state = gameStore.reset(gameId);
    console.log(`${gameId} board reset by ${socket.id}`);
    io.to(roomFor(gameId)).emit('game-state', stateFor(gameId, state));
  });


  // Drawing Canvas Socket Handlers
  
  // Create new Drawing session (use global session)
  socket.on('create-drawing-session', async () => {
    const drawingState = await drawingStore.load(GLOBAL_DRAWING_SESSION);
    
    socket.join(GLOBAL_DRAWING_SESSION);
    
    console.log(`Desktop joined global Drawing session: ${GLOBAL_DRAWING_SESSION}`);
    socket.emit('drawing-session-created', { 
      sessionId: GLOBAL_DRAWING_SESSION, 
      drawingState: drawingState.strokes 
    });
  });
  
  // Join Drawing session
  socket.on('join-drawing-session', async ({ sessionId }) => {
    // The shared canvas is always available; any other id must already exist.
    if (sessionId !== GLOBAL_DRAWING_SESSION && !(await persistence.loadDrawingSession(sessionId))) {
      socket.emit('drawing-session-not-found');
      return;
    }
    
    const drawingState = await drawingStore.load(sessionId);
    
    socket.join(sessionId);
    socket.drawingSessionId = sessionId;
    
    const playerCount = drawingStore.addPlayer(sessionId, socket.id);
    
    console.log(`Player joined Drawing session ${sessionId}`);
    
    socket.emit('drawing-session-joined', { 
      sessionId, 
      drawingState: drawingState.strokes,
      playerCount
    });
    
    // Notify all clients in session about new player
    io.to(sessionId).emit('drawing-player-joined', { playerCount });
    broadcastPlayerCounts();
  });
  
  // Handle drawing data. Clients batch a stroke's points into `segments`, but a
  // single `{fromX, ...}` segment is still accepted so older tabs keep drawing.
  socket.on('drawing-data', async ({ sessionId, segments, gesture, fromX, fromY, toX, toY, color, lineWidth }) => {
    const batch = Array.isArray(segments)
      ? segments.map((segment) => ({ color, lineWidth, ...segment }))
      : [{ fromX, fromY, toX, toY, color, lineWidth }];
    
    const valid = batch.slice(0, MAX_SEGMENTS_PER_PACKET).filter(isDrawableSegment);
    if (valid.length === 0) return;
    
    if (!drawingStore.getState(sessionId)) {
      if (sessionId !== GLOBAL_DRAWING_SESSION && !(await persistence.loadDrawingSession(sessionId))) {
        socket.emit('drawing-session-not-found');
        return;
      }
      await drawingStore.load(sessionId);
    }
    
    // The client stamps one id per press-to-lift so undo can remove a stroke
    // rather than a few pixels. A tab open from before gestures existed sends
    // none, so each of its packets becomes its own stroke -- undo still walks
    // back sensibly, just in smaller steps.
    const strokeId = typeof gesture === 'string' && gesture
      ? gesture.slice(0, 64)
      : `${socket.id}-${Date.now()}`;

    // Synchronous from here: nothing can interleave between read and write, so
    // no stroke in a burst of packets can be lost.
    const strokes = drawingStore.appendSegments(sessionId, valid, strokeId);
    
    // Send only what is new; clients already hold the rest of the canvas.
    socket.to(sessionId).emit('drawing-append', { strokes });
  });
  
  // Handle stroke undo
  socket.on('drawing-undo', async ({ sessionId } = {}) => {
    if (!drawingStore.getState(sessionId)) {
      if (sessionId !== GLOBAL_DRAWING_SESSION && !(await persistence.loadDrawingSession(sessionId))) {
        socket.emit('drawing-session-not-found');
        return;
      }
      await drawingStore.load(sessionId);
    }

    const removed = drawingStore.undoLastGesture(sessionId);
    if (removed === 0) return;

    console.log(`Undid a ${removed}-segment stroke in session ${sessionId}`);

    // Removing strokes cannot be expressed as an append, so everybody repaints.
    io.to(sessionId).emit('drawing-undone', { drawingState: drawingStore.getStrokes(sessionId) });
  });

  // Handle canvas clear
  socket.on('clear-drawing-canvas', async ({ sessionId }) => {
    console.log(`Received clear-drawing-canvas: ${sessionId} from ${socket.id}`);
    if (!drawingStore.getState(sessionId)) {
      if (sessionId !== GLOBAL_DRAWING_SESSION && !(await persistence.loadDrawingSession(sessionId))) {
        console.log(`Drawing session not found for clear: ${sessionId}`);
        socket.emit('drawing-session-not-found');
        return;
      }
      await drawingStore.load(sessionId);
    }
    
    drawingStore.clear(sessionId);
    
    console.log(`Canvas cleared in session ${sessionId}`);
    
    // Broadcast clear to all clients in session
    io.to(sessionId).emit('drawing-cleared', { drawingState: drawingStore.getStrokes(sessionId) });
  });

  // Handle disconnection
  socket.on('disconnect', async () => {
    console.log('Client disconnected:', socket.id);

    if (socket.gameId) {
      const left = socket.gameId;
      forgetSeats(socket.id);
      // The room membership is already gone by now; the counts just need to
      // reach everyone still looking at the board and the menu.
      broadcastSeats(left);
      broadcastPlayerCounts();
    }

    // Handle Drawing session disconnection
    if (socket.drawingSessionId && drawingStore.getState(socket.drawingSessionId)) {
      const count = drawingStore.removePlayer(socket.drawingSessionId, socket.id);

      console.log(`Player left Drawing session ${socket.drawingSessionId}`);

      // Notify remaining players
      io.to(socket.drawingSessionId).emit('drawing-player-left', { playerCount: count });
      broadcastPlayerCounts();
    }
  });
});

// Health check endpoint
app.get('/health', async (req, res) => {
  const redisHealthy = await persistence.isHealthy();

  res.json({
    status: redisHealthy ? 'healthy' : 'degraded',
    timestamp: new Date().toISOString(),
    redis: {
      connected: persistence.isConnected,
      healthy: redisHealthy
    },
    games: allPlayerCounts(),
    activeDrawingSessions: drawingStore.sessionIds().length,
    totalDrawingPlayers: drawingStore.sessionIds().reduce((sum, sessionId) =>
      sum + drawingStore.playerCount(sessionId), 0)
  });
});

// Board state endpoint (for debugging)
app.get('/games', (req, res) => {
  res.json({
    games: games.GAMES.map(({ id, name, blurb, seats }) => ({
      id,
      name,
      blurb,
      seats,
      players: playerCount(id),
      seatCounts: seatCounts(id),
      canUndo: gameStore.canUndo(id),
      state: gameStore.getState(id)
    }))
  });
});

const PORT = process.env.PORT || 3001;

async function shutdown(signal) {
  console.log(`${signal} received, shutting down gracefully...`);
  await Promise.all([drawingStore.flushAll(), gameStore.flushAll()]);
  await persistence.disconnect();
  server.close(() => {
    console.log('Server shut down');
    process.exit(0);
  });
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

// Initialize server and start listening
initializeServer().then(() => {
  server.listen(PORT, () => {
    console.log(`Lab backend server running on port ${PORT}`);
    console.log(`Environment: ${process.env.NODE_ENV || 'development'}`);
    console.log(`Redis connection: ${persistence.isConnected ? 'connected' : 'failed'}`);
  });
}).catch((error) => {
  console.error('Failed to initialize server:', error);
  process.exit(1);
});
