.PHONY: help dev prod build logs clean stop check

# Colors for help output
CYAN = \033[36m
GREEN = \033[32m
YELLOW = \033[33m
RED = \033[31m
RESET = \033[0m
BOLD = \033[1m

# Default target - show help
help:
	@echo "$(BOLD)🚀 Zola Site Commands$(RESET)"
	@echo ""
	@echo "$(CYAN)Development:$(RESET)"
	@echo "  $(GREEN)make dev$(RESET)     - Start development server with live reload (http://localhost:1111)"
	@echo "  $(GREEN)make logs$(RESET)    - Show container logs"
	@echo "  $(GREEN)make stop$(RESET)    - Stop running containers"
	@echo ""
	@echo "$(CYAN)Production:$(RESET)"
	@echo "  $(GREEN)make prod$(RESET)    - Build and serve production site with nginx (http://localhost:8080)"
	@echo "  $(GREEN)make check$(RESET)   - Validate site structure and content"
	@echo ""
	@echo "$(CYAN)Docker:$(RESET)"
	@echo "  $(GREEN)make build$(RESET)   - Build Docker image"
	@echo "  $(GREEN)make clean$(RESET)   - Clean up containers and images"
	@echo ""
	@echo "$(YELLOW)💡 Tip: Run 'make dev' to get started!$(RESET)"

# Development mode - runs zola serve with live reloading
dev:
	DOCKERFILE=Dockerfile.dev PORT=1111 INTERNAL_PORT=1111 VOLUME_MOUNT=.:/project docker compose up --build

# Production mode - builds static site and serves with nginx
prod:
	DOCKERFILE=Dockerfile PORT=8080 INTERNAL_PORT=80 VOLUME_MOUNT=/dev/null:/dev/null docker compose up --build

# Build the Docker image
build:
	docker compose build

# Show logs from the running container
logs:
	docker compose logs -f zola

# Clean up containers and images
clean:
	docker compose down --rmi local

# Stop running containers
stop:
	docker compose down

# Check if site builds successfully
check:
	DOCKERFILE=Dockerfile.dev ZOLA_COMMAND="check" docker compose up --build --abort-on-container-exit 