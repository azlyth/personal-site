# Lab Backend Deployment to Render

This guide walks you through deploying the lab backend to Render so it works with your GitHub Pages deployment.

## Prerequisites

1. A Render account (free tier is sufficient)
2. Your GitHub repository connected to Render

## Deployment Steps

### 1. Connect Repository to Render

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click "New +" and select "Web Service"
3. Connect your GitHub account if not already done
4. Select your `personal-site` repository

### 2. Configure the Service

Use these settings when creating the web service:

- **Name**: `peter-lab-backend`
- **Region**: Oregon (US West)
- **Branch**: `main`
- **Runtime**: Node
- **Build Command**: `cd lab-backend && npm install`
- **Start Command**: `cd lab-backend && npm start`
- **Plan**: Free

### 3. Environment Variables

Add these environment variables in the Render dashboard:

- `NODE_ENV`: `production`
- `PORT`: `10000` (Render will override this automatically)

### 4. Advanced Settings

- **Health Check Path**: `/health`
- **Auto-Deploy**: Yes (deploys on every push to main)

## Alternative: Deploy with render.yaml

You can also deploy using the included `render.yaml` file:

1. In your Render dashboard, go to "Blueprint"
2. Click "New Blueprint Instance"
3. Connect your repository
4. Render will automatically detect the `render.yaml` file
5. Review and deploy

## Verification

After deployment:

1. Your service will be available at: `https://peter-lab-backend.onrender.com`
2. Check health status: `https://peter-lab-backend.onrender.com/health`
3. View active sessions: `https://peter-lab-backend.onrender.com/sessions`

## Integration with GitHub Pages

The frontend is already configured to use the Render backend when deployed:

- **Local development**: Uses `http://localhost:3001`
- **Network testing**: Uses `http://192.168.1.191:3001`
- **Production (peter.direct)**: Uses `https://peter-lab-backend.onrender.com`

## CORS Configuration

The backend is pre-configured to accept requests from:

- `https://peter.direct` (your GitHub Pages site)
- All `*.peter.direct` subdomains
- Local development URLs

## Free Tier Limitations

Render's free tier has some limitations:

- **Sleep after inactivity**: Service sleeps after 15 minutes of no requests
- **Cold start**: First request after sleep takes ~30 seconds to wake up
- **Monthly hours**: 750 hours/month (sufficient for most use cases)

## Monitoring

Monitor your deployment:

- **Logs**: Available in Render dashboard
- **Metrics**: CPU, memory usage in dashboard
- **Health checks**: Automatic monitoring of `/health` endpoint

## Troubleshooting

### Service won't start
- Check build logs for npm install errors
- Verify Node.js version compatibility

### CORS errors
- Ensure your domain is in the CORS whitelist
- Check browser developer tools for specific error messages

### WebSocket connection issues
- Render supports WebSockets on all plans
- Check that Socket.IO is connecting to the correct URL

## Next Steps

After successful deployment:

1. Test the experiment at https://peter.direct/lab/experiment-1
2. Verify QR code generation and mobile connectivity
3. Test counter synchronization across devices
4. Monitor performance and logs in Render dashboard

The deployment will automatically update whenever you push changes to the main branch. 