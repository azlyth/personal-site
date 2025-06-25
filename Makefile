.PHONY: help dev prod build logs clean stop check open-local open-gh

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
	@echo "  $(GREEN)make open-local$(RESET) - Open local development site in browser"
	@echo "  $(GREEN)make open-gh$(RESET)    - Open GitHub Pages site in browser"
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
	docker compose -f compose.dev.yaml up --build

# Open local development site
open-local:
	@echo "$(CYAN)Opening local development site...$(RESET)"
	open http://localhost:1111

# Open GitHub Pages site
open-gh:
	@echo "$(CYAN)Opening GitHub Pages site...$(RESET)"
	open https://azlyth.github.io/personal-site

# Production mode - builds static site and serves with nginx
prod:
	docker compose up --build

# Build the Docker image
build:
	docker compose build

# Show logs from the running container
logs:
	docker compose logs -f web

# Clean up containers and images
clean:
	docker compose down --rmi local
	docker compose -f compose.dev.yaml down --rmi local

# Stop running containers
stop:
	docker compose down
	docker compose -f compose.dev.yaml down

# Check if site builds successfully
check:
	docker compose -f compose.dev.yaml run --rm zola check 