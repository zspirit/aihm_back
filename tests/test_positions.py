import pytest


@pytest.mark.asyncio
async def test_create_position(client, auth_headers):
    res = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={
            "title": "Developpeur Python",
            "description": "Backend dev senior",
            "seniority_level": "senior",
            "required_skills": ["Python", "FastAPI", "PostgreSQL"],
            "custom_questions": ["Decrivez votre experience avec FastAPI"],
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Developpeur Python"
    assert data["seniority_level"] == "senior"
    assert len(data["required_skills"]) == 3
    assert len(data["custom_questions"]) == 1
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_create_position_viewer_forbidden(client, viewer_headers):
    res = await client.post(
        "/api/v1/positions",
        headers=viewer_headers,
        json={
            "title": "Nope",
        },
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_list_positions(client, auth_headers):
    # Create 2 positions
    await client.post("/api/v1/positions", headers=auth_headers, json={"title": "Dev Python"})
    await client.post("/api/v1/positions", headers=auth_headers, json={"title": "Dev React"})

    res = await client.get("/api/v1/positions", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_list_positions_search(client, auth_headers):
    await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={"title": "Dev Python Senior"},
    )
    await client.post("/api/v1/positions", headers=auth_headers, json={"title": "Designer UI"})

    res = await client.get("/api/v1/positions?search=python", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert "Python" in res.json()["items"][0]["title"]


@pytest.mark.asyncio
async def test_list_positions_status_filter(client, auth_headers):
    create_res = await client.post(
        "/api/v1/positions", headers=auth_headers, json={"title": "Active"}
    )
    pos_id = create_res.json()["id"]
    await client.put(f"/api/v1/positions/{pos_id}", headers=auth_headers, json={"status": "closed"})

    await client.post("/api/v1/positions", headers=auth_headers, json={"title": "Still Active"})

    res = await client.get("/api/v1/positions?status_filter=active", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total"] == 1


@pytest.mark.asyncio
async def test_list_positions_pagination(client, auth_headers):
    for i in range(5):
        await client.post(
            "/api/v1/positions",
            headers=auth_headers,
            json={"title": f"Position {i}"},
        )

    res = await client.get("/api/v1/positions?page=1&page_size=2", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_get_position(client, auth_headers):
    create_res = await client.post(
        "/api/v1/positions",
        headers=auth_headers,
        json={
            "title": "Get Me",
            "description": "Test position",
        },
    )
    pos_id = create_res.json()["id"]

    res = await client.get(f"/api/v1/positions/{pos_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["title"] == "Get Me"


@pytest.mark.asyncio
async def test_update_position(client, auth_headers):
    create_res = await client.post(
        "/api/v1/positions", headers=auth_headers, json={"title": "Old Title"}
    )
    pos_id = create_res.json()["id"]

    res = await client.put(
        f"/api/v1/positions/{pos_id}",
        headers=auth_headers,
        json={
            "title": "New Title",
            "status": "draft",
        },
    )
    assert res.status_code == 200
    assert res.json()["title"] == "New Title"
    assert res.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_delete_position(client, auth_headers):
    create_res = await client.post(
        "/api/v1/positions", headers=auth_headers, json={"title": "Delete Me"}
    )
    pos_id = create_res.json()["id"]

    res = await client.delete(f"/api/v1/positions/{pos_id}", headers=auth_headers)
    assert res.status_code == 204

    get_res = await client.get(f"/api/v1/positions/{pos_id}", headers=auth_headers)
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_delete_position_viewer_forbidden(client, auth_headers, viewer_headers):
    create_res = await client.post(
        "/api/v1/positions", headers=auth_headers, json={"title": "No Delete"}
    )
    pos_id = create_res.json()["id"]

    res = await client.delete(f"/api/v1/positions/{pos_id}", headers=viewer_headers)
    assert res.status_code in (403, 404)  # 404 because different tenant
