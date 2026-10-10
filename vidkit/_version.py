"""The single source of truth for the vidkit version.

Every consumer — the package metadata (``pyproject.toml`` reads this attribute
dynamically), ``vidkit.__version__``, the CLI ``--version``, the provenance and
job manifests — imports the same string from here. Bump it in exactly one place
or the distribution and the reported version drift apart.
"""

__version__ = "1.0.0"
