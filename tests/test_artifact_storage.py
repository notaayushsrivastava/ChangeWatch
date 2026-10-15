from pathlib import Path

from app.services.artifact_storage import ArtifactStorage


def test_local_artifact_storage_round_trip(tmp_path: Path):
    storage = ArtifactStorage(base_dir=str(tmp_path))
    payload = b"fake-png-data"

    filename = storage.save_screenshot(payload, "monitor-1", "version-1")

    assert storage.exists(filename)
    assert storage.get_artifact_path(filename) is not None
    assert storage.read_bytes(filename) == payload
    assert storage.delete_artifact(filename) is True
    assert storage.exists(filename) is False


def test_artifact_storage_rejects_path_traversal(tmp_path: Path):
    storage = ArtifactStorage(base_dir=str(tmp_path))

    assert storage.read_bytes("../secret.png") is None
    assert storage.read_bytes(r"..\secret.png") is None
    assert storage.exists("/etc/passwd") is False
