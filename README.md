# Pyronear Dev Environment

This repository provides a Docker Compose configuration to run a full Pyronear development environment with the API, database, S3 emulation, frontend, notebooks, and optional camera engine.

---

## ⚙️ Installation

### Prerequisites

* Docker and Docker Compose

> **Upgrading?** MinIO was replaced by [RustFS](https://github.com/rustfs/rustfs): set
> `S3_ENDPOINT_URL=http://rustfs:9000` in your `.env` (or re-run `cp .env.test .env`).
> The `127.0.0.1 minio` hosts entry is no longer needed either.

---

## 🚀 Quick Start

### Init

```bash
make init
make build
```

### Run

```bash
make run
```

* Send an alert by opening [http://0.0.0.0:8889/notebooks/notebooks/send_real_alerts.ipynb](http://0.0.0.0:8889/notebooks/notebooks/send_real_alerts.ipynb)
* Observe the alert on the frontend at [http://localhost:8080/](http://localhost:8080/)
* Use credentials from `data/csv/API_DATA_DEV/users.csv`
* Or check directly on the API at [http://0.0.0.0:5050/docs](http://0.0.0.0:5050/docs) with the same creds

---

## 🧩 Services

* **pyro-api**: Pyronear API (uvicorn)
* **db**: PostgreSQL database
* **rustfs**: S3-compatible storage (via RustFS)
* **keycloak**: identity provider for platform users and scripts (realm `pyronear`). The API image must
  verify Keycloak tokens, which needs pyro-api's Keycloak support (build it with `make build-external`
  until a release ships it).
* **frontend**: Web app (React, [pyro-platform](https://github.com/pyronear/pyro-platform))
* **pyro-engine**: Engine service (requires cameras, optional)
* **reolinkdev1 / reolinkdev2**: Fake Reolink cameras sending test images
* **notebooks**: Jupyter server to run helper notebooks
* **db-ui**: pgAdmin to browse/manage the database

---

## ▶️ Running

### Full stack with engine

```bash
make build
make run-all
```

This launches everything including the engine and simulated alerts.
You can check health with:

```bash
docker logs init
docker logs engine
```

### Partial runs

* Backend only (API, DB, S3, Keycloak):

  ```bash
  make run-backend
  ```
* Engine only:

  ```bash
  make run-engine
  ```
* Tools only (notebooks, db-ui):

  ```bash
  make run-tools
  ```

---

## 🔑 Access

* **API**: [http://localhost:5050/docs](http://localhost:5050/docs)
* **Frontend (React app)**: [http://localhost:8080](http://localhost:8080)

  * If issues: use a private browser window
  * Admin access currently does not display camera alerts, use user creds from `data/csv/users.csv`
  * Configuration (API URL, etc.) lives in `containers/frontend/app-config.js`
* **Notebooks**: [http://localhost:8889](http://localhost:8889)
* **Keycloak admin console**: [http://localhost:9310/admin/](http://localhost:9310/admin/)

  * Login: `KEYCLOAK_USERNAME` / `KEYCLOAK_PASSWORD` (set in `.env`)
  * The realm is imported from `containers/keycloak/realm/realm_pyronear.json` only when the container is
    created. After changing that file, recreate it: `docker compose up -d --force-recreate keycloak`
* **pgAdmin (db-ui)**: [http://localhost:8888/browser/](http://localhost:8888/browser/)

  * Login: `DB_UI_MAIL` / `DB_UI_PWD` (set in `.env`)
  * First connection: register server with host `db`, user/password from `.env`
* **RustFS console (S3 GUI)**: [http://localhost:9001/rustfs/console/](http://localhost:9001/rustfs/console/)

  * Login: `S3_ACCESS_KEY` / `S3_SECRET_KEY` (set in `.env`)
  * Manage buckets, upload/delete files
* **RustFS S3 API**: `rustfs:9000` from the compose network (`S3_ENDPOINT_URL`),
  [http://localhost:9000](http://localhost:9000) from the host (`S3_PROXY_URL`, used
  for presigned image URLs)

---

## 📂 Data Usage

### Users Keycloak

| Username      | Organization_id | Realm role | Password |
|---------------|-----------------|------------|----------|
| test77        | 2               | operator   | test     |
| test07        | 3               | operator   | test     |
| test07-viewer | 3               | viewer     | test     |
| test-admin    | 1               | admin      | test     |

Realm roles map to API roles: `admin` → `admin`, `operator` → `agent`, `viewer` → `user`.
The organization comes from the `pyro-organization` user attribute (an API organization id).

Access tokens for pyro-api carry:

* `aud`: includes `pyro-api` (`pyro-api` client scope)
* `roles`: the user's realm roles (`pyro-api` client scope)
* `organization_id`: the `pyro-organization` attribute (`pyro-organization` client scope)

### API client

pyro-api checks every Keycloak token twice: locally (signature, expiry, issuer, audience), then with
Keycloak's introspection endpoint, so a revoked session or a disabled user is rejected on its next request.
It authenticates those calls as the confidential `pyro-api` client (secret `KEYCLOAK_API_CLIENT_SECRET`,
dev-only value `pyro-api-dev-secret`).

### Scripts service account

The init script and notebooks call the API with an admin token from the `pyro-scripts` client
(client credentials grant, realm role `admin`, organization 1), configured by `KEYCLOAK_TOKEN_URL`,
`KEYCLOAK_SCRIPTS_CLIENT_ID` and `KEYCLOAK_SCRIPTS_CLIENT_SECRET` in `.env`. The secret is a dev-only value
committed in the realm export.

```python
from api import get_token
token = get_token(KEYCLOAK_TOKEN_URL, KEYCLOAK_SCRIPTS_CLIENT_ID, KEYCLOAK_SCRIPTS_CLIENT_SECRET)
```

Service-account tokens last 10 hours (`access.token.lifespan` on the `pyro-scripts` client, capped by the
realm's 10-hour session maximum) because the scripts fetch one token per run; user tokens keep the realm's
5 minutes.

From the host, use `http://localhost:9310/realms/pyronear/protocol/openid-connect/token` as the token URL.
Keycloak issues the same `iss` (`http://localhost:9310/realms/pyronear`) either way (`KC_HOSTNAME`).


### Add more images to Reolink Dev

Create a directory `data/images` before starting the environment and put your images inside.

### Send custom alerts

Use Jupyter notebooks (e.g., `notebooks/send_real_alerts.ipynb`).
When running notebooks **inside Docker**, set:

```python
API_URL = "http://api:5050"

### Update the last image for a camera

1. Upload a new image in RustFS under the bucket ending with `...-alert-api-{organisation_id}`
2. In pgAdmin, update the `cameras` table:

   * `last_image` with the filename
   * `last_active_at` timestamp


```

---

## 🛑 Cleanup

Stop and remove everything:

```bash
make stop
```
