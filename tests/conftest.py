"""Keep synthetic Git repositories independent of the developer's host policy.

Repository-local hooks and configuration remain active. Authentic native-client
consumer probes run separately, with the real machine configuration intact.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def isolated_git_configuration(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
