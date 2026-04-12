"""Audit logging helpers shared across route modules."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import sys
from typing import Optional

from fastapi import Request


AUDIT_LOGGER = logging.getLogger("questline.audit")


def _trusted_proxy_networks_from_env() -> tuple[ipaddress._BaseNetwork, ...]:
    configured = os.getenv("QUESTLINE_TRUSTED_PROXIES", "")
    networks = []
    for raw_value in configured.split(","):
        value = raw_value.strip()
        if not value:
            continue
        networks.append(ipaddress.ip_network(value, strict=False))
    return tuple(networks)


def _configure_audit_logger():
    audit_log_path = os.getenv("QUESTLINE_AUDIT_LOG_PATH")
    audit_log_level_name = os.getenv("QUESTLINE_AUDIT_LOG_LEVEL", "INFO").upper()
    audit_log_level = getattr(logging, audit_log_level_name, logging.INFO)

    AUDIT_LOGGER.setLevel(audit_log_level)
    AUDIT_LOGGER.propagate = True
    if not any(
        isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        for handler in AUDIT_LOGGER.handlers
    ):
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(audit_log_level)
        stream_handler.setFormatter(logging.Formatter("%(message)s"))
        AUDIT_LOGGER.addHandler(stream_handler)
    if audit_log_path and not any(
        isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", None) == os.path.abspath(audit_log_path)
        for handler in AUDIT_LOGGER.handlers
    ):
        file_handler = logging.FileHandler(audit_log_path)
        file_handler.setLevel(audit_log_level)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        AUDIT_LOGGER.addHandler(file_handler)


def _request_client_ip(request: Optional[Request]) -> str:
    if request is None:
        return "unknown"
    client = getattr(request, "client", None)
    peer_host = client.host if client and client.host else "unknown"
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for and peer_host != "unknown":
        try:
            peer_ip = ipaddress.ip_address(peer_host)
        except ValueError:
            peer_ip = None
        app = request.scope.get("app")
        trusted_proxy_networks = getattr(getattr(app, "state", None), "trusted_proxy_networks", None)
        if trusted_proxy_networks is None:
            trusted_proxy_networks = _trusted_proxy_networks_from_env()
        if peer_ip and any(peer_ip in network for network in trusted_proxy_networks):
            forwarded_host = forwarded_for.split(",", 1)[0].strip()
            if forwarded_host:
                try:
                    return str(ipaddress.ip_address(forwarded_host))
                except ValueError:
                    return peer_host
    return peer_host


def _audit_log(
    event: str,
    request: Optional[Request] = None,
    actor_user_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    board_id: Optional[int] = None,
    outcome: str = "success",
    reason: Optional[str] = None,
    email: Optional[str] = None,
    details: Optional[dict] = None,
):
    payload = {
        "event": event,
        "actor_user_id": actor_user_id,
        "target_user_id": target_user_id,
        "board_id": board_id,
        "remote_ip": _request_client_ip(request),
        "outcome": outcome,
    }
    if reason is not None:
        payload["reason"] = reason
    if email is not None:
        payload["email"] = email
    if details:
        payload.update(details)
    AUDIT_LOGGER.info(json.dumps(payload, sort_keys=True, separators=(",", ":")))
