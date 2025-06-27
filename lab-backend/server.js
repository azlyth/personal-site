const express = require('express');
const http = require('http');
const socketIo = require('socket.io');
const cors = require('cors');
const { v4: uuidv4 } = require('uuid');

const app = express();
const server = http.createServer(app);

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
    /\.peter\.direct$/
  ],
  credentials: true
};

app.use(cors(corsOptions));

const io = socketIo(server, {
  cors: corsOptions
});

// In-memory session storage
const sessions = new Map();
const goSessions = new Map();
const drawingSessions = new Map();

// Global Go session ID
const GLOBAL_GO_SESSION = 'global-go-game';

// Global Drawing session ID
const GLOBAL_DRAWING_SESSION = 'global-drawing-canvas';

// Go game helper functions
function getNeighbors(row, col) {
  const neighbors = [];
  if (row > 0) neighbors.push([row - 1, col]);
  if (row < 8) neighbors.push([row + 1, col]);
  if (col > 0) neighbors.push([row, col - 1]);
  if (col < 8) neighbors.push([row, col + 1]);
  return neighbors;
}

function getGroup(board, row, col, color, visited = new Set()) {
  const key = `${row},${col}`;
  if (visited.has(key) || board[row][col] !== color) {
    return [];
  }
  
  visited.add(key);
  const group = [[row, col]];
  
  const neighbors = getNeighbors(row, col);
  for (const [nRow, nCol] of neighbors) {
    if (board[nRow][nCol] === color) {
      group.push(...getGroup(board, nRow, nCol, color, visited));
    }
  }
  
  return group;
}

function hasLiberties(board, group) {
  for (const [row, col] of group) {
    const neighbors = getNeighbors(row, col);
    for (const [nRow, nCol] of neighbors) {
      if (board[nRow][nCol] === null) {
        return true; // Found an empty space (liberty)
      }
    }
  }
  return false; // No liberties found
}

function checkAndRemoveCaptures(board, lastRow, lastCol, lastColor) {
  const capturedStones = [];
  const opponentColor = lastColor === 'black' ? 'white' : 'black';
  const processedGroups = new Set();
  
  // Check all adjacent opponent stones for captures
  const neighbors = getNeighbors(lastRow, lastCol);
  for (const [nRow, nCol] of neighbors) {
    if (board[nRow][nCol] === opponentColor) {
      const groupKey = `${nRow},${nCol}`;
      if (!processedGroups.has(groupKey)) {
        const group = getGroup(board, nRow, nCol, opponentColor);
        
        // Mark all stones in this group as processed
        for (const [gRow, gCol] of group) {
          processedGroups.add(`${gRow},${gCol}`);
        }
        
        // If the group has no liberties, capture it
        if (!hasLiberties(board, group)) {
          for (const [gRow, gCol] of group) {
            board[gRow][gCol] = null;
            capturedStones.push([gRow, gCol]);
          }
        }
      }
    }
  }
  
  return capturedStones;
}

// Global counter shared by all sessions
let globalCounter = 0;

// Session structure:
// {
//   id: string,
//   devices: [{ id: string, socketId: string }],
//   createdAt: Date,
//   lastActivity: Date
// }

// Clean up old sessions (older than 24 hours)
setInterval(() => {
  const now = Date.now();
  const maxAge = 24 * 60 * 60 * 1000; // 24 hours
  
  for (const [sessionId, session] of sessions.entries()) {
    if (now - session.lastActivity.getTime() > maxAge) {
      console.log(`Cleaning up old session: ${sessionId}`);
      sessions.delete(sessionId);
    }
  }
}, 60 * 60 * 1000); // Check every hour

// Socket.IO connection handling
io.on('connection', (socket) => {
  console.log('Client connected:', socket.id);
  
  // Create new session
  socket.on('create-session', () => {
    const sessionId = uuidv4().substring(0, 8); // Short session ID
    const session = {
      id: sessionId,
      devices: [],
      createdAt: new Date(),
      lastActivity: new Date()
    };
    
    sessions.set(sessionId, session);
    socket.join(sessionId);
    
    console.log(`Session created: ${sessionId}`);
    socket.emit('session-created', { sessionId, counter: globalCounter });
  });
  
  // Join existing session
  socket.on('join-session', ({ sessionId }) => {
    const session = sessions.get(sessionId);
    
    if (!session) {
      socket.emit('session-not-found');
      return;
    }
    
    // Add device to session
    const device = {
      id: uuidv4().substring(0, 8),
      socketId: socket.id
    };
    
    session.devices.push(device);
    session.lastActivity = new Date();
    
    socket.join(sessionId);
    socket.sessionId = sessionId;
    socket.deviceId = device.id;
    
    console.log(`Device ${device.id} joined session ${sessionId}`);
    
    socket.emit('session-joined', { sessionId, deviceId: device.id, counter: globalCounter });
    
    // Notify all clients in session about new device
    io.to(sessionId).emit('device-connected', {
      devices: session.devices,
      counter: globalCounter
    });
  });
  
  // Handle counter increment
  socket.on('increment', ({ sessionId }) => {
    const session = sessions.get(sessionId);
    
    if (!session) {
      socket.emit('session-not-found');
      return;
    }
    
    globalCounter++;
    session.lastActivity = new Date();
    
    console.log(`Global counter incremented to ${globalCounter} by session ${sessionId}`);
    
    // Broadcast to ALL connected clients
    io.emit('counter-update', {
      value: globalCounter,
      action: 'increment'
    });
  });
  
  // Handle counter decrement
  socket.on('decrement', ({ sessionId }) => {
    const session = sessions.get(sessionId);
    
    if (!session) {
      socket.emit('session-not-found');
      return;
    }
    
    globalCounter--;
    session.lastActivity = new Date();
    
    console.log(`Global counter decremented to ${globalCounter} by session ${sessionId}`);
    
    // Broadcast to ALL connected clients
    io.emit('counter-update', {
      value: globalCounter,
      action: 'decrement'
    });
  });
  
  // Go Game Socket Handlers
  
  // Create new Go session (use global session)
  socket.on('create-go-session', () => {
    let gameState = goSessions.get(GLOBAL_GO_SESSION);
    
    // Create global session if it doesn't exist
    if (!gameState) {
      gameState = {
        board: Array(9).fill().map(() => Array(9).fill(null)),
        currentPlayer: 'black',
        players: { white: null, black: null },
        createdAt: new Date(),
        lastActivity: new Date()
      };
      goSessions.set(GLOBAL_GO_SESSION, gameState);
      console.log(`Global Go session created: ${GLOBAL_GO_SESSION}`);
    }
    
    socket.join(GLOBAL_GO_SESSION);
    
    console.log(`Desktop joined global Go session: ${GLOBAL_GO_SESSION}`);
    socket.emit('go-session-created', { sessionId: GLOBAL_GO_SESSION, gameState });
  });
  
  // Join Go session as specific color
  socket.on('join-go-session', ({ sessionId, color }) => {
    const gameState = goSessions.get(sessionId);
    
    if (!gameState) {
      socket.emit('go-session-not-found');
      return;
    }
    
    socket.join(sessionId);
    socket.goSessionId = sessionId;
    
    // Handle observer (desktop) connections
    if (color === 'observer') {
      socket.playerColor = 'observer';
      console.log(`Observer joined Go session ${sessionId}`);
      socket.emit('go-session-joined', { sessionId, gameState });
      return;
    }
    
    // Check if color is already taken for actual players
    if (gameState.players[color] !== null) {
      socket.emit('go-color-taken');
      return;
    }
    
    // Add player to game
    gameState.players[color] = {
      id: uuidv4().substring(0, 8),
      socketId: socket.id,
      color: color
    };
    gameState.lastActivity = new Date();
    
    socket.playerColor = color;
    
    console.log(`Player joined Go session ${sessionId} as ${color}`);
    
    socket.emit('go-session-joined', { sessionId, gameState });
    
    // Notify all clients in session (including observers)
    io.to(sessionId).emit('go-player-joined', {
      players: gameState.players
    });
  });
  
  // Handle Go move
  socket.on('go-make-move', ({ sessionId, row, col, color }) => {
    const gameState = goSessions.get(sessionId);
    
    if (!gameState) {
      socket.emit('go-session-not-found');
      return;
    }
    
    // Validate move
    if (gameState.currentPlayer !== color) {
      socket.emit('go-invalid-move', { reason: 'Not your turn' });
      return;
    }
    
    if (gameState.board[row][col] !== null) {
      socket.emit('go-invalid-move', { reason: 'Position already occupied' });
      return;
    }
    
    if (row < 0 || row >= 9 || col < 0 || col >= 9) {
      socket.emit('go-invalid-move', { reason: 'Invalid position' });
      return;
    }
    
    // Create a copy of the board to test the move
    const testBoard = gameState.board.map(row => [...row]);
    testBoard[row][col] = color;
    
    // Check if this move would capture opponent stones
    const capturedStones = checkAndRemoveCaptures(testBoard, row, col, color);
    
    // Check if the placed stone or its group would have liberties after captures
    const placedStoneGroup = getGroup(testBoard, row, col, color);
    const wouldHaveLiberties = hasLiberties(testBoard, placedStoneGroup);
    
    // If the move doesn't capture anything AND the placed stone has no liberties, it's suicide
    if (capturedStones.length === 0 && !wouldHaveLiberties) {
      socket.emit('go-invalid-move', { reason: 'Invalid move: suicide is not allowed' });
      return;
    }
    
    // Make the actual move
    gameState.board[row][col] = color;
    
    // Apply captures to the real board
    const actualCapturedStones = checkAndRemoveCaptures(gameState.board, row, col, color);
    
    gameState.currentPlayer = color === 'black' ? 'white' : 'black';
    gameState.lastActivity = new Date();
    
    console.log(`Go move: ${color} played at ${row},${col} in session ${sessionId}`);
    if (actualCapturedStones.length > 0) {
      console.log(`Captured ${actualCapturedStones.length} stones:`, actualCapturedStones);
    }
    
    // Broadcast game update to all clients in session (players + observers)
    io.to(sessionId).emit('go-game-update', { gameState });
    
    console.log(`Broadcasting game update to session ${sessionId}:`, {
      move: { row, col, color },
      captured: actualCapturedStones,
      currentPlayer: gameState.currentPlayer,
      boardState: gameState.board.map(row => row.map(cell => cell || '.')).join('\n').replace(/,/g, '')
    });
  });
  
  // Handle color switching
  socket.on('go-switch-color', ({ sessionId, newColor }) => {
    console.log(`Received go-switch-color: ${sessionId}, ${newColor} from ${socket.id}`);
    console.log(`Available sessions:`, Array.from(goSessions.keys()));
    const gameState = goSessions.get(sessionId);
    
    if (!gameState) {
      console.log(`Session not found: ${sessionId}, available: ${Array.from(goSessions.keys())}`);
      socket.emit('go-session-not-found');
      return;
    }
    
    // Remove player from current color
    if (socket.playerColor && socket.playerColor !== 'observer') {
      gameState.players[socket.playerColor] = null;
    }
    
    // Add player to new color (replace existing player if any)
    gameState.players[newColor] = {
      id: uuidv4().substring(0, 8),
      socketId: socket.id,
      color: newColor
    };
    
    socket.playerColor = newColor;
    gameState.lastActivity = new Date();
    
    console.log(`Player switched to ${newColor} in session ${sessionId}`);
    console.log(`Updated players:`, gameState.players);
    
    // Notify the player of successful switch
    socket.emit('go-color-switched', { newColor });
    console.log(`Sent go-color-switched to ${socket.id}:`, { newColor });
    
    // Notify all clients in session about player changes
    io.to(sessionId).emit('go-player-joined', {
      players: gameState.players
    });
  });
  
  // Handle game reset
  socket.on('go-reset-game', ({ sessionId }) => {
    console.log(`Received go-reset-game: ${sessionId} from ${socket.id}`);
    const gameState = goSessions.get(sessionId);
    
    if (!gameState) {
      console.log(`Session not found for reset: ${sessionId}`);
      socket.emit('go-session-not-found');
      return;
    }
    
    // Reset the board
    gameState.board = Array(9).fill().map(() => Array(9).fill(null));
    gameState.currentPlayer = 'black';
    gameState.lastActivity = new Date();
    
    console.log(`Game reset in session ${sessionId}`);
    
    // Broadcast reset to all clients in session
    io.to(sessionId).emit('go-game-reset', { gameState });
    io.to(sessionId).emit('go-game-update', { gameState });
  });

  // Drawing Canvas Socket Handlers
  
  // Create new Drawing session (use global session)
  socket.on('create-drawing-session', () => {
    let drawingState = drawingSessions.get(GLOBAL_DRAWING_SESSION);
    
    // Create global session if it doesn't exist
    if (!drawingState) {
      drawingState = {
        strokes: [],
        players: new Map(),
        createdAt: new Date(),
        lastActivity: new Date()
      };
      drawingSessions.set(GLOBAL_DRAWING_SESSION, drawingState);
      console.log(`Global Drawing session created: ${GLOBAL_DRAWING_SESSION}`);
    }
    
    socket.join(GLOBAL_DRAWING_SESSION);
    
    console.log(`Desktop joined global Drawing session: ${GLOBAL_DRAWING_SESSION}`);
    socket.emit('drawing-session-created', { 
      sessionId: GLOBAL_DRAWING_SESSION, 
      drawingState: drawingState.strokes 
    });
  });
  
  // Join Drawing session
  socket.on('join-drawing-session', ({ sessionId }) => {
    const drawingState = drawingSessions.get(sessionId);
    
    if (!drawingState) {
      socket.emit('drawing-session-not-found');
      return;
    }
    
    socket.join(sessionId);
    socket.drawingSessionId = sessionId;
    
    // Add player to session
    drawingState.players.set(socket.id, {
      id: socket.id,
      joinedAt: new Date()
    });
    drawingState.lastActivity = new Date();
    
    console.log(`Player joined Drawing session ${sessionId}`);
    
    socket.emit('drawing-session-joined', { 
      sessionId, 
      drawingState: drawingState.strokes,
      playerCount: drawingState.players.size
    });
    
    // Notify all clients in session about new player
    io.to(sessionId).emit('drawing-player-joined', {
      playerCount: drawingState.players.size
    });
  });
  
  // Handle drawing data
  socket.on('drawing-data', ({ sessionId, fromX, fromY, toX, toY, color, lineWidth }) => {
    const drawingState = drawingSessions.get(sessionId);
    
    if (!drawingState) {
      socket.emit('drawing-session-not-found');
      return;
    }
    
    // Add stroke to drawing state
    const stroke = {
      fromX,
      fromY,
      toX,
      toY,
      color,
      lineWidth,
      timestamp: Date.now()
    };
    
    drawingState.strokes.push(stroke);
    drawingState.lastActivity = new Date();
    
    // Broadcast drawing update to all clients in session
    socket.to(sessionId).emit('drawing-update', { 
      drawingState: drawingState.strokes 
    });
    
    console.log(`Drawing stroke added to session ${sessionId}: ${color} from (${fromX},${fromY}) to (${toX},${toY})`);
  });
  
  // Handle canvas clear
  socket.on('clear-drawing-canvas', ({ sessionId }) => {
    console.log(`Received clear-drawing-canvas: ${sessionId} from ${socket.id}`);
    const drawingState = drawingSessions.get(sessionId);
    
    if (!drawingState) {
      console.log(`Drawing session not found for clear: ${sessionId}`);
      socket.emit('drawing-session-not-found');
      return;
    }
    
    // Clear all strokes
    drawingState.strokes = [];
    drawingState.lastActivity = new Date();
    
    console.log(`Canvas cleared in session ${sessionId}`);
    
    // Broadcast clear to all clients in session
    io.to(sessionId).emit('drawing-cleared', { drawingState: drawingState.strokes });
  });
  
  // Handle disconnection
  socket.on('disconnect', () => {
    console.log('Client disconnected:', socket.id);
    
    // Handle regular session disconnection
    if (socket.sessionId) {
      const session = sessions.get(socket.sessionId);
      
      if (session) {
        // Remove device from session
        session.devices = session.devices.filter(device => device.socketId !== socket.id);
        session.lastActivity = new Date();
        
        console.log(`Device ${socket.deviceId} left session ${socket.sessionId}`);
        
        // Notify remaining clients
        io.to(socket.sessionId).emit('device-disconnected', {
          devices: session.devices
        });
        
        // Clean up empty sessions
        if (session.devices.length === 0) {
          console.log(`Session ${socket.sessionId} is empty, will be cleaned up later`);
        }
      }
    }
    
    // Handle Go session disconnection
    if (socket.goSessionId) {
      const gameState = goSessions.get(socket.goSessionId);
      
      if (gameState && socket.playerColor) {
        // Remove player from game
        gameState.players[socket.playerColor] = null;
        gameState.lastActivity = new Date();
        
        console.log(`Player ${socket.playerColor} left Go session ${socket.goSessionId}`);
        
        // Notify remaining players
        io.to(socket.goSessionId).emit('go-player-left', {
          players: gameState.players
        });
        
        // Clean up empty Go sessions
        const hasPlayers = Object.values(gameState.players).some(p => p !== null);
        if (!hasPlayers) {
          console.log(`Go session ${socket.goSessionId} is empty, will be cleaned up later`);
        }
      }
    }
    
    // Handle Drawing session disconnection
    if (socket.drawingSessionId) {
      const drawingState = drawingSessions.get(socket.drawingSessionId);
      
      if (drawingState) {
        // Remove player from drawing session
        drawingState.players.delete(socket.id);
        drawingState.lastActivity = new Date();
        
        console.log(`Player left Drawing session ${socket.drawingSessionId}`);
        
        // Notify remaining players
        io.to(socket.drawingSessionId).emit('drawing-player-left', {
          playerCount: drawingState.players.size
        });
        
        // Clean up empty Drawing sessions
        if (drawingState.players.size === 0) {
          console.log(`Drawing session ${socket.drawingSessionId} is empty, will be cleaned up later`);
        }
      }
    }
  });
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
    activeSessions: sessions.size,
    activeGoSessions: goSessions.size,
    activeDrawingSessions: drawingSessions.size,
    totalDevices: Array.from(sessions.values()).reduce((sum, session) => sum + session.devices.length, 0),
    totalGoPlayers: Array.from(goSessions.values()).reduce((sum, game) => 
      sum + Object.values(game.players).filter(p => p !== null).length, 0),
    totalDrawingPlayers: Array.from(drawingSessions.values()).reduce((sum, drawing) => 
      sum + drawing.players.size, 0),
    globalCounter: globalCounter
  });
});

// Session info endpoint (for debugging)
app.get('/sessions', (req, res) => {
  const sessionList = Array.from(sessions.entries()).map(([id, session]) => ({
    id,
    deviceCount: session.devices.length,
    createdAt: session.createdAt,
    lastActivity: session.lastActivity
  }));
  
  res.json({
    globalCounter: globalCounter,
    sessions: sessionList
  });
});

const PORT = process.env.PORT || 3001;

server.listen(PORT, () => {
  console.log(`Lab backend server running on port ${PORT}`);
  console.log(`Environment: ${process.env.NODE_ENV || 'development'}`);
}); 