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
  
  // Handle disconnection
  socket.on('disconnect', () => {
    console.log('Client disconnected:', socket.id);
    
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
  });
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
    activeSessions: sessions.size,
    totalDevices: Array.from(sessions.values()).reduce((sum, session) => sum + session.devices.length, 0),
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