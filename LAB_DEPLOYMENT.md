# Lab Deployment Guide

This guide explains how to deploy the lab backend to Render and update the frontend to use the production backend.

## Quick Start

1. **Test Locally**:
   ```bash
   make lab-dev
   ```
   This starts both the Zola site (localhost:1111) and lab backend (localhost:3001).

2. **Deploy Backend to Render**:
   - Go to [Render Dashboard](https://dashboard.render.com/)
   - Create new Web Service
   - Connect your GitHub repository
   - Configure the service:
     - **Name**: `peter-lab-backend` (or similar)
     - **Root Directory**: `lab-backend`
     - **Build Command**: `npm install`
     - **Start Command**: `npm start`
     - **Auto-Deploy**: Yes

3. **Update Frontend Configuration**:
   - Once deployed, Render will give you a URL like `https://peter-lab-backend.onrender.com`
   - Update the `BACKEND_URL` in `content/lab/experiment-1.md`:
   ```javascript
   const BACKEND_URL = window.location.hostname === 'localhost' 
       ? 'http://localhost:3001' 
       : 'https://peter-lab-backend.onrender.com'; // Update this URL
   ```

4. **Deploy Site**:
   - Commit and push changes to GitHub
   - GitHub Pages will automatically rebuild and deploy

## Testing the Deployment

1. Visit `https://peter.direct/lab/experiment-1/`
2. You should see a QR code generated
3. Scan the QR code with your phone
4. The phone should connect and show increment/decrement buttons
5. Pressing buttons on phone should update the counter on desktop

## Render Configuration Details

### Service Settings
- **Environment**: Node.js
- **Plan**: Free tier is sufficient for testing
- **Auto-Deploy**: Enable for automatic deployments
- **Health Check Path**: `/health`

### Build Settings
- **Build Command**: `npm install`
- **Start Command**: `npm start`
- **Node Version**: 18.x (specified in package.json)

### Environment Variables
No custom environment variables needed. Render automatically sets `PORT`.

## Monitoring

### Health Check
Visit your Render service URL at `/health` to see:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00.000Z",
  "activeSessions": 0,
  "totalDevices": 0
}
```

### Logs
Check logs in Render dashboard or use the logs URL provided by Render.

### Session Info
Visit `/sessions` to see active sessions (useful for debugging).

## Troubleshooting

### Common Issues

1. **CORS Errors**:
   - Ensure the frontend domain is added to CORS origins in `server.js`
   - Add any custom domains to the `corsOptions.origin` array

2. **WebSocket Connection Failed**:
   - Check that the backend URL is correct in the frontend
   - Verify the backend is running and accessible

3. **QR Code Not Generating**:
   - Check browser console for errors
   - Ensure QR code library is loading from CDN

4. **Mobile Not Connecting**:
   - Verify the session parameter is in the URL
   - Check that the session hasn't expired

### Local Testing

To test locally with the exact same setup as production:

```bash
# Build and run backend with Docker
make lab-build
docker run -p 3001:3001 lab-backend

# Start site development server
make dev
```

## Next Steps

Once the basic counter experiment is working, you can:

1. **Add More Experiments**:
   - Create `content/lab/experiment-2.md`
   - Add new socket events in `server.js`
   - Update the lab index page

2. **Enhance Features**:
   - Add user names for devices
   - Implement different game modes
   - Add sound effects or animations
   - Store high scores

3. **Scale Up**:
   - Add Redis for session persistence
   - Implement session clustering
   - Add rate limiting
   - Monitor with logging services

## Cost Considerations

- **Render Free Tier**: Sufficient for initial testing
- **GitHub Pages**: Free for public repositories
- **Domain**: Already owned (`peter.direct`)

The setup is designed to be cost-effective while allowing for easy scaling as experiments grow in complexity. 