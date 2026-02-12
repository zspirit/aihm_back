import pytest


@pytest.fixture()
async def position_id(client, auth_headers):
    res = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={
            "title": "Test Position",
            "required_skills": ["Python", "React"],
        },
    )
    return res.json()["id"]


@pytest.mark.asyncio
async def test_create_candidate(client, auth_headers, position_id):
    from io import BytesIO

    files = {"cv": ("cv.pdf", BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    data = {"name": "Ali Benali", "email": "ali@example.com", "phone": "+212600000000"}

    res = await client.post(
        f"/api/v1/positions/{position_id}/candidates",
        headers=auth_headers,
        data=data,
        files=files,
    )
    assert res.status_code == 201
    cand = res.json()
    assert cand["name"] == "Ali Benali"
    assert cand["email"] == "ali@example.com"
    assert cand["pipeline_status"] == "new"


@pytest.mark.asyncio
async def test_create_candidate_no_cv(client, auth_headers, position_id):
    data = {"name": "Sans CV"}
    res = await client.post(
        f"/api/v1/positions/{position_id}/candidates",
        headers=auth_headers,
        data=data,
    )
    assert res.status_code == 201
    assert res.json()["cv_file_path"] is None


@pytest.mark.asyncio
async def test_list_candidates(client, auth_headers, position_id):
    # Create 3 candidates
    for name in ["Alice", "Bob", "Charlie"]:
        await client.post(
            f"/api/v1/positions/{position_id}/candidates",
            headers=auth_headers,
            data={"name": name},
        )

    res = await client.get(
        f"/api/v1/positions/{position_id}/candidates",
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


@pytest.mark.asyncio
async def test_list_candidates_search(client, auth_headers, position_id):
    await client.post(
        f"/api/v1/positions/{position_id}/candidates",
        headers=auth_headers,
        data={"name": "Ahmed Fassi"},
    )
    await client.post(
        f"/api/v1/positions/{position_id}/candidates",
        headers=auth_headers,
        data={"name": "Leila Tazi"},
    )

    res = await client.get(
        f"/api/v1/positions/{position_id}/candidates?search=ahmed",
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["total"] == 1


@pytest.mark.asyncio
async def test_list_candidates_pagination(client, auth_headers, position_id):
    for i in range(5):
        await client.post(
            f"/api/v1/positions/{position_id}/candidates",
            headers=auth_headers,
            data={"name": f"Cand {i}"},
        )

    res = await client.get(
        f"/api/v1/positions/{position_id}/candidates?page=1&page_size=2",
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_get_candidate(client, auth_headers, position_id):
    create_res = await client.post(
        f"/api/v1/positions/{position_id}/candidates",
        headers=auth_headers,
        data={"name": "Get Me", "email": "getme@test.com"},
    )
    cand_id = create_res.json()["id"]

    res = await client.get(f"/api/v1/candidates/{cand_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["name"] == "Get Me"
    assert res.json()["position_id"] == position_id


@pytest.mark.asyncio
async def test_delete_candidate(client, auth_headers, position_id):
    create_res = await client.post(
        f"/api/v1/positions/{position_id}/candidates",
        headers=auth_headers,
        data={"name": "Delete Me"},
    )
    cand_id = create_res.json()["id"]

    res = await client.delete(f"/api/v1/candidates/{cand_id}", headers=auth_headers)
    assert res.status_code == 204

    get_res = await client.get(f"/api/v1/candidates/{cand_id}", headers=auth_headers)
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_delete_candidate_viewer_forbidden(client, auth_headers, viewer_headers, position_id):
    create_res = await client.post(
        f"/api/v1/positions/{position_id}/candidates",
        headers=auth_headers,
        data={"name": "No Delete"},
    )
    cand_id = create_res.json()["id"]

    res = await client.delete(f"/api/v1/candidates/{cand_id}", headers=viewer_headers)
    assert res.status_code in (403, 404)


@pytest.mark.asyncio
async def test_grant_consent(client, auth_headers, position_id):
    create_res = await client.post(
        f"/api/v1/positions/{position_id}/candidates",
        headers=auth_headers,
        data={"name": "Consent Me", "phone": "+212600000001"},
    )
    cand_id = create_res.json()["id"]

    res = await client.post(f"/api/v1/candidates/{cand_id}/grant-consent", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["consents_granted"] == 2

    # Verify candidate status updated
    get_res = await client.get(f"/api/v1/candidates/{cand_id}", headers=auth_headers)
    assert get_res.json()["pipeline_status"] == "consent_given"


@pytest.mark.asyncio
async def test_export_csv(client, auth_headers, position_id):
    await client.post(
        f"/api/v1/positions/{position_id}/candidates",
        headers=auth_headers,
        data={"name": "Export User"},
    )

    res = await client.get(
        f"/api/v1/positions/{position_id}/candidates/export",
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "text/csv; charset=utf-8"
    assert "Export User" in res.text
