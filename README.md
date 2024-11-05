**README**

This Docker Compose configuration sets up a development environment for Pyronear's API along with supporting services like a PostgreSQL database, LocalStack for S3 emulation, Pyro Engine, and Promtail for log shipping.

### Prerequisites
- Docker and Docker Compose installed on your system.
- Precommit hook installed on this repo

### Usage

 Start the Docker services using the following command:
    ```
    make build
    make run-api
    ```
Then, you will be able to connect to the API thanks to the credentials in the .env file

If you want to launch the engine and two dev-cameras you can use :
    ```
    make run-engine
    ```

### Services
1. **pyro-api**: Runs the Pyronear API using uvicorn.
2. **db**: PostgreSQL database for the API.
3. **localstack**: Emulates AWS S3 using LocalStack.
4. **pyro-engine**: Pyro Engine service.
5. **reolink_dev**: a service which imitate a reolink camera by sending back pictures of fire

### Accessing the API
Once the services are up and running, you can access the Pyronear API at `http://localhost:5050/docs`.


### Cleanup
To stop and remove the Docker services, run:
```
make stop
```

### More images in the Reoling Dev Camera

you need to create a directory data/images before launching the env, with the images inside :)

This Docker Compose setup provides a comprehensive development environment for working with Pyronear's API and supporting services.
