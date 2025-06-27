const { createClient } = require('redis');

class PersistenceLayer {
  constructor() {
    this.client = null;
    this.isConnected = false;
  }

  async connect() {
    try {
      const redisUrl = process.env.REDIS_URL || 'redis://localhost:6379';
      console.log(`Connecting to Redis at ${redisUrl}...`);
      
      this.client = createClient({
        url: redisUrl,
        socket: {
          connectTimeout: 60000,
          lazyConnect: true,
        }
      });

      this.client.on('error', (err) => {
        console.error('Redis Client Error:', err);
        this.isConnected = false;
      });

      this.client.on('connect', () => {
        console.log('Redis client connected');
        this.isConnected = true;
      });

      this.client.on('ready', () => {
        console.log('Redis client ready');
        this.isConnected = true;
      });

      this.client.on('end', () => {
        console.log('Redis client disconnected');
        this.isConnected = false;
      });

      await this.client.connect();
      console.log('Redis connection established');
      return true;
    } catch (error) {
      console.error('Failed to connect to Redis:', error);
      this.isConnected = false;
      return false;
    }
  }

  async disconnect() {
    if (this.client) {
      await this.client.disconnect();
      this.isConnected = false;
    }
  }

  // Generic key-value operations
  async set(key, value, ttl = null) {
    if (!this.isConnected) return false;
    try {
      const data = JSON.stringify(value);
      if (ttl) {
        await this.client.setEx(key, ttl, data);
      } else {
        await this.client.set(key, data);
      }
      return true;
    } catch (error) {
      console.error(`Error setting key ${key}:`, error);
      return false;
    }
  }

  async get(key) {
    if (!this.isConnected) return null;
    try {
      const data = await this.client.get(key);
      return data ? JSON.parse(data) : null;
    } catch (error) {
      console.error(`Error getting key ${key}:`, error);
      return null;
    }
  }

  async delete(key) {
    if (!this.isConnected) return false;
    try {
      await this.client.del(key);
      return true;
    } catch (error) {
      console.error(`Error deleting key ${key}:`, error);
      return false;
    }
  }

  async exists(key) {
    if (!this.isConnected) return false;
    try {
      const result = await this.client.exists(key);
      return result === 1;
    } catch (error) {
      console.error(`Error checking existence of key ${key}:`, error);
      return false;
    }
  }

  // Experiment-specific persistence methods
  
  // Global counter
  async saveGlobalCounter(counter) {
    return await this.set('global:counter', counter);
  }

  async loadGlobalCounter() {
    const counter = await this.get('global:counter');
    return counter !== null ? counter : 0;
  }

  // Regular sessions
  async saveSession(sessionId, session) {
    return await this.set(`session:${sessionId}`, session, 86400); // 24 hours TTL
  }

  async loadSession(sessionId) {
    return await this.get(`session:${sessionId}`);
  }

  async deleteSession(sessionId) {
    return await this.delete(`session:${sessionId}`);
  }

  async getAllSessions() {
    if (!this.isConnected) return new Map();
    try {
      const keys = await this.client.keys('session:*');
      const sessions = new Map();
      
      if (keys.length > 0) {
        const values = await this.client.mGet(keys);
        keys.forEach((key, index) => {
          if (values[index]) {
            const sessionId = key.replace('session:', '');
            sessions.set(sessionId, JSON.parse(values[index]));
          }
        });
      }
      
      return sessions;
    } catch (error) {
      console.error('Error loading all sessions:', error);
      return new Map();
    }
  }

  // Go sessions
  async saveGoSession(sessionId, gameState) {
    return await this.set(`go:${sessionId}`, gameState, 86400); // 24 hours TTL
  }

  async loadGoSession(sessionId) {
    return await this.get(`go:${sessionId}`);
  }

  async deleteGoSession(sessionId) {
    return await this.delete(`go:${sessionId}`);
  }

  async getAllGoSessions() {
    if (!this.isConnected) return new Map();
    try {
      const keys = await this.client.keys('go:*');
      const sessions = new Map();
      
      if (keys.length > 0) {
        const values = await this.client.mGet(keys);
        keys.forEach((key, index) => {
          if (values[index]) {
            const sessionId = key.replace('go:', '');
            sessions.set(sessionId, JSON.parse(values[index]));
          }
        });
      }
      
      return sessions;
    } catch (error) {
      console.error('Error loading all go sessions:', error);
      return new Map();
    }
  }

  // Drawing sessions
  async saveDrawingSession(sessionId, drawingState) {
    return await this.set(`drawing:${sessionId}`, drawingState, 86400); // 24 hours TTL
  }

  async loadDrawingSession(sessionId) {
    return await this.get(`drawing:${sessionId}`);
  }

  async deleteDrawingSession(sessionId) {
    return await this.delete(`drawing:${sessionId}`);
  }

  async getAllDrawingSessions() {
    if (!this.isConnected) return new Map();
    try {
      const keys = await this.client.keys('drawing:*');
      const sessions = new Map();
      
      if (keys.length > 0) {
        const values = await this.client.mGet(keys);
        keys.forEach((key, index) => {
          if (values[index]) {
            const sessionId = key.replace('drawing:', '');
            const data = JSON.parse(values[index]);
            // Convert players array back to Map if needed
            if (data.players && Array.isArray(data.players)) {
              data.players = new Map(data.players);
            }
            sessions.set(sessionId, data);
          }
        });
      }
      
      return sessions;
    } catch (error) {
      console.error('Error loading all drawing sessions:', error);
      return new Map();
    }
  }

  // Helper method to convert Maps to arrays for JSON serialization
  serializeDrawingState(drawingState) {
    return {
      ...drawingState,
      players: Array.from(drawingState.players.entries())
    };
  }

  // Health check
  async isHealthy() {
    if (!this.isConnected) return false;
    try {
      await this.client.ping();
      return true;
    } catch (error) {
      console.error('Redis health check failed:', error);
      return false;
    }
  }
}

module.exports = PersistenceLayer; 