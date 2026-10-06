"""Provider (plugin) interface.

A *provider* is a plain Python module named in the spec. It may supply:

* ``datasets(ctx) -> dict[str, Any]`` — the data each chart panel is drawn from.
* ``panels() -> dict[str, (kind, dataset)]`` — named panels assembled from
  built-in kinds (or custom kinds it registers).
* ``stills(ctx) -> dict[str, Path]`` — named still images a scene can reference.
* ``extra_voices`` — not used yet.
* ``register()`` — called once so the provider can add custom panel kinds.

Only ``datasets`` is usually needed. vidkit loads the module from the spec's
folder without installing anything; the module may import the host project's
libraries freely (that is the point — providers are the bridge to your data).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .context import Context
from .errors import ProviderError


def load_provider(name: str, root: Path) -> tuple[ModuleType, bool]:
    """Load ``<root>/<name>.py`` as a module. Returns (module, was_loaded)."""
    if not name:
        raise ProviderError("empty provider name")
    path = (root / name).with_suffix(".py")
    if not path.exists():
        path = root / name
    if not path.exists():
        raise ProviderError(f"provider module not found: {path}")
    mod_name = f"vidkit_provider_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ProviderError(f"cannot load provider: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    # make the provider able to import sibling modules in the same folder
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec.loader.exec_module(module)
    return module, True


def call_provider(module: ModuleType | None, func: str, *args, default: Any = None) -> Any:
    if module is None:
        return default
    fn = getattr(module, func, None)
    if fn is None:
        return default
    return fn(*args)


def collect_datasets(module: ModuleType | None, ctx: Context) -> dict[str, Any]:
    if module is None:
        return {}
    fn = getattr(module, "datasets", None)
    if fn is None:
        return {}
    try:
        data = fn(ctx)
    except Exception as exc:  # surface provider bugs clearly
        raise ProviderError(f"provider.datasets() failed: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderError("provider.datasets() must return a dict")
    return data


def collect_panels(module: ModuleType | None) -> dict[str, tuple[str, str, dict]]:
    """provider.panels() -> {name: (kind, dataset_key, options)}."""
    if module is None:
        return {}
    fn = getattr(module, "panels", None)
    if fn is None:
        return {}
    out = fn()
    if not isinstance(out, dict):
        raise ProviderError("provider.panels() must return a dict")
    normalised: dict[str, tuple[str, str, dict]] = {}
    for name, value in out.items():
        if isinstance(value, dict):
            normalised[name] = (str(value["kind"]), str(value.get("dataset", name)),
                                dict(value.get("options") or {}))
        elif isinstance(value, (list, tuple)):
            kind, dataset = value[0], value[1]
            options = value[2] if len(value) > 2 else {}
            normalised[name] = (str(kind), str(dataset), dict(options or {}))
        else:
            raise ProviderError(f"provider.panels()[{name!r}] must be a dict or tuple")
    return normalised


def collect_stills(module: ModuleType | None, ctx: Context) -> dict[str, Path]:
    if module is None:
        return {}
    fn = getattr(module, "stills", None)
    if fn is None:
        return {}
    raw = fn(ctx)
    return {str(k): Path(v) for k, v in (raw or {}).items()}
