"""Avatar resolution.

The deployed app died with MediaFileStorageError because the container was
built without images/, so the placeholder every player fell back to was not
there. Resolution has to answer "no picture", never "a path that is not there".
"""

from __future__ import annotations

import pytest

from wingspan import avatars


@pytest.fixture()
def uploads(tmp_path, monkeypatch):
    directory = tmp_path / "uploads"
    monkeypatch.setenv("WINGSPAN_IMAGES", str(directory))
    return directory


def test_upload_dir_follows_the_environment(uploads):
    assert avatars.upload_dir() == uploads


def test_upload_dir_falls_back_to_the_bundled_directory(monkeypatch):
    monkeypatch.delenv("WINGSPAN_IMAGES", raising=False)
    assert avatars.upload_dir() == avatars.BUNDLED_DIR


def test_a_stored_picture_resolves_from_the_upload_directory(uploads):
    uploads.mkdir()
    (uploads / "p1_ant.png").write_bytes(b"png")
    assert avatars.resolve("p1_ant.png") == uploads / "p1_ant.png"


def test_a_windows_path_resolves_to_its_filename(uploads):
    uploads.mkdir()
    (uploads / "ant.png").write_bytes(b"png")
    assert avatars.resolve(r"C:\\Users\\ant\\images\\ant.png") == uploads / "ant.png"


def test_a_missing_picture_falls_back_to_the_placeholder(uploads):
    assert avatars.resolve("gone.png") == avatars.BUNDLED_DIR / avatars.DEFAULT_AVATAR_NAME


def test_no_picture_at_all_falls_back_to_the_placeholder(uploads):
    assert avatars.resolve(None) == avatars.BUNDLED_DIR / avatars.DEFAULT_AVATAR_NAME


def test_resolution_is_none_when_even_the_placeholder_is_absent(tmp_path, monkeypatch):
    """The exact deployment shape that crashed: no images anywhere."""
    monkeypatch.setenv("WINGSPAN_IMAGES", str(tmp_path / "uploads"))
    monkeypatch.setattr(avatars, "BUNDLED_DIR", tmp_path / "bundled")

    assert avatars.default_avatar() is None
    assert avatars.resolve(None) is None
    assert avatars.resolve("ant.png") is None


def test_the_placeholder_ships_with_the_repository():
    assert (avatars.BUNDLED_DIR / avatars.DEFAULT_AVATAR_NAME).is_file()


def test_saving_creates_the_upload_directory_and_returns_a_bare_name(uploads):
    name = avatars.save("p1", "ant.png", b"png-bytes")

    assert name == "p1_ant.png"
    assert (uploads / name).read_bytes() == b"png-bytes"
    assert avatars.resolve(name) == uploads / name


def test_saving_keeps_uploads_out_of_the_bundled_directory(uploads):
    avatars.save("p1", "ant.png", b"png-bytes")
    assert not (avatars.BUNDLED_DIR / "p1_ant.png").exists()


def test_an_upload_shadows_a_bundled_picture_of_the_same_name(uploads):
    uploads.mkdir()
    (uploads / avatars.DEFAULT_AVATAR_NAME).write_bytes(b"newer")
    assert avatars.default_avatar() == uploads / avatars.DEFAULT_AVATAR_NAME
