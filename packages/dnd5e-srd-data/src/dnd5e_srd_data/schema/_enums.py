"""Enums shared across SRD schema models."""

from __future__ import annotations

from enum import StrEnum


class SrdVersion(StrEnum):
    SRD_5_1 = "5.1"
    SRD_5_2 = "5.2"


class TranslatorSource(StrEnum):
    FOUNDRY = "foundry"
    # AI_OPEN5E = "open5e_ai"  # deferred; reintroduce per backlog [engine] AI translator


class LicenseTag(StrEnum):
    CC_BY_4 = "CC-BY-4.0"
