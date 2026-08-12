"""The inference edge must default to the murakumo fleet alias, not a pod id.

Guards ADR-2607173100 at `lg_animeka.graphs.autopilot`, the module in this
package that holds an inference URL.

This is the first test file for the `lg` Python package — before it, `lg_clj`
had a smoke suite but `lg_animeka` had no tests at all. It therefore covers
only the property it was written for; it is not a general suite for autopilot.

Three properties, one per clause of the ADR's resolution order:

  * an env override still wins (clause 1) — the positive control, expected to
    pass both before and after the change this file lands with;
  * the baked fallback names the fleet endpoint (clause 3);
  * the baked fallback names NO concrete model id (clause 3) — it carries the
    `murakumo-main` alias, which the fleet resolves server-side, so switching
    the fleet's main model does not require a release here.

The module reads its env at import time, so overrides are exercised by
reloading it under a patched environ rather than by monkeypatching attributes
— that is what a real process start does.
"""

from __future__ import annotations

import importlib

import pytest

_MODULE = "lg_animeka.graphs.autopilot"


def _reload():
    return importlib.reload(importlib.import_module(_MODULE))


@pytest.fixture(autouse=True)
def _restore_module():
    """Leave the imported module holding its real defaults afterwards."""
    yield
    _reload()


def test_default_endpoint_is_the_murakumo_fleet(monkeypatch):
    monkeypatch.delenv("VLLM_URL", raising=False)
    assert _reload()._VLLM_URL == "https://api.murakumo.cloud/v1"


def test_default_endpoint_is_not_an_ephemeral_pod_host(monkeypatch):
    """RunPod releases `*.proxy.runpod.net` names and can reassign them.

    A default pointing at one names a host another tenant may come to own.
    `_chat` sends only Content-Type — no credential reaches this endpoint — so
    the exposure is of scene text and prompts rather than of secrets, but a
    default must still not name a host we do not control.
    """
    monkeypatch.delenv("VLLM_URL", raising=False)
    assert "runpod.net" not in _reload()._VLLM_URL


def test_default_model_is_the_alias_not_a_concrete_id(monkeypatch):
    """The fallback must carry the endpoint only — never a pinned model.

    `murakumo-main` is an alias the fleet resolves; naming the model behind it
    would pin this app to whatever was current on the day it was written.
    """
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    mod = _reload()
    assert mod._VLLM_MODEL == "murakumo-main"
    # `tier0-general` was the previous pinned default.
    assert mod._VLLM_MODEL != "tier0-general"


def test_env_override_still_wins(monkeypatch):
    """Positive control: passes before and after the alias change.

    If this ever fails, the fix broke the escape hatch rather than the default.
    """
    monkeypatch.setenv("VLLM_URL", "http://127.0.0.1:4000/v1")
    monkeypatch.setenv("VLLM_MODEL", "some-local-build")
    mod = _reload()
    assert mod._VLLM_URL == "http://127.0.0.1:4000/v1"
    assert mod._VLLM_MODEL == "some-local-build"


def test_trailing_slash_is_stripped_from_override(monkeypatch):
    """Also a positive control — URL joining is `f"{url}/chat/completions"`."""
    monkeypatch.setenv("VLLM_URL", "https://example.invalid/v1/")
    assert _reload()._VLLM_URL == "https://example.invalid/v1"
