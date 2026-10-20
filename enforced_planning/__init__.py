"""Importable package surfaces for enforced-planning."""

from __future__ import annotations

from enforced_planning import coordination_claims as _coordination_claims

# ChatGPT operating through Remote Desktop Commander is a portable claim owner,
# not a native hook client. Registering the owner here keeps persisted ChatGPT
# claims readable by ordinary lifecycle/push-safety processes after the bridge
# command exits, while native hook dispatch remains unchanged.
_CHATGPT_AGENT = "chatgpt"
_CHATGPT_SESSION_ENV = "CHATGPT_SESSION_ID"
if _CHATGPT_AGENT not in _coordination_claims.SUPPORTED_AGENTS:
    _coordination_claims.SUPPORTED_AGENTS = (*_coordination_claims.SUPPORTED_AGENTS, _CHATGPT_AGENT)
_coordination_claims.SESSION_ENV_KEYS[_CHATGPT_AGENT] = (_CHATGPT_SESSION_ENV,)
_coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS[_CHATGPT_AGENT] = _CHATGPT_SESSION_ENV
