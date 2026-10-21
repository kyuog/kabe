"""Proveedores de fondos de Kabe."""

from __future__ import annotations

from .base import Provider
from .github import GitHubProvider
from .local import LocalProvider

__all__ = ["Provider", "GitHubProvider", "LocalProvider"]
