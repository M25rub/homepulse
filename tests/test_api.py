from starlette.testclient import TestClient

import main


def client():
    return TestClient(main.create_app())


def test_sample_home_then_run_routine_and_pulse():
    with client() as c:
        assert c.post("/devices/sample").json()["devices_in_home"] == 6
        run = c.post("/run/secure_house").json()
        assert run["results"] and "attempts" in run["results"][0]
        garage = next(r for r in run["results"] if r["device_id"] == "garage")
        assert garage["verified"] is False and garage["outcome"].startswith("FAILED")
        pulse = c.get("/pulse").json()
        assert pulse["total_checks"] == len(run["results"])
        assert any(a["name"] == "Garage door" for a in pulse["attention"])


def test_bad_command_is_rejected():
    with client() as c:
        c.post("/devices/sample")
        r = c.post("/command", json={"target": {"type": "device", "id": "front_lock"}, "capability": "lock", "value": "ajar"})
        assert r.status_code == 400


def test_website_still_served():
    with client() as c:
        assert c.get("/").status_code == 200
