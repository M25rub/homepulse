import json

import core


def test_flaky_device_recovers_by_retry(sample_home):
    device = sample_home["devices"]["kitchen_light"]
    detail = core.verify_detailed(device, "power", "off")
    assert detail["outcome"] == "recovered by retry"
    assert [a["matched"] for a in detail["attempts"]] == [False, True]


def test_cloud_down_device_recovers_by_local_fallback(sample_home):
    detail = core.verify_detailed(sample_home["devices"]["back_lock"], "lock", "locked")
    assert detail["outcome"] == "recovered by local fallback"
    assert [a["route"] for a in detail["attempts"]] == ["cloud", "cloud", "local"]


def test_offline_device_is_reported_failed_never_confirmed(sample_home):
    detail = core.verify_detailed(sample_home["devices"]["garage"], "openclose", "closed")
    assert detail["outcome"] == core.FAILED_OUTCOME and not detail["verified"]
    assert len(detail["attempts"]) == 3


def test_values_are_validated():
    assert core.clean_value("brightness", "30") == 30
    for capability, bad in [("brightness", 150), ("lock", "ajar"), ("nonsense", "x"), ("temperature", "warm")]:
        try:
            core.clean_value(capability, bad)
        except ValueError:
            continue
        raise AssertionError(f"{capability}={bad} should have been rejected")


def test_save_is_atomic_and_keeps_a_backup(fresh_home, sample_home):
    core.save_home(sample_home)
    core.save_home(sample_home)
    assert fresh_home.exists() and fresh_home.with_name("home.json.bak").exists()
    assert not list(fresh_home.parent.glob(".home-*.tmp"))          # no temp files left behind


def test_damaged_file_recovers_from_backup_instead_of_starting_empty(fresh_home, sample_home):
    core.save_home(sample_home)
    core.save_home(sample_home)                                      # now a good .bak exists
    fresh_home.write_text("{ this is not json", encoding="utf-8")   # simulate a crash mid-write
    recovered = core.load_home()
    assert len(recovered["devices"]) == len(sample_home["devices"])
    assert list(fresh_home.parent.glob("home.damaged-*.json"))      # the broken file was kept for inspection


def test_run_actions_does_not_change_the_real_home(sample_home):
    before = json.dumps(sample_home["devices"], sort_keys=True)
    core.run_actions(sample_home, core.clean_actions([{"target": {"type": "all", "id": ""}, "capability": "power", "value": "off"}]))
    assert json.dumps(sample_home["devices"], sort_keys=True) == before


def test_pulse_flags_the_failing_device_and_groups_by_room(sample_home):
    # Kitchen: a flaky light and a coffee maker; Garage: offline. Run the secure_house routine twice.
    for _ in range(2):
        results, _unmatched = core.run_actions(sample_home, sample_home["routines"]["secure_house"]["actions"])
        core.record_history(sample_home, "secure_house", results)
    report = core.pulse(sample_home)
    urgent = [a["name"] for a in report["attention"] if a["level"] == "urgent"]
    assert "Garage door" in urgent
    assert report["score"] is not None and report["score"] < 100
    assert report["saved_by_recovery"] > 0
    assert "need" in report["headline"]


def test_pulse_with_no_history_says_so(sample_home):
    report = core.pulse(sample_home)
    assert report["score"] is None and "No commands" in report["headline"]


def test_alexa_discovery_json_import():
    payload = {"event": {"payload": {"endpoints": [
        {"endpointId": "lamp-1", "friendlyName": "Desk lamp", "displayCategories": ["LIGHT"],
         "capabilities": [{"interface": "Alexa.PowerController"}, {"interface": "Alexa.BrightnessController"},
                          {"interface": "Alexa.EndpointHealth"}]},
        {"endpointId": "x", "friendlyName": "Mystery", "capabilities": [{"interface": "Alexa.Unknown"}]},
    ]}}}
    home = core.load_home()
    added, skipped, notes = core.import_alexa(home, payload)
    assert [d["name"] for d in added] == ["Desk lamp"] and skipped == 1
    assert added[0]["capabilities"] == ["power", "brightness"] and added[0]["category"] == "light"
    assert notes == ["Alexa.Unknown"]
