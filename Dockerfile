FROM ghcr.io/getzola/zola:v0.20.0 as builder

# Copy the site source
COPY . /project
WORKDIR /project

# Build the site for production (this will create /project/public)
RUN zola build

# Runtime image - using the same Zola image for serve command
FROM ghcr.io/getzola/zola:v0.20.0

# Copy the source files for development mode
COPY . /project
WORKDIR /project

# Default command (can be overridden via environment variable or docker-compose)
CMD ["zola", "serve", "--interface", "0.0.0.0", "--port", "1111"] 