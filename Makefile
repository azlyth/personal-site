.PHONY: help dev prod build logs clean stop check check-links check-fit open-local open-gh deploy-up deploy-down deploy-restart deploy-ps install uninstall upload-image upload-video build-site publish-site editor-install editor-restart editor-logs

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
	@echo "  $(GREEN)make dev$(RESET)     - Start site + lab backend (ports 1111 & 3001)"
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
	@echo "$(CYAN)Self-hosted deploy (cloudy.nyc, via http-routing):$(RESET)"
	@echo "  $(GREEN)make deploy-up$(RESET)      - Build + start the stack detached"
	@echo "  $(GREEN)make deploy-restart$(RESET) - Force-recreate after a code/config change"
	@echo "  $(GREEN)make deploy-down$(RESET)    - Stop the stack"
	@echo "  $(GREEN)make deploy-ps$(RESET)      - Container status"
	@echo "  $(GREEN)make install$(RESET)        - Install + enable the boot systemd unit (sudo)"
	@echo "  $(GREEN)make uninstall$(RESET)      - Disable + remove the boot systemd unit (sudo)"
	@echo ""
	@echo "$(CYAN)Blog images (img.cloudy.nyc, public + Cloudflare-cached, not served from the Pi):$(RESET)"
	@echo "  $(GREEN)make upload-image SLUG=<post-slug> NAME=<name> FILE=<path>$(RESET)"
	@echo "      Strips EXIF, resizes, re-encodes as JPEG, uploads, prints the URL."
	@echo "  $(GREEN)make upload-video SLUG=<post-slug> NAME=<name> FILE=<path> [LOOP=<seconds>]$(RESET)"
	@echo "      Re-encodes as muted H.264, scales to 640px, uploads, prints the URL."
	@echo "      LOOP loops+trims to an exact frame-accurate duration (for synced loops)."
	@echo ""
	@echo "$(YELLOW)💡 Tip: Run 'make dev' to start both site and experiments!$(RESET)"

# --- self-hosted deploy (cloudy.nyc) ---
deploy-up:
	docker compose up -d --build

deploy-restart:
	docker compose up -d --build --force-recreate

deploy-down:
	docker compose down

deploy-ps:
	docker compose ps

build-site:
	./scripts/build-site.sh

publish-site:
	./scripts/publish-site.sh

SERVICE  := personal-site.service
UNIT_SRC := systemd/$(SERVICE)
UNIT_DST := /etc/systemd/system/$(SERVICE)

install:
	sudo cp $(UNIT_SRC) $(UNIT_DST)
	sudo systemctl daemon-reload
	sudo systemctl enable --now $(SERVICE)

uninstall:
	-sudo systemctl disable --now $(SERVICE)
	-sudo rm -f $(UNIT_DST)
	sudo systemctl daemon-reload

upload-image:
	python3 scripts/upload-image.py "$(SLUG)" "$(NAME)" "$(FILE)"

upload-video:
	python3 scripts/upload-video.py "$(SLUG)" "$(NAME)" "$(FILE)" $(LOOP)

# Development mode - runs zola serve with live reloading + lab backend
dev:
	HOST_UID=$(shell id -u) HOST_GID=$(shell id -g) docker compose -f compose.dev.yaml up --build

# Open local development site
open-local:
	@echo "$(CYAN)Opening local development site...$(RESET)"
	open http://localhost:1111

# Open GitHub Pages site
open-gh:
	@echo "$(CYAN)Opening site at peter.direct...$(RESET)"
	open https://peter.direct

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

# Both checks always run, and `check` fails if EITHER did.
#
# They are not chained with make's usual prerequisite ordering on purpose:
# check-links has exited non-zero for years (see below), which would abort the
# target before check-fit ever ran -- a check that can never execute is worse
# than no check at all.
check:
	@rc=0; \
	$(MAKE) --no-print-directory check-links || rc=1; \
	$(MAKE) --no-print-directory check-fit || rc=1; \
	exit $$rc

# Does the site build, and do its links resolve.
# ⚠ This currently FAILS, and has since long before it was split out: `zola
# check` validates EXTERNAL links too, and six of them in posts from 2016-2017
# point at sites that have since died (ptrvldz.me, redub.audio, a pulled Play
# Store listing). The failure is real and the links are genuinely dead; fixing
# them means editing old posts, which is a content decision, not a build one.
check-links:
	docker compose -f compose.dev.yaml run --rm zola check

# The root font size scales up on big displays but stops before a page grows
# taller than the window, using a constant in base.html that encodes today's
# home page height. This catches that constant going stale.
#
# It needs a SERVED site and defaults to serving the WORKING TREE, starting and
# stopping a dev server itself if one isn't already up -- checking the live site
# would only tell you about the last thing you published. To check that instead:
#   make check-fit FIT_URL=https://cloudy.nyc
FIT_URL ?=
check-fit:
	@./scripts/check-fit.sh $(FIT_URL)

EDITOR_SERVICE := blog-editor.service

editor-install:
	sudo cp systemd/$(EDITOR_SERVICE) /etc/systemd/system/$(EDITOR_SERVICE)
	sudo systemctl daemon-reload
	sudo systemctl enable --now $(EDITOR_SERVICE)

editor-restart:
	sudo systemctl restart $(EDITOR_SERVICE)

editor-logs:
	journalctl -u $(EDITOR_SERVICE) -f



 