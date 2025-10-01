# Makefile
# Build and run local stack for Pyronear

SHELL := /bin/sh
COMPOSE := docker compose

.PHONY: help init build build-external build-all run-backend run-engine run-tools run run-all stop ps logs test

help:
	@echo "Targets:"
	@echo "  init            Create .env from .env.test if missing"
	@echo "  build           Build local images in this repo"
	@echo "  build-external  Build images in sibling repos"
	@echo "  build-all       Build local and external images"
	@echo "  run-backend     Start base services without profiles"
	@echo "  run-engine      Start engine profile only"
	@echo "  run-tools       Start tools profile only"
	@echo "  run             Start everything except engine"
	@echo "  run-all         Start everything including engine"
	@echo "  stop            Stop and remove all services and volumes"
	@echo "  ps              Show compose status"
	@echo "  logs            Follow logs"
	@echo "  test            Run pytest"

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
	docker build -f containers/reolinkdev1/Dockerfile -t pyronear/reolinkdev1:latest containers/reolinkdev1/
	docker build -f containers/reolinkdev2/Dockerfile -t pyronear/reolinkdev2:latest containers/reolinkdev2/
	docker build -f containers/notebooks/Dockerfile -t pyronear/notebooks:latest containers/notebooks/

# -------------------------------------------------------------------
# Build images from sibling repositories
# -------------------------------------------------------------------

build-external:
	cd ../pyro-api && make build
	cd ../pyro-engine && make build-lib
	cd ../pyro-engine && make build-app
	cd ../pyro-platform && make build

build-all: build build-external

# -------------------------------------------------------------------
# Run targets
# -------------------------------------------------------------------

run-backend:
	$(COMPOSE) up -d

run-engine:
	$(COMPOSE) --profile engine up -d

run-tools:
	$(COMPOSE) --profile tools up -d

# Start everything except the engine: base services plus front + tools
run:
	$(COMPOSE) --profile front --profile tools up -d

# Start everything including the engine
run-all:
	$(COMPOSE) --profile front --profile tools --profile engine up -d

stop:
	$(COMPOSE) --profile front --profile engine --profile tools down -v

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=200

# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

test:
	pytest -s tests/*
