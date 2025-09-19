# Build the docker images contained in this repo

build:
	docker build -f containers/init_script/Dockerfile -t pyronear/pyro-api-init:latest containers/init_script/
	docker build -f containers/reolinkdev1/Dockerfile -t pyronear/reolinkdev1:latest containers/reolinkdev1/
	docker build -f containers/reolinkdev2/Dockerfile -t pyronear/reolinkdev2:latest containers/reolinkdev2/
	docker build -f containers/notebooks/Dockerfile -t pyronear/notebooks:latest containers/notebooks/

build-external:
	cd ../pyro-api/; make build
	cd ../pyro-engine/; make build-lib
	cd ../pyro-engine/; make build-app
	cd ../pyro-platform/; make build


build-all: build build-external

run-backend:
	docker compose up -d

run-engine:
	docker compose --profile engine up -d

run-tools:
	cp .env.test .env
	docker compose --profile tools up -d

run-etl:
	docker compose --profile etl up -d

run:
	docker compose --profile front up -d

run-all:
	docker compose --profile front --profile engine up -d

stop:
	docker compose --profile front --profile engine --profile etl down

test:
	pytest -s tests/*
