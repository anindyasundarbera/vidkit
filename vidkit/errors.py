"""Typed exceptions for vidkit."""

from __future__ import annotations


class VidkitError(Exception):
    """Base class for all vidkit errors."""


class SpecError(VidkitError):
    """The video spec is malformed or references something that does not exist."""


class ToolError(VidkitError):
    """An external tool (ffmpeg, rsvg-convert, a browser, a TTS engine) failed."""


class ProviderError(VidkitError):
    """The data provider could not supply the values the spec asked for."""
