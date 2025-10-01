# Makefile
# Build and run the local stack for Pyronear

help:
	@echo "Targets:"
	@echo "  init            Create .env from .env.test if missing"
	@echo "  build           Build local images in this repo"
	@echo "  build-external  Build images in sibling repos"
	@echo "  build-all       Build local and external images"
	@echo "  run-backend     Start base services only"
	@echo "  run-engine      Start base services plus engine profile"
	@echo "  run-tools       Start base services plus tools profile"
	@echo "  run             Start base services plus front and tools profiles"
	@echo "  run-all         Start base services plus front tools and engine profiles"
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

# Base services: db, minio, pyro_api, init_script
run-backend:
	docker compose up -d

# Engine profile adds pyro_engine, reolinkdev1, reolinkdev2
run-engine:
	docker compose --profile engine up -d

# Tools profile adds notebooks, db-ui
run-tools:
	docker compose --profile tools up -d

# Front profile adds frontend, here we also include tools
run:
	docker compose --profile front --profile tools up -d

# Everything including engine
run-all:
	docker compose --profile front --profile tools --profile engine up -d

stop:
	docker compose --profile front --profile engine --profile tools down -v

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=200

# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

test:
	pytest -s tests/*
