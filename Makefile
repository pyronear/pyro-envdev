# Build the docker images contained in this repo

build:
	docker build -f containers/init_script/Dockerfile -t pyronear/pyro-api-init:latest containers/init_script/
	docker build -f containers/dev_reolink/Dockerfile -t pyronear/dev-reolink:latest containers/dev_reolink/

build-external:
	cd ../pyro-api/; make build
	cd ../pyro-engine/; make build


build-all: build build-external

run:
	cp .env.test .env
	docker compose up -d

stop:
	docker compose down
