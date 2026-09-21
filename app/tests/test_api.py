import logging
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.dependencies import get_viewshed_service
from app.exceptions import CopernicusConfigurationError, CopernicusTimeoutError, DemCoverageError
from app.main import app
from app.models.user import User
from app.schemas.viewshed import (
    GeoJSONFeature,
    GeoJSONGeometry,
    ViewshedProperties,
    ViewshedRequest,
)
from app.services.s3_tiles import COPERNICUS_CONFIGURATION_MESSAGE, COPERNICUS_TIMEOUT_MESSAGE


class FakeViewshedService:
    async def create(self, request: ViewshedRequest) -> GeoJSONFeature:
        return GeoJSONFeature(
            properties=ViewshedProperties(
                observer_height_agl_m=request.observer_height_agl_m,
                observer_coordinates=request.observer_coordinates,
                target_height_agl_m=request.target_height_agl_m,
                radius_m=request.radius_m,
                visible_area_sq_km=0.9,
                visible_pixel_count=1000,
                resolution_m=30,
                earth_curvature=True,
                refraction_coefficient=1 / 7,
            ),
            geometry=GeoJSONGeometry(
                type="Polygon",
                coordinates=[
                    [
                        [174.0, -39.0],
                        [174.1, -39.0],
                        [174.1, -39.1],
                        [174.0, -39.0],
                    ]
                ],
            ),
        )


REQUEST_BODY = {
    "observer_coordinates": [174.0, -39.0],
    "observer_height_agl_m": 30,
    "target_height_agl_m": 0,
    "radius_m": 1000,
}
RESTRICTED_GEOGRAPHY_DETAIL = (
    "The geography you have requested is not yet released to the public. Please visit "
    "https://sentinels.copernicus.eu/-/copernicus-dem-30-metre-dataset-now-freely-available "
    "for more information"
)
UNAVAILABLE_GEOGRAPHY_DETAIL = (
    "The geography you have requested is not available from Copernicus GLO-30"
)


class CoverageErrorViewshedService:
    def __init__(self, detail: str, log_detail: str | None = None) -> None:
        self.detail = detail
        self.log_detail = log_detail

    async def create(self, _request: ViewshedRequest) -> GeoJSONFeature:
        raise DemCoverageError(self.detail, log_detail=self.log_detail)


class CopernicusErrorViewshedService:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def create(self, _request: ViewshedRequest) -> GeoJSONFeature:
        raise self.error


@pytest.mark.asyncio
async def test_viewshed_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/viewsheds", json=REQUEST_BODY)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_viewshed_returns_typed_geojson(
    client: AsyncClient,
    create_test_user: Callable[..., Awaitable[User]],
) -> None:
    await create_test_user()
    app.dependency_overrides[get_viewshed_service] = lambda: FakeViewshedService()

    response = await client.post(
        "/api/v1/viewsheds",
        json=REQUEST_BODY,
        headers={"Authorization": "Bearer test-bearer-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "Feature"
    assert payload["properties"]["dem"] == "Copernicus GLO-30 DGED"
    assert payload["properties"]["observer_coordinates"] == [174.0, -39.0]
    assert payload["geometry"]["type"] == "Polygon"


@pytest.mark.parametrize(
    "detail",
    [RESTRICTED_GEOGRAPHY_DETAIL, UNAVAILABLE_GEOGRAPHY_DETAIL],
)
@pytest.mark.asyncio
async def test_viewshed_coverage_error_is_returned_as_client_error(
    client: AsyncClient,
    create_test_user: Callable[..., Awaitable[User]],
    detail: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await create_test_user()
    log_detail = "Affected tile: Copernicus_DSM_10_N40_00_E044_00"
    app.dependency_overrides[get_viewshed_service] = lambda: CoverageErrorViewshedService(
        detail,
        log_detail,
    )

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        response = await client.post(
            "/api/v1/viewsheds",
            json=REQUEST_BODY,
            headers={"Authorization": "Bearer test-bearer-token"},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert caplog.record_tuples[-1] == (
        "uvicorn.error",
        logging.WARNING,
        "Application error: POST /api/v1/viewsheds returned 422 "
        f"(DemCoverageError): {detail}; {log_detail}",
    )


@pytest.mark.parametrize(
    ("error", "status_code", "detail", "diagnostic"),
    [
        (
            CopernicusTimeoutError(
                COPERNICUS_TIMEOUT_MESSAGE,
                log_detail="Copernicus catalogue timed out (ReadTimeout)",
            ),
            504,
            COPERNICUS_TIMEOUT_MESSAGE,
            "Copernicus catalogue timed out (ReadTimeout)",
        ),
        (
            CopernicusConfigurationError(
                COPERNICUS_CONFIGURATION_MESSAGE,
                log_detail="Copernicus S3 rejected access (HTTP 403, code=InvalidAccessKeyId)",
            ),
            502,
            COPERNICUS_CONFIGURATION_MESSAGE,
            "Copernicus S3 rejected access (HTTP 403, code=InvalidAccessKeyId)",
        ),
    ],
)
@pytest.mark.asyncio
async def test_viewshed_copernicus_errors_return_safe_detail_and_explicit_logs(
    client: AsyncClient,
    create_test_user: Callable[..., Awaitable[User]],
    error: Exception,
    status_code: int,
    detail: str,
    diagnostic: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await create_test_user()
    app.dependency_overrides[get_viewshed_service] = lambda: CopernicusErrorViewshedService(error)

    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        response = await client.post(
            "/api/v1/viewsheds",
            json=REQUEST_BODY,
            headers={"Authorization": "Bearer test-bearer-token"},
        )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert diagnostic in caplog.record_tuples[-1][2]
    if isinstance(error, CopernicusConfigurationError):
        assert "InvalidAccessKeyId" not in response.text
