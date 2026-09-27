"""Tests run against a COPY of data/northwind.db so they never touch the live demo state."""
import shutil

import pytest

import src.config as cfg


@pytest.fixture(scope="session", autouse=True)
def isolated_db(tmp_path_factory):
    live = cfg.DATA / "northwind.db"
    if not live.exists():
        from src.pipeline import build_all
        build_all()
    copy = tmp_path_factory.mktemp("db") / "northwind.db"
    shutil.copy(live, copy)
    cfg.DB_PATH = copy
    yield copy


@pytest.fixture
def con(isolated_db):
    c = cfg.connect()
    yield c
    c.close()
