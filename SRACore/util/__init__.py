import importlib
import sys
from pathlib import Path

import SRACore.util.strutil as strutil
import SRACore.util.sys_util as sys_util

def dynamic_import(package: str):
    """动态导入包"""
    try:
        # 扫描 package 包下的所有 .py 文件，导入每个模块
        for file in Path(package).glob("*.py"):
            importlib.import_module(f"{package}.{file.stem}")
    except ModuleNotFoundError:
        pass

def reload_package(package: str):
    """重新加载包"""
    try:
        for file in Path(package).glob("*.py"):
            module_name = f"{package}.{file.stem}"
            if module_name in sys.modules:
                importlib.reload(sys.modules[module_name])
            else:
                importlib.import_module(module_name)
    except ModuleNotFoundError:
        pass

__all__ = [
    "strutil",
    "sys_util",
    "dynamic_import",
    "reload_package",
]
