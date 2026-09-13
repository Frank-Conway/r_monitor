"""生成 PyInstaller 版本资源 version_info.txt。

版本号单一来源为 r_monitor.config.APP_VERSION；本脚本把版本号展开为
VSVersionInfo 所需的 4 段元组与字符串字段，避免手动维护版本号漂移。

用法（在项目根目录执行，build.ps1 会自动调用）：
    python tools\\generate_version_info.py
"""
import sys
from pathlib import Path

# 允许从任意位置运行本脚本时都能导入项目包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from r_monitor import config  # noqa: E402

_OUT = Path(__file__).resolve().parents[1] / "version_info.txt"


def _version_tuple(version: str) -> tuple:
    """把 "0.1.0" 展开成 (0, 1, 0, 0)。"""
    parts = [int(x) for x in version.split(".")]
    return tuple((parts + [0, 0, 0, 0])[:4])


def render(version: str) -> str:
    ver = _version_tuple(version)
    return f'''# UTF-8
# 本文件由 tools/generate_version_info.py 自动生成，请勿手动修改。
# 版本号单一来源：r_monitor.config.APP_VERSION（当前 {version}）。
# 供 PyInstaller EXE(version=...) 使用的 Windows 版本资源。
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver},
    prodvers={ver},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'080404B0',  # 语言 0804（简体中文）+ 代码页 04B0（1200 = UTF-16）
        [
          StringStruct(u'CompanyName', u'r_monitor'),
          StringStruct(u'FileDescription', u'r_monitor - Windows 系统监控工具'),
          StringStruct(u'FileVersion', u'{version}'),
          StringStruct(u'InternalName', u'r_monitor'),
          StringStruct(u'OriginalFilename', u'r_monitor.exe'),
          StringStruct(u'ProductName', u'r_monitor'),
          StringStruct(u'ProductVersion', u'{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])  # 1033 = 英语(美国) LCID，1200 = UTF-16 代码页
  ]
)
'''


def main():
    _OUT.write_text(render(config.APP_VERSION), encoding="utf-8")
    print(f"已生成 {_OUT}（版本 {config.APP_VERSION}）")


if __name__ == "__main__":
    main()
