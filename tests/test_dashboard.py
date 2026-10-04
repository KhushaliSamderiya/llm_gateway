def test_dashboard_page_is_served_with_security_headers(client):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_dashboard_assets_come_from_an_allowlist(client):
    assert client.get("/dashboard/assets/dashboard.js").status_code == 200
    assert client.get("/dashboard/assets/dashboard.css").status_code == 200
    assert client.get("/dashboard/assets/secrets.txt").status_code == 404
    assert client.get("/dashboard/assets/..%2Fmain.py").status_code == 404
