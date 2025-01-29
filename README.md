**README**

This Docker Compose configuration sets up a development environment for Pyronear's API along with supporting services like a PostgreSQL database, LocalStack for S3 emulation, Pyro Engine, and Promtail for log shipping.

### Prerequisites
- Docker and Docker Compose installed on your system.
- Precommit hook installed on this repo


### Services
1. **pyro-api**: Runs the Pyronear API using uvicorn.
2. **db**: PostgreSQL database for the API.
3. **localstack**: Emulates AWS S3 using LocalStack.
4. **pyro-engine**: Pyro Engine service.
5. **reolink_dev**: a service which imitate a reolink camera by sending back pictures of fire.
6. **frontend**: our webapp available on the 8085 port.

### Usage

First you have to create a .env file, a simple copy of the .env.test would be enough.
    ```
    cp .env.test .env
    ```

Start the Docker services using the following command:
    ```
    make build
    make run
    ```
Then, you will be able to connect to the API thanks to the credentials in the .env file

If you want to launch only the engine and two dev-cameras you can use :
    ```
    make run-engine
    ```

you can check that everyhing is working thanks to the following commands :
    ```
    docker logs init
    docker logs engine
    ```

### Accessing the API
Once the services are up and running, you can access the Pyronear API at `http://localhost:5050/docs`.


### Accessing the web-app
Since Dash can be a bit capricious, you should launch a private window from you browser and access the web app at `http://localhost:8050`

### Cleanup
To stop and remove the Docker services, run:
```
make stop
```

### More images in the Reoling Dev Camera

you need to create a directory data/images before launching the env, with the images inside !
