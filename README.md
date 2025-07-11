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
5. **reolinkdev**: a service which imitate a reolink camera by sending back pictures of fire.
6. **frontend**: our webapp available on the 8085 port.

### Usage

Thank you, here’s the corrected and complete version including the missing step about installing the notebooks requirements:

---

#### 1. Running everything (engine + predefined alerts)

Start the Docker services using the following commands:

```bash
make build
make run-all
```

This will launch the full stack including the engine and the predefined alert generation.

---

#### 2. Running customized alerts using notebooks

Start the Docker services using the following commands:

```bash
make build
make run
```

Then install the notebook dependencies:

```bash
pip install -r notebooks/requirements.txt
```

Finally, use one of the provided notebooks to send custom alerts manually.

For example, to send real alerts based on selected examples, run:

```bash
notebooks/send_real_alerts.ipynb
```

Then, you will be able to connect to the API thanks to the credentials in the .env file

If you want to launch only the engine and two dev-cameras you can use :
```bash
make run-engine
```

you can check that everyhing is working thanks to the following commands :
```bash
docker logs init
docker logs engine
```

### Accessing the API
Once the services are up and running, you can access the Pyronear API at `http://localhost:5050/docs`.


### Accessing the web-app

First you need to tell your computer where your S3 is.
For that you will have to add this line to you /etc/hosts :

```bash
127.0.0.1 www.localstack.com localstack
```

Since Dash can be a bit capricious, you should launch a private window from you browser and access the web app at `http://localhost:8050`

29/01/2024 : For the moment, the ADMIN access doesn't show the alerts sent by the camera. For that you will have to use a user account which are defined in data/csv/users.csv

### Launch the web app manually from the pyro-platform directory

You can launch the API :

```bash
make run-api
```

And, in your pyro-platform/.env use this API_URL env var :
```bash
API_URL=http://localhost:5050
```

### Cleanup
To stop and remove the Docker services, run:
```bash
make stop
```

### More images in the Reoling Dev Camera

you need to create a directory data/images before launching the env, with the images inside !
