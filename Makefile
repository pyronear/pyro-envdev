# Makefile
# Build and run the local stack for Pyronear

help:
	@echo "Targets:"
	@echo "  init                Create .env from .env.test if missing"
	@echo "  build               Build local images in this repo"
	@echo "  build-external      Build images in sibling repos"
	@echo "  build-all           Build local and external images"
	@echo "  build-e2e           Build only the local images the e2e needs (no notebooks)"
	@echo "  fetch-scenario      Download scenario images (SCENARIO=smoke-then-clear)"
	@echo "  run-backend         Start base services only"
	@echo "  run-camera          Start only the fake cameras, to work on pyro-engine"
	@echo "  run-engine          Start base services plus engine profile"
	@echo "  run-tools-and-engine  Start base services plus tools and engine profiles"
	@echo "  run-tools           Start base services plus tools profile"
	@echo "  run                 Start base services plus front and tools profiles"
	@echo "  run-temporal        Same as run (front + tools) plus temporal model API"
	@echo "  stop-temporal       Stop only the temporal model API"
	@echo "  stop-engine         Stop only engine services (engine, pyro_camera_api, fake cameras)"
	@echo "  restart-engine      Restart engine services and replay the scenario from the start"
	@echo "  stop                Stop and remove all services and volumes"
	@echo "  ps                  Show compose status"
	@echo "  logs                Follow logs"
	@echo "  test                Run the unit tests"
	@echo "  e2e                 Fresh stack, then the end-to-end tests (SCENARIO=smoke-then-clear), artifacts in e2e-artifacts/"

# -------------------------------------------------------------------
# Init
# -------------------------------------------------------------------

init:
	@test -f .env || cp .env.test .env

# -------------------------------------------------------------------
# Build images in this repo
# -------------------------------------------------------------------

# The fake camera image embeds the default scenario, fetched first.
build: fetch-scenario
	docker build -f containers/init_script/Dockerfile -t pyronear/pyro-api-init:latest containers/init_script/
	docker build -f containers/notebooks/Dockerfile -t pyronear/notebooks:latest containers/notebooks/
	docker build --build-context scenarios=data/scenarios -f containers/fake_camera/Dockerfile -t pyronear/fake-camera:latest containers/fake_camera/

# Same images as `build` minus notebooks, which the e2e does not run.
build-e2e: fetch-scenario
	docker build -f containers/init_script/Dockerfile -t pyronear/pyro-api-init:latest containers/init_script/
	docker build --build-context scenarios=data/scenarios -f containers/fake_camera/Dockerfile -t pyronear/fake-camera:latest containers/fake_camera/

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

# Base services: db, rustfs, pyro_api, init_script
run-backend:
	docker compose up -d

# Fake camera scenarios: definitions are in data/scenarios/<name>/scenario.json,
# images come from the "scenarios" GitHub release.
SCENARIO ?= smoke-then-clear
export SCENARIO
SCENARIOS_URL = https://github.com/pyronear/pyro-envdev/releases/download/scenarios
# Downloads unless every camera of scenario.json already has frames.
fetch-scenario:
	@python3 -c "import glob, json, sys; d = 'data/scenarios/$(SCENARIO)'; \
		sys.exit(any(not glob.glob(f'{d}/{c}/**/*.jpg', recursive=True) for c in json.load(open(f'{d}/scenario.json'))['cameras']))" || \
		(curl -fsSL $(SCENARIOS_URL)/$(SCENARIO).zip -o /tmp/$(SCENARIO).zip && \
		unzip -oq /tmp/$(SCENARIO).zip -x '*/scenario.json' -d data/scenarios && rm /tmp/$(SCENARIO).zip)

# Fake cameras alone, for a pyro-engine running outside compose (see README)
run-camera: fetch-scenario
	docker compose up -d fakecam-1 fakecam-2

# Engine profile adds engine + pyro_camera_api + fake cameras
run-engine: fetch-scenario
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
	docker compose --profile engine stop engine pyro_camera_api fakecam-1 fakecam-2

restart-engine: stop-engine
	docker compose --profile engine up -d fakecam-1 fakecam-2 pyro_camera_api engine --no-deps

stop:
	docker compose --profile front --profile engine --profile camera --profile tools --profile temporal down -v

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=200

# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------

test:
	pytest -s tests --ignore=tests/e2e -m "not integration"

# End-to-end: fresh stack (data/ is a bind mount, so the init marker survives `down -v`),
# then the tests. Whatever fails, ps and the logs are dumped to e2e-artifacts/ and make
# exits with the failing step's code. The stack is left up for debugging, `make stop` cleans.
e2e:
	$(MAKE) stop
	rm -f data/.init_done
	$(MAKE) init build-e2e
	rm -rf e2e-artifacts && mkdir -p e2e-artifacts
	@rc=0; \
	docker compose --profile front --profile engine up -d --wait || rc=$$?; \
	if [ $$rc -eq 0 ]; then \
		uv run --python 3.12 --with-requirements tests/requirements.txt pytest tests/e2e --junitxml=e2e-artifacts/junit.xml -ra --tb=short || rc=$$?; \
	fi; \
	docker compose ps -a > e2e-artifacts/ps.txt 2>&1; \
	docker compose --profile front --profile engine logs --no-color > e2e-artifacts/compose.log 2>&1; \
	exit $$rc
