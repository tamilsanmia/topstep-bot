from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Type

from topstepbot.strategy.interface import IStrategy

logger = logging.getLogger(__name__)


def load_strategy_class(name: str, strategy_path: str | Path) -> Type[IStrategy]:
    base = Path(strategy_path)
    module_file = base / f"{name}.py"
    if not module_file.exists():
        raise FileNotFoundError(f"Strategy file not found: {module_file}")

    module_name = f"user_strategy_{name}"
    spec = importlib.util.spec_from_file_location(module_name, module_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load strategy module from {module_file}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    for attr in dir(module):
        if attr.startswith("_"):
            continue
        obj = getattr(module, attr)
        if isinstance(obj, type) and issubclass(obj, IStrategy) and obj is not IStrategy:
            logger.info("Loaded strategy class %s from %s", obj.__name__, module_file)
            return obj

    raise ImportError(f"No IStrategy subclass found in {module_file}")
