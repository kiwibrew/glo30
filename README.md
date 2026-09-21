# Copernicus GLO-30 Viewshed API

This FastAPI service creates terrain viewsheds from Copernicus GLO-30 DGED elevation data. It returns the visible area as a GeoJSON Feature and includes authenticated Swagger, user administration, and a tile-cache page.

Terrain data produced using Copernicus WorldDEM™-30 © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018, provided under COPERNICUS by the European Union and ESA; all rights reserved.

## How it Works

The service gets the Copernicus GLO-30 DGED GeoTIFF tiles required for a request. It first finds every one-degree geocell that intersects the requested circle. It uses a locally cached tile when one is available; otherwise, it finds the product through the Copernicus catalogue, downloads the DEM from the Copernicus Data Space Ecosystem S3 service, and records it in the SQLite cache.

All geographic input uses longitude and latitude in WGS 84 coordinates. The service reprojects the required DEM tiles into an Azimuthal Equidistant projection centred on the observer, so it can calculate distances and the output grid in metres.

`POST /api/v1/viewsheds` accepts an observer position, observer and target heights above ground level, and a radius. GDAL calculates the visible cells in the local raster. By default, it accounts for Earth curvature and uses an atmospheric-refraction coefficient of `1/7`.

The service polygonises the visible cells, simplifies the result to a configurable global vertex budget, and transforms it back to WGS 84. The response geometry is a GeoJSON Polygon or MultiPolygon. Its visible area and pixel count are calculated before simplification.

| Library | Use |
| --- | --- |
| Boto3 | Find and download Copernicus DGED tiles from S3. |
| HTTPX | Query the Copernicus catalogue for tile products. |
| Rasterio | Read, reproject, and polygonise DEM rasters. |
| GDAL | Calculate the terrain viewshed. |
| PyProj | Calculate geodesic coverage and create the local metre-based projection. |
| Shapely | Simplify and transform the output geometry. |

## Run the service

Docker Compose is the only supported application environment. CPython and all application tools run in the `app` container.

1. Copy `docker-compose.yml.example` to `docker-compose.yml`.
2. Copy `.env.example` to `.env`.
3. Set valid Copernicus Data Space Ecosystem S3 credentials and replace `secret_key` with a long, random value. Set `cookie_secure=true` for production HTTPS.
4. Build and start the service:

```bash
docker compose up --build
```

5. Create the first administrator:

```bash
docker compose run --rm app python manage_users.py create admin@example.com 'a-long-password'
```

The application is available at <http://localhost:8004>. The SQLite database and downloaded DEM tiles remain in the `glo30-data` Docker volume.

Do not install Python packages or run Python tools on the host. Declare dependencies in the repository, then rebuild the image.

## API

All application endpoints use the `/api/v1` prefix and require an active account:

| Method | Endpoint | Input | Result |
| --- | --- | --- | --- |
| `GET` | `/api/v1/health` | None | Service health response. |
| `POST` | `/api/v1/viewsheds` | Observer, heights, and radius JSON body. | A visible-area GeoJSON Feature. |

For example:

```bash
curl -X POST \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  http://localhost:8004/api/v1/viewsheds \
  --data '{
    "observer_coordinates": [174.2316077, -39.0035668],
    "observer_height_agl_m": 30,
    "target_height_agl_m": 0,
    "radius_m": 10000
  }'
```

`observer_coordinates` uses GeoJSON order: `[longitude, latitude]`. Heights and radius are metres. Observer and target heights must be from `0` through `10,000` metres. The radius must be greater than `0` and no greater than `max_radius_m`, which defaults to `100,000` metres.

The response has this shape:

```json
{
  "type": "Feature",
  "properties": {
    "observer_height_agl_m": 30,
    "observer_coordinates": [174.2316077, -39.0035668],
    "target_height_agl_m": 0,
    "radius_m": 10000,
    "dem": "Copernicus GLO-30 DGED",
    "visible_area_sq_km": 126.4,
    "visible_pixel_count": 140472,
    "resolution_m": 30,
    "earth_curvature": true,
    "refraction_coefficient": 0.14285714285714285
  },
  "geometry": {
    "type": "MultiPolygon",
    "coordinates": []
  }
}
```

Send API credentials in `Authorization: Bearer TOKEN`. The application tries a persistent token first, then accepts an access-type JWT from `POST /token`. Inactive accounts receive HTTP 403.

### Error handling

The API reports a valid request whose required DEM tile is unavailable as HTTP 422, rather than an upstream gateway error. This lets clients receive the application response instead of a proxy-generated 502 page.

A request that intersects a geocell withheld from public distribution receives HTTP 422 with an explanation that the geography is not yet released. A tile that is not restricted but has no Copernicus catalogue product or DEM object also receives HTTP 422:

```json
{
  "detail": "The geography you have requested is not available from Copernicus GLO-30"
}
```

Actual Copernicus catalogue or S3 failures receive HTTP 502. Viewshed-processing failures receive HTTP 500. The configured `glo30_restricted_tile_ids` list contains the known unavailable geocells.

## Configuration

Copy `.env.example` to `.env`. Change values there, then restart the app container. `app/config.py` defines the settings, types, validation, and defaults. Environment variables override those defaults.

| Setting | Default | Purpose |
| --- | ---: | --- |
| `DATABASE_URL` | `sqlite+aiosqlite:////app/data/app.db` | SQLAlchemy database connection URL. |
| `TILE_CACHE_DIR` | `/app/data/tiles` | Directory for downloaded DGED GeoTIFF tiles. |
| `TILE_CACHE_EXPIRY_DAYS` | `30` | Days before an unused cached tile expires. |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Required | Copernicus Data Space Ecosystem S3 credentials. |
| `S3_HOST_BASE` | `eodata.dataspace.copernicus.eu` | Copernicus S3 endpoint host. |
| `S3_BUCKET_NAME` | `eodata` | Copernicus S3 bucket name. |
| `GLO30_S3_PREFIX` | Empty | Optional direct S3 prefix that bypasses catalogue discovery. |
| `MAX_RADIUS_M` | `100000` | Largest accepted viewshed radius in metres. |
| `DEM_RESOLUTION_M` | `30` | Working-raster cell size in metres. |
| `DEM_RESAMPLING_METHOD` | `bilinear` | Elevation interpolation for the working grid. |
| `GEOMETRY_VERTICES_PER_SQ_KM` | `100` | Vertex budget density for the output geometry. |
| `GEOMETRY_MIN_VERTEX_BUDGET` | `8` | Smallest global geometry vertex budget. |
| `GEOMETRY_MAX_VERTEX_BUDGET` | `10000` | Largest global geometry vertex budget. |
| `SECRET_KEY` | Required | Secret used to sign JWTs and CSRF tokens. Use a long random value. |
| `COOKIE_SECURE` | `false` | Send cookies only over HTTPS when `true`. |
| `SMTP_ENABLED` | `false` | Enable password-reset email delivery. |
| `SMTP_HOST` / `SMTP_FROM` | Empty | Required SMTP host and sender when email is enabled. |

`GLO30_S3_PREFIX` must use this direct-geocell layout:

```text
<glo30_s3_prefix>/
  Copernicus_DSM_10_<geocell>/DEM/Copernicus_DSM_10_<geocell>_DEM.tif
```

Lower `DEM_RESOLUTION_M` values make a finer working raster, with substantially greater memory and compute cost. Values below GLO-30's native detail interpolate existing terrain rather than adding measurements. Increase `GEOMETRY_VERTICES_PER_SQ_KM` to retain more curved edges and output detail. The complete output-shape controls are documented with their defaults in `app/config.py`.

Running the service requires a Copernicus Data Space Ecosystem account registered for Copernicus Contributing Missions access. Generate S3 credentials through the Copernicus Data Space Ecosystem portal.

## Authentication and UI

Open `/` and sign in with an administrator account. Authenticated users can access these pages:

- `/docs` for Swagger
- `/app-docs` for this guide
- `/manage-users` for their visible account information
- `/tile-cache` for the current GLO-30 tile inventory

Administrators manage users. API users get a random persistent bearer token; administrators never get one. `/token` exchanges a valid email and password for a short-lived JWT. Browser sessions use a separate typed JWT in an HTTP-only cookie.

Use `/forgot-password` to request a reset code. When SMTP delivery is enabled, the service emails a one-time code. The code expires after 30 minutes. Paste it into `/reset-password`. The acknowledgement is the same whether or not an eligible account exists.

## Database and first administrator

The container applies Alembic migrations when it starts. Use these commands for explicit migration work:

```bash
docker compose run --rm app alembic upgrade head
docker compose run --rm app alembic revision --autogenerate -m "description"
```

Create or remove an account with the user-management command:

```bash
docker compose run --rm app python manage_users.py create admin@example.com 'a-long-password'
docker compose run --rm app python manage_users.py remove user@example.com
```

The command does not print a password, password hash, JWT, or persistent token.

## Checks

Run every check through Compose:

```bash
docker compose run --rm app pytest
docker compose run --rm app pytest --cov=app
docker compose run --rm app ruff check .
docker compose run --rm app ruff format --check .
docker compose run --rm app mypy app/
```

Tests use a separate SQLite database. Rollback transactions isolate database changes.

## Structure

```text
app/
├── main.py
├── config.py
├── database.py
├── dependencies.py
├── models/
├── schemas/
├── routers/
├── services/
├── repositories/
└── templates/
tests/
├── conftest.py
├── test_routers/
└── test_services/
migrations/
```

## Citation

Copernicus DEM GLO-30 (DGED). European Space Agency (ESA) and the Copernicus Programme. Digital Surface Model (DSM), 30 m global resolution. DOI: 10.5270/ESA-c5d3d65.
