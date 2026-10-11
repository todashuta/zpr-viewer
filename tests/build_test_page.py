"""ヘッドレス検証用のページを zpr-viewer.html から作る。

本体ファイルには検証コードを一切入れない。コピーに tests/inject.js を足すだけ。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
src = (ROOT / "zpr-viewer.html").read_text(encoding="utf-8")
inject = (ROOT / "tests" / "inject.js").read_text(encoding="utf-8")

MARK = "\ninstallUI();\n"
if MARK not in src:
    sys.exit("installUI(); が見つからない。本体の構成が変わったので差し込み位置を確認してください")

out = ROOT / "zpr-viewer.test.html"
out.write_text(src.replace(MARK, MARK + inject, 1), encoding="utf-8")
print(out)
