from decimal import Decimal

from app.config import settings

ADMIN = {"Authorization": "Bearer adm_test_admin_key"}


def make_team(client, name="t", budget="50.00"):
    r = client.post(
        "/admin/v1/teams",
        json={"name": name, "monthly_budget_usd": budget},
        headers=ADMIN,
    )
    assert r.status_code == 201
    return r.json()


def make_api_key(client, team_id, **body):
    r = client.post(f"/admin/v1/teams/{team_id}/keys", json=body, headers=ADMIN)
    assert r.status_code == 201
    return r.json()


# ---- who may call the admin API ----
def test_admin_requires_a_key(client):
    r = client.get("/admin/v1/teams")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_admin_key"


def test_wrong_admin_key_is_rejected(client):
    r = client.get("/admin/v1/teams", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_a_team_key_does_not_open_the_admin_api(client, make_key):
    r = client.get("/admin/v1/teams", headers={"Authorization": f"Bearer {make_key()}"})
    assert r.status_code == 401


def test_the_admin_key_does_not_work_as_a_team_key(chat):
    assert chat("adm_test_admin_key").status_code == 401


def test_admin_api_is_disabled_when_no_key_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "")
    r = client.get("/admin/v1/teams", headers=ADMIN)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "admin_disabled"


# ---- teams ----
def test_create_and_list_teams(client):
    r = client.post(
        "/admin/v1/teams",
        json={"name": "growth", "monthly_budget_usd": "25.50"},
        headers=ADMIN,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "growth"
    assert Decimal(str(body["monthly_budget_usd"])) == Decimal("25.50")
    listed = client.get("/admin/v1/teams", headers=ADMIN).json()
    assert [t["name"] for t in listed] == ["growth"]


def test_duplicate_team_name_is_409(client):
    make_team(client, name="dup")
    r = client.post("/admin/v1/teams", json={"name": "dup"}, headers=ADMIN)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "team_exists"


def test_negative_budget_is_400(client):
    r = client.post(
        "/admin/v1/teams",
        json={"name": "neg", "monthly_budget_usd": "-5"},
        headers=ADMIN,
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_request"


def test_blank_team_name_is_400(client):
    r = client.post("/admin/v1/teams", json={"name": "   "}, headers=ADMIN)
    assert r.status_code == 400


def test_keys_of_an_unknown_team_is_404(client):
    r = client.get("/admin/v1/teams/999/keys", headers=ADMIN)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "team_not_found"


def test_raising_the_budget_unblocks_a_team(client, chat):
    team = make_team(client, budget="0.00")
    raw = make_api_key(client, team["id"])["api_key"]
    assert chat(raw).status_code == 429
    r = client.patch(
        f"/admin/v1/teams/{team['id']}",
        json={"monthly_budget_usd": "10.00"},
        headers=ADMIN,
    )
    assert r.status_code == 200
    assert chat(raw).status_code == 200


# ---- keys ----
def test_a_created_key_works_immediately(client, chat):
    team = make_team(client)
    created = make_api_key(client, team["id"], label="app", rate_limit_rpm=10)
    assert created["api_key"].startswith("gw_")
    assert created["rate_limit_rpm"] == 10
    assert chat(created["api_key"]).status_code == 200


def test_listing_keys_never_exposes_secrets(client):
    team = make_team(client)
    created = make_api_key(client, team["id"], label="app")
    r = client.get(f"/admin/v1/teams/{team['id']}/keys", headers=ADMIN)
    item = r.json()[0]
    assert "api_key" not in item and "key_hash" not in item
    assert created["api_key"] not in r.text


def test_revoking_and_reactivating_a_key_takes_effect_immediately(client, chat):
    team = make_team(client)
    created = make_api_key(client, team["id"])
    raw, key_id = created["api_key"], created["id"]
    assert chat(raw).status_code == 200
    client.patch(f"/admin/v1/keys/{key_id}", json={"is_active": False}, headers=ADMIN)
    assert chat(raw).status_code == 401
    client.patch(f"/admin/v1/keys/{key_id}", json={"is_active": True}, headers=ADMIN)
    assert chat(raw).status_code == 200


def test_changing_the_rate_limit_takes_effect(client, chat):
    team = make_team(client)
    created = make_api_key(client, team["id"], rate_limit_rpm=1)
    raw = created["api_key"]
    assert chat(raw).status_code == 200
    assert chat(raw).status_code == 429
    client.patch(
        f"/admin/v1/keys/{created['id']}", json={"rate_limit_rpm": 100}, headers=ADMIN
    )
    assert chat(raw).status_code == 200


def test_updating_a_key_with_an_empty_body_is_400(client):
    team = make_team(client)
    created = make_api_key(client, team["id"])
    r = client.patch(f"/admin/v1/keys/{created['id']}", json={}, headers=ADMIN)
    assert r.status_code == 400


def test_updating_an_unknown_key_is_404(client):
    r = client.patch("/admin/v1/keys/999", json={"is_active": False}, headers=ADMIN)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "key_not_found"
