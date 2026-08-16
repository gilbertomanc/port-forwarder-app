"""Tests de WslIpProvider: cache y parseo de hostname -I."""

from __future__ import annotations

from unittest import mock

import pytest

from src.providers.wsl_ip_provider import WslIpProvider


def test_get_ip_parses_first_ip():
    p = WslIpProvider(wsl_exe="wsl.exe", cache_ttl=5)
    with mock.patch("src.providers.wsl_ip_provider.sp.run") as run:
        run.return_value = mock.Mock(returncode=0,
                                     stdout="172.18.0.2 172.18.0.3\n")
        assert p.get_ip("ubuntu") == "172.18.0.2"


def test_get_ip_failure_returns_none():
    p = WslIpProvider(wsl_exe="wsl.exe")
    with mock.patch("src.providers.wsl_ip_provider.sp.run") as run:
        run.return_value = mock.Mock(returncode=1, stdout="", stderr="x")
        assert p.get_ip("ubuntu") is None


def test_get_ip_no_output_returns_none():
    p = WslIpProvider(wsl_exe="wsl.exe")
    with mock.patch("src.providers.wsl_ip_provider.sp.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout="\n")
        assert p.get_ip("ubuntu") is None


def test_cache_avoids_repeated_calls():
    p = WslIpProvider(wsl_exe="wsl.exe", cache_ttl=60)
    with mock.patch("src.providers.wsl_ip_provider.sp.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout="172.18.0.2\n")
        p.get_ip("ubuntu")
        p.get_ip("ubuntu")
        assert run.call_count == 1


def test_invalidate_clears_cache():
    p = WslIpProvider(wsl_exe="wsl.exe", cache_ttl=60)
    with mock.patch("src.providers.wsl_ip_provider.sp.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout="172.18.0.2\n")
        p.get_ip("ubuntu")
        p.invalidate("ubuntu")
        p.get_ip("ubuntu")
        assert run.call_count == 2


def test_get_all_ips_dedups_distros():
    p = WslIpProvider(wsl_exe="wsl.exe")
    with mock.patch.object(p, "get_ip", side_effect=lambda d: f"10.0.0.{len(d)}"):
        ips = p.get_all_ips(["a", "b", "a"])
    assert ips == {"a": "10.0.0.1", "b": "10.0.0.1"}
