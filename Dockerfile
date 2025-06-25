# Build stage
FROM alpine:3.20 as builder

# Install Zola from Alpine packages
RUN apk add --no-cache zola

# Copy the site source
COPY . /project
WORKDIR /project

# Build the static site
RUN zola build

# Production stage - serve with nginx
FROM nginx:alpine

# Copy the built static files from builder stage
COPY --from=builder /project/public /usr/share/nginx/html

# Copy custom nginx config if needed
# COPY nginx.conf /etc/nginx/nginx.conf

# Expose port 80
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"] 