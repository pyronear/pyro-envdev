# Build the docker images contained in this repo

build:
	docker build -f containers/init_script/Dockerfile -t pyronear/pyro-api-init:latest containers/init_script/
	docker build -f containers/dev_reolink/Dockerfile -t pyronear/dev-reolink:latest containers/dev_reolink/
	docker build -f containers/reolink_dev2/Dockerfile -t pyronear/reolink-dev2:latest containers/reolink_dev2/

build-external:
	cd ../pyro-api/; make build
	cd ../pyro-engine/; make build-lib
	cd ../pyro-engine/; make build-app
	cd ../pyro-platform/; make build


build-all: build build-external

run-api:
	cp .env.test .env
	docker compose up -d

run-engine:
	cp .env.test .env
	docker compose --profile engine up -d

run-front:
	cp .env.test .env
	docker compose --profile front up -d

run:
	cp .env.test .env
	docker compose --profile front --profile engine up -d

stop:
	docker compose --profile front --profile engine down

test:
	pytest -s tests/*
