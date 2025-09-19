**README**

This Docker Compose configuration sets up a development environment for Pyronear's API along with supporting services like a PostgreSQL database, MinIO for S3 emulation, Pyro Engine, and Promtail for log shipping.

## Services
1. **pyro-api**: Runs the Pyronear API using uvicorn.
2. **db**: PostgreSQL database for the API.
3. **minio**: Emulates AWS S3 using [MinIO](https://github.com/minio/minio).
4. **pyro-engine**: Pyro Engine service.
5. **reolinkdev**: a service which imitate a reolink camera by sending back pictures of fire.
6. **frontend**: our webapp available on the 8085 port.


   _Additional services (helpers):_
7. **notebooks** : Python notebook server to run scripts on api without having to install python
8. **db-ui** (pgadmin): UI to visualize and manipulate the data in PostgreSQL database

## Installation
### Prerequisites
- Docker and Docker Compose installed on your system.
- Precommit hook installed on this repo

### Running everything (engine + predefined alerts)

Start the Docker services using the following commands:

```bash
make build
make run-all
```

This will launch the full stack including the engine and the predefined alert generation.

---

you can check that everyhing is working thanks to the following commands :
```bash
docker logs init
docker logs engine
```


### Running services partially
If you want to launch only the engine and two dev-cameras you can use :
```bash
make run-engine
```

If you want to launch only the backend (in order to develop the frontend) :
```bash
make run-backend
```

If you want to launch only the additional tools, you can use :
```bash
make run-tools
```

### Running customized alerts using personal notebooks (not in docker)

Install the notebook dependencies:

```bash
pip install -r notebooks/requirements.txt
```


## Access
### Accessing the API
Once the services are up and running, you can access the Pyronear API at `http://localhost:5050/docs`.


### Accessing the Dash web-app

Since Dash can be a bit capricious, you should launch a private window from you browser and access the web app at `http://localhost:8050`

29/01/2024 : For the moment, the ADMIN access doesn't show the alerts sent by the camera. For that you will have to use a user account which are defined in data/csv/users.csv

### Launch the web app manually from the pyro-platform directory

You can launch the backend (alert-api, postgresdb & s3) :

```bash
make run-backend
```

And, in your pyro-platform/.env use this API_URL env var :
```bash
API_URL=http://localhost:5050
```

### Access the service notebooks
Access at the address :  http://localhost:8889/

For the first connection, open the logs of the container.
Copy the token and save it for later (to login in the service)


### Access the service db-ui
You can access the db-ui service (pgadmin) at `http://localhost:8888/browser/`

Log in with the mail/pwd specified in the env file (`DB_UI_MAIL`/`DB_UI_PWD`)

At the first connection, the db server must be configured:
- Register a server with those data :
- Name: "pyro-db"
- Host name/address: "db"
- Maintenance database : see POSTGRES_DB in .env
- User : see POSTGRES_USER in .env
- Password : see POSTGRES_PASSWORD in .env

### Access the S3 GUI MinIO console
You can access S3 GUI MinIO console at `http://localhost:9001/`
And then upload/download/delete files, create buckets.

## How to use data
#### How to update the last image for a camera
- In S3 GUI MinIO console, open the directory finishing by "...-alert-api-{organisation_id}" and upload the image
- In db-ui, open the table "cameras" and update
    - the column last_image with the filename from above
    - the column last_active_at

### More images in the Reoling Dev Camera
you need to create a directory data/images before launching the env, with the images inside !

### How to create alerts
Use one of the provided notebooks to send custom alerts manually.

For example, to send real alerts based on selected examples, run:

```bash
notebooks/send_real_alerts.ipynb
```

Then, you will be able to connect to the API thanks to the credentials in the .env file
Note : if the notebook is run in a container, please change the following variable
in the files .ipynb
API_URL = "http://api:5050"

## Cleanup
To stop and remove the Docker services, run:
```bash
make stop
```
