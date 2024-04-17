**README**

This Docker Compose configuration sets up a development environment for Pyronear's API along with supporting services like a PostgreSQL database, LocalStack for S3 emulation, Pyro Engine, and Promtail for log shipping.

### Prerequisites
- Docker and Docker Compose installed on your system.
- Precommit hook installed on this repo

### Usage

 Start the Docker services using the following command:
    ```
    docker-compose up -d
    ```

Currently the initialisation script is failing, so you should launch it again with the command :

    ```
    docker-compose start init_script
    ```

### Services
1. **pyro-api**: Runs the Pyronear API using uvicorn.
2. **db**: PostgreSQL database for the API.
3. **localstack**: Emulates AWS S3 using LocalStack.
4. **pyro-engine**: Pyro Engine service.
5. **promtail**: Log shipper for collecting logs from Docker containers.

### Accessing the API
Once the services are up and running, you can access the Pyronear API at `http://localhost:8080`.

### Monitoring Logs
Promtail collects logs from Docker containers. You can access the Promtail dashboard at `http://localhost:8300`.

### Cleanup
To stop and remove the Docker services, run:
```
docker-compose down
```

This Docker Compose setup provides a comprehensive development environment for working with Pyronear's API and supporting services.