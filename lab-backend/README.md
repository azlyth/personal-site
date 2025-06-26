# Lab Backend

Backend service for interactive experiments on the personal site lab section.

## Features

- Real-time WebSocket communication using Socket.IO
- Session-based experiment management
- QR code pairing for mobile devices
- In-memory session storage with automatic cleanup
- Health check endpoints
- CORS configuration for cross-origin requests

## Local Development

### Prerequisites

- Node.js 18.x
- npm

### Setup

```bash
# Install dependencies
npm install

# Start development server
npm start
```

The server will run on `http://localhost:3001`.

### Available Endpoints

- `GET /health` - Health check with session statistics
- `GET /sessions` - List all active sessions (debugging)
- WebSocket connections on the root path

## Docker

### Build Image

```bash
docker build -t lab-backend .
```

### Run Container

```bash
docker run -p 3001:3001 lab-backend
```

## Deployment on Render

### Setup

1. Create new Web Service on Render
2. Connect to this repository
3. Set the following configuration:
   - **Root Directory**: `lab-backend`
   - **Build Command**: `npm install`
   - **Start Command**: `npm start`
   - **Docker**: Use Dockerfile (optional)

### Environment Variables

No environment variables required for basic operation. The service uses:
- `PORT` - Automatically set by Render (defaults to 3001 locally)
- `NODE_ENV` - Set to "production" in production

### CORS Configuration

The backend is configured to accept requests from:
- `http://localhost:1111` (local Zola development)
- `https://peter.direct` (production site)
- Any subdomain of `peter.direct`

## Session Management

- Sessions are stored in memory
- Each session has a unique 8-character ID
- Sessions auto-expire after 24 hours of inactivity
- Supports multiple devices per session
- Real-time synchronization between all connected devices

## API Events

### Client to Server

- `create-session` - Create new experiment session
- `join-session` - Join existing session with session ID
- `increment` - Increment session counter
- `decrement` - Decrement session counter

### Server to Client

- `session-created` - Session created successfully
- `session-joined` - Successfully joined session
- `session-not-found` - Session ID not found
- `counter-update` - Counter value changed
- `device-connected` - New device joined session
- `device-disconnected` - Device left session

## Architecture

```
┌─────────────────┐    WebSocket    ┌─────────────────┐
│   Desktop Web   │◄──────────────► │                 │
│   (QR Display)  │                 │   Lab Backend   │
└─────────────────┘                 │   (Node.js +    │
                                    │   Socket.IO)    │
┌─────────────────┐    WebSocket    │                 │
│   Mobile Web    │◄──────────────► │                 │
│  (Controller)   │                 └─────────────────┘
└─────────────────┘
```

## Monitoring

The `/health` endpoint provides information about:
- Service status
- Number of active sessions
- Total connected devices
- Current timestamp

Example response:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00.000Z",
  "activeSessions": 3,
  "totalDevices": 7
}
``` 