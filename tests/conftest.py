"""Shared test setup: paths and app fixture, applied before any test module
imports the application (pytest imports conftest first)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parent / "_tmp_data"
os.environ["IDL_DATA_DIR"] = str(TEST_ROOT / "data")
os.environ["IDL_STORAGE_DIR"] = str(TEST_ROOT / "storage")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from idl import create_app, db, security  # noqa: E402


@pytest.fixture(scope="session")
def app():
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)
    application = create_app()
    application.config["TESTING"] = True
    with application.app_context():
        db.ensure_schema()
        # one admin per test module's credentials
        db.create_admin("testadmin", security.hash_password("correct-horse-battery-staple"))
        db.create_admin("featureadmin", security.hash_password("another-long-test-password"))
    return application


@pytest.fixture()
def client(app):
    return app.test_client()
