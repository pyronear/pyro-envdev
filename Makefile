# Makefile
# Build and run the local stack for Pyronear

help:
	@echo "Targets:"
	@echo "  init                Create .env from .env.test if missing"
	@echo "  build               Build local images in this repo"
	@echo "  build-external      Build images in sibling repos"
	@echo "  build-all           Build local and external images"
	@echo "  run-backend         Start base services only"
	@echo "  run-engine          Start base services plus engine profile"
	@echo "  run-tools-and-engine  Start base services plus tools and engine profiles"
	@echo "  run-tools           Start base services plus tools profile"
	@echo "  run                 Start base services plus front and tools profiles"
	@echo "  run-temporal        Same as run (front + tools) plus temporal model API"
	@echo "  stop-temporal       Stop only the temporal model API"
	@echo "  stop-engine         Stop only engine services (engine + pyro_camera_api)"
	@echo "  restart-engine      Restart engine services without re-running init_script"
	@echo "  stop                Stop and remove all services and volumes"
	@echo "  ps                  Show compose status"
	@echo "  logs                Follow logs"
	@echo "  test                Run pytest"

# -------------------------------------------------------------------
# Init
# -------------------------------------------------------------------

init:
	@test -f .env || cp .env.test .env

# -------------------------------------------------------------------
# Build images in this repo
# -------------------------------------------------------------------

build:
	docker build -f containers/init_script/Dockerfile -t pyronear/pyro-api-init:latest containers/init_script/
	docker build -f containers/notebooks/Dockerfile -t pyronear/notebooks:latest containers/notebooks/

# -------------------------------------------------------------------
# Build images from sibling repositories
# -------------------------------------------------------------------

build-external:
	cd ../pyro-api && make build
	cd ../pyro-engine && make build-lib
	cd ../pyro-engine && make build-app

build-all: build build-external

# -------------------------------------------------------------------
# Run targets
# -------------------------------------------------------------------

# Base services: db, minio, pyro_api, init_script
run-backend:
	docker compose up -d

# Engine profile adds engine + pyro_camera_api
run-engine:
	docker compose --profile engine up -d

# Tools + engine (tools must be up first so the API is ready when engine starts)
run-tools-and-engine:
	$(MAKE) run-tools
	$(MAKE) run-engine

# Tools profile adds notebooks, db-ui
run-tools:
	docker compose --profile tools up -d

# Front profile adds frontend, here we also include tools
run:
	docker compose --profile front --profile tools up -d

# Same as `run` (front + tools) plus the temporal model API, with validation + auth enabled.
# Points pyro-api at the temporal service and shares a token with both.
# Override either: TEMPORAL_API_URL=... TEMPORAL_API_TOKEN=... make run-temporal
TEMPORAL_API_URL ?= http://temporal_model_api:8000
TEMPORAL_API_TOKEN ?= dev-temporal-token
run-temporal:
	TEMPORAL_API_URL=$(TEMPORAL_API_URL) TEMPORAL_API_TOKEN=$(TEMPORAL_API_TOKEN) docker compose --profile front --profile tools --profile temporal up -d

stop-temporal:
	docker compose --profile temporal stop temporal_model_api

stop-engine:
	docker compose --profile engine stop engine pyro_camera_api

restart-engine: stop-engine
	docker compose --profile engine up -d engine pyro_camera_api --no-deps

stop:
	docker compose --profile front --profile engine --profile tools --profile temporal down -v

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=200

# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

test:
	pytest -s tests/*
