from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap_terminal_nodes.sh"


def test_bootstrap_docker_config_does_not_reset_invalid_daemon_json():
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "except Exception:" not in text
    assert "json.loads(text)" in text
    assert "Refuse to overwrite Docker daemon config" in text


def test_bootstrap_defaults_to_acceptance_network_profile():
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'NETWORK_PROFILE="${NETWORK_PROFILE:-acceptance}"' in text
    assert "172.16 management addresses; current -> 10.112 fallback addresses" in text
