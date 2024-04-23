# Build the docker images contained in this repo
build:
	docker build -f containers/init_script/Dockerfile -t pyronear/pyro-api-init:latest containers/init_script/
	docker build -f containers/dev_reolink/Dockerfile -t pyronear/dev-reolink:latest containers/dev_reolink/

run:
	docker compose up -d
