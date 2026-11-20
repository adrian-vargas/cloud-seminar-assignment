# Cloud Notes

A small 3-service app deployed to Azure for the Cloud Deployments Seminar assignment.

```
Browser ──► Frontend (Blob Storage static website)
   │
   └──────► API: Python/FastAPI container (Azure Container Apps)
                 │
                 └──► Azure Database for PostgreSQL (Flexible Server)
```

| Service | Code | Runs on (Azure) | Runs on (local) |
|---|---|---|---|
| Frontend | `web/` (HTML + JS, no build step) | Storage account, static website | nginx container |
| API | `api/` (FastAPI, Dockerfile) | Container Apps, public HTTPS ingress | container |
| Database | — | PostgreSQL Flexible Server (managed) | `postgres:17-alpine` |

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/message` | greeting from `APP_MESSAGE` and the image version (commit SHA) |
| GET | `/api/notes` | list notes (newest first) |
| POST | `/api/notes` | create a note: `{"text": "..."}` (1–500 chars) |
| DELETE | `/api/notes/{id}` | delete a note |
| GET | `/livez` | liveness: the process is up |
| GET | `/readyz` | readiness: the database answers (503 otherwise) |

## Configuration (environment variables only)

| Variable | Where it comes from in Azure |
|---|---|
| `DATABASE_URL` | Container Apps **secret** `database-url` (`secretref:`), never in code or image |
| `CORS_ORIGINS` | env var: the static website URL |
| `APP_MESSAGE` | env var: changing it creates a new revision with no rebuild |
| `APP_VERSION` | baked in at build time (`--build-arg`), set to the commit SHA by CI |

## Good practices applied

- Multi-stage API image on `python:3.13-slim`: dependencies in a cached layer, no pip cache or build tooling in the final image, runs as a non-root user.
- No secrets in Git: the connection string is a Container Apps secret; locally it comes from a git-ignored `.env`.
- Images are tagged with the commit SHA, never only `:latest`, so every deployment traces back to its code and rollback is redeploying an older tag.
- Liveness and readiness endpoints; readiness returns 503 while shutting down or when the database is unreachable.
- User input is rendered with `textContent` (no HTML injection) and validated in the API.

## Run locally

```cmd
copy .env.example .env
docker compose up --build
```

Open http://localhost:3000. The API is also at http://localhost:8080/api/message.
`docker compose down` keeps the data (volume `dbdata`); `docker compose down -v` deletes it.

Tests (no database needed, an in-memory repo is injected):

```cmd
cd api
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Deploy to Azure (Windows `cmd`)

Prerequisites: `az login`, `docker login`. The `^` at line ends continues a command in `cmd`.
Run these commands in `cmd`, not PowerShell: PowerShell does not expand `%VAR%` (it would use `$env:VAR`).

### 0. Variables

```cmd
set LOCATION=norwayeast
set RG=rg-notes
set PG=pg-notes-adrivara-no
set STORAGE=stnotesadrivara
set DOCKER_USER=adrivara
set PG_PASSWORD=ChangeMe2026SomethingLong
```

Use your own password: at least 16 characters with upper case, lower case and digits only (no symbols, so it is safe inside a URL and in `cmd`). It is typed here, never committed.

Region: the Azure for Students subscription only allows `norwayeast`, `brazilsouth`, `chilecentral`, `francecentral` and `swedencentral`. The PostgreSQL `Standard_B1ms` SKU was not available in `swedencentral` (`SkuNotAvailable`), so the deployment uses `norwayeast`. The server name has a region suffix (`-no`) because a name used in a failed attempt in another region can stay reserved for a while.

### 1. Resource group

```cmd
az group create -n %RG% -l %LOCATION%
```

### 1b. Register resource providers (once per subscription)

A new subscription fails with `MissingSubscriptionRegistration` until these are registered:

```cmd
az provider register --namespace Microsoft.DBforPostgreSQL --wait
az provider register --namespace Microsoft.Storage --wait
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait
```

### 2. Managed database (takes 5–10 min)

```cmd
az postgres flexible-server create -g %RG% -n %PG% -l %LOCATION% ^
  --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 17 ^
  --admin-user notesadmin --admin-password %PG_PASSWORD% ^
  --public-access 0.0.0.0 --yes
az postgres flexible-server db create -g %RG% -s %PG% -n notes
```

The database is created with a separate command: in current Azure CLI versions `--database-name` on `flexible-server create` only applies to elastic clusters.

`--public-access 0.0.0.0` allows connections only from Azure services (Container Apps), not from the whole Internet. TLS is required (`sslmode=require`).

### 3. Storage account with static website

```cmd
az storage account create -g %RG% -n %STORAGE% -l %LOCATION% --sku Standard_LRS --kind StorageV2
az storage account update -g %RG% -n %STORAGE% --min-tls-version TLS1_2
az storage blob service-properties update --account-name %STORAGE% --auth-mode key ^
  --static-website --index-document index.html
az storage account show -g %RG% -n %STORAGE% --query primaryEndpoints.web -o tsv
```

Copy the URL from the last command:

```cmd
set WEB_URL=https://stnotesadrivara.zXX.web.core.windows.net
```

### 4. API image

The image is published by CI (see [CI/CD](#cicd-github-actions)): every push to `main` that touches `api/` pushes `docker.io/%DOCKER_USER%/notes-api:<commit-sha>`. Take the full SHA of that commit (`git rev-parse HEAD`, or the Actions run) and use it as the tag:

```cmd
set IMAGE_TAG=<commit-sha>
```

Manual alternative, only if CI has not run yet:

```cmd
docker build -t %DOCKER_USER%/notes-api:%IMAGE_TAG% --build-arg APP_VERSION=%IMAGE_TAG% ./api
docker push %DOCKER_USER%/notes-api:%IMAGE_TAG%
```

### 5. Container App

```cmd
az extension add --name containerapp --upgrade

az containerapp env create -g %RG% -n cae-notes -l %LOCATION%

az containerapp create -g %RG% -n notes-api --environment cae-notes ^
  --image docker.io/%DOCKER_USER%/notes-api:%IMAGE_TAG% ^
  --target-port 8080 --ingress external --min-replicas 0 --max-replicas 2 ^
  --secrets "database-url=postgresql://notesadmin:%PG_PASSWORD%@%PG%.postgres.database.azure.com:5432/notes?sslmode=require" ^
  --env-vars DATABASE_URL=secretref:database-url CORS_ORIGINS=%WEB_URL% "APP_MESSAGE=Hello from Azure Container Apps"

az containerapp show -g %RG% -n notes-api --query properties.configuration.ingress.fqdn -o tsv
```

Copy the FQDN and check `https://<FQDN>/api/message` and `https://<FQDN>/readyz` in the browser.

### 6. Upload the frontend

```cmd
rmdir /s /q dist 2>nul
xcopy web dist\ /e /i /q
del dist\Dockerfile dist\nginx.conf
echo window.APP_CONFIG = { API_URL: "https://<FQDN>" }; > dist\config.js
az storage blob upload-batch --account-name %STORAGE% --auth-mode key -s dist -d $web --overwrite
```

Open `%WEB_URL%`: add and delete notes. (`$web` is the literal container name; in PowerShell write `'$web'`.)

### 7. Clean up (after the screenshots and the video)

```cmd
az group delete -n %RG% --yes --no-wait
```

To save credit between work sessions: `az postgres flexible-server stop -g %RG% -n %PG%` (and `start` later).

## CI/CD (GitHub Actions)

`.github/workflows/api-ci.yml` runs on every push to `main` that touches `api/`:

1. **test**: `pytest` against an in-memory repository.
2. **image**: build and push `docker.io/<user>/notes-api:<commit-sha>`, with `APP_VERSION=<commit-sha>`.
3. **deploy** (optional, only if the Azure variables exist): log in to Azure with OIDC (no password stored), `az containerapp update --image ...:<sha>`, then a smoke test that waits until `/api/message` reports the new SHA.

Repository settings → Secrets and variables → Actions:

- Variable `DOCKERHUB_USERNAME`, secret `DOCKERHUB_TOKEN` (Docker Hub personal access token, Read & Write).
- For the deploy job: variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP` (`rg-notes`), `AZURE_CONTAINER_APP` (`notes-api`).

OIDC identity for the deploy job (edit `GITHUB_USER` in `infra/github-oidc.json` first):

```cmd
az ad app create --display-name gh-notes-deploy --query appId -o tsv
az ad sp create --id <APP_ID>
az role assignment create --assignee <APP_ID> --role Contributor ^
  --scope /subscriptions/<SUBSCRIPTION_ID>/resourceGroups/rg-notes
az ad app federated-credential create --id <APP_ID> --parameters infra/github-oidc.json
```

The role is scoped to the resource group only, and the federated credential trusts only the `main` branch of this repository.
