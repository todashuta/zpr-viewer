"""zpr-viewer.html のヘッドレステスト。Chrome を起動して実描画まで確かめる。

    python3 tests/test_zpr_viewer.py

前提:
  - tests/samples/*.zpr がある（無ければ tests/make_samples.py を Blender で実行）
  - Google Chrome が入っている（CHROME 環境変数でパス上書き可）

ビューア本体には検証コードを入れない。build_test_page.py が作った
zpr-viewer.test.html（本体 + tests/inject.js）に対して検証する。
"""

import json
import os
import re
import struct
import subprocess
import sys
import time
import traceback
import urllib.parse
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "tests" / "samples"
PAGE = ROOT / "zpr-viewer.test.html"

CHROME = os.environ.get(
    "CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

FLAGS = [
    "--headless=new", "--use-gl=angle", "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader", "--allow-file-access-from-files",
    "--no-first-run", "--disable-extensions",
    "--window-size=1280,800", "--virtual-time-budget=20000",
]


def read_page(query):
    """テストページを開いて、inject.js が <pre> に出した JSON を返す。"""
    url = f"file://{PAGE}?{urllib.parse.urlencode(query)}"
    proc = subprocess.run([CHROME, *FLAGS, "--dump-dom", url],
                          capture_output=True, text=True, timeout=180)
    found = re.search(r"<pre[^>]*>(.*?)</pre>", proc.stdout, re.S)
    if not found:
        raise AssertionError(f"テストページが応答しない\n{proc.stdout[:400]}\n{proc.stderr[-400:]}")
    return json.loads(unescape(found.group(1)))


def open_sample(name, mode=0, case=None, **extra):
    query = {"f": f"tests/samples/{name}", "mode": mode}
    if case:
        query["case"] = case
    query.update(extra)
    result = read_page(query)
    if "ERROR" in result:
        raise AssertionError(f"{name}: ページ側で例外 {result}")
    return result


def coverage(result, key="coverage"):
    return float(result[key].rstrip("%"))


def require_samples():
    missing = [n for n in NEEDED if not (SAMPLES / n).exists()]
    if missing:
        print("  skip: サンプルが無い → tests/make_samples.py を Blender で実行してください:", missing)
        return False
    return True


def make_broken_samples():
    """壊れた入力用。本体サンプルから毎回作り直す（末尾だけ切る等が目的）。"""
    whole = (SAMPLES / "cube_color.zpr").read_bytes()
    (SAMPLES / "truncated.zpr").write_bytes(whole[:len(whole) * 6 // 10])
    (SAMPLES / "not_zpr.bin").write_bytes(b"\x00\x01\x02\x03" * 64)


def _chunk(tag, body):
    return bytes([tag]) + struct.pack("<I", len(body) + 5) + body


def build_plane_zpr(texture_name, jpeg):
    """アドオンと同じ書式で「平面 1 枚 + テクスチャ 1 枚」を手で組む。
    テクスチャ名のエンコーディングは Blender では選べないので、検証ファイルを自由に作るために必要。"""
    def vertex(x, y):
        return struct.pack("<fff", x, y, 0.0) + bytes([255, 255, 255]) + struct.pack("<i", -1)

    verts = b"".join(vertex(x, y) for x, y in ((-50, -50), (50, -50), (-50, 50), (50, 50)))

    def tri(a, b, c):
        return struct.pack("<III", a, b, c) + bytes([255] * 9) + struct.pack("<i", 0)

    tris = tri(0, 1, 3) + tri(0, 3, 2)

    def face_uv(tex, coords):
        return struct.pack("<i", tex) + struct.pack("<fff", *[c[0] for c in coords]) \
            + struct.pack("<fff", *[c[1] for c in coords])

    uvs = face_uv(0, [(0, 0), (1, 0), (1, 1)]) + face_uv(0, [(0, 0), (1, 1), (0, 1)])
    textures = (struct.pack("<I", 1) + struct.pack("<I", len(texture_name)) + texture_name
                + struct.pack("<I", 0) + bytes([1, 1, 1, 0])
                + struct.pack("<II", 2, len(jpeg)) + jpeg)
    creator = b"Pi Test Exp"
    return (struct.pack("<H", 0x03AA) + struct.pack("<I", len(creator)) + creator
            + bytes([3, 2]) + bytes([0x02, 0xFF, 0xFF, 0xFF])
            + _chunk(0x0A, verts) + _chunk(0x15, tris) + _chunk(0x1F, textures)
            + _chunk(0x28, b"") + _chunk(0x32, uvs))


def make_named_sample(name, texture_name):
    """指定バイト列をテクスチャ名に埋めたサンプルを作る。"""
    path = SAMPLES / name
    path.write_bytes(build_plane_zpr(texture_name, (SAMPLES / "uvprobe.jpg").read_bytes()))
    return path


NEEDED = ["cube_color.zpr", "two_cubes.zpr", "plane_uv.zpr", "plane_uv_pair.zpr",
          "mixed.zpr", "grid.zpr", "uvprobe.jpg"]


def require(name, hint):
    """make_samples.py では再生成できないサンプル用の skip 判定"""
    if not (SAMPLES / name).exists():
        print(f"  skip: {name} が無い → {hint}")
        return True
    return False


def test_実アドオン出力でテクスチャ面と色だけの面が両方描ける():
    # blender_out.zpr は Blender アドオンが書き出した実データそのもの。
    # テクスチャ面 2 + 色だけで塗る面 12 の混合ケース
    if require("blender_out.zpr", "アドオンから手動でエクスポートして tests/samples/ に置く"):
        return
    r = open_sample("blender_out.zpr", mode=1)
    assert r["verts"] == 12, r
    assert r["faces"] == 14, r
    assert r["texGroups"] == 1, f"テクスチャ面がグループになっていない {r}"
    assert r["decodedTex"] == [0], f"JPEG がデコードされていない {r}"
    assert r["plainFaces"] == 12, f"UV の無い面が描画対象から消えている {r}"
    assert coverage(r) > 0.5, f"モデルが画面に映っていない {r}"
    assert r["glError"] == 0, r


def test_実アドオン出力のUV平面にテクスチャが貼れる():
    if require("plane_only.zpr", "アドオンから手動でエクスポートして tests/samples/ に置く"):
        return
    r = open_sample("plane_only.zpr", mode=1)
    assert r["faces"] == 2, r
    assert r["texGroups"] == 1, r
    assert r["decodedTex"] == [0], r
    assert r["plainFaces"] == 0, f"UV のない面が混ざっている {r}"
    assert coverage(r) > 0.5, f"平面が画面を覆っていない {r}"
    assert r["glError"] == 0, r


def test_はてなキーでキー一覧が出て閉じる():
    r = open_sample("cube_color.zpr", mode=0, case="help")
    h = r["help"]
    assert h["shown"], f"? キーで一覧が出ない {r}"
    assert h["rows"] >= 10, f"一覧の内容が足りない {h}"
    # 読み込み画面は一行ヒントのまま（表にしたのは見づらいので戻した）
    assert h["dropTable"] == 0, f"読み込み画面が表になっている {h}"
    assert "キー 1〜5" in h["dropHint"], f"読み込み画面のヒントが消えている {h}"
    # 3D 表示中の左下メモに ? への導線が残っていれば、一覧の存在に辿り着ける
    assert "?" in h["tipsText"] and "ショートカット" in h["tipsText"], f"3D 画面に ? の案内がない {h}"
    assert h["closedByEsc"], f"Esc で閉じられない {h}"
    assert h["openAgain"] and h["closedByQuestion"], f"? で開け閉めできない {h}"


def test_テクスチャはクリックで拡大表示になる():
    r = open_sample("plane_uv.zpr", mode=1, case="lightbox")
    lb = r["lightbox"]
    assert lb["thumbs"] == 1, f"サムネイルが出ていない {r}"
    assert lb["shown"] and lb["hasImage"], f"クリックで拡大表示にならない {r}"
    assert lb["hasDownload"], f"ダウンロードの導線が消えている {r}"
    assert lb["closed"], f"拡大表示が閉じられない {r}"
    assert lb["imgRadius"] in ("0px", "0%"), f"拡大画像の角が丸い（縁が読めない）{lb}"
    assert lb["imgBorder"] == "0px", f"拡大画像に枠が付いている（縁が読めない）{lb}"


def test_頂点色付き立方体が読み込んだ規模のまま描画される():
    r = open_sample("cube_color.zpr", mode=0)
    assert r["verts"] == 8, r
    assert r["faces"] == 12, r
    assert coverage(r) > 0.5, f"モデルが画面に映っていない {r}"
    assert r["glError"] == 0, r


def test_色のないメッシュも白く塗れて見える():
    r = open_sample("two_cubes.zpr", mode=0)
    assert r["faces"] == 24, r
    assert all(v > 60 for v in r["avg"]), f"黒いまま（白塗りされていない）{r}"
    assert coverage(r) > 0.5, r


def test_テクスチャの_JPEG_がデコードされて面に貼られる():
    r = open_sample("plane_uv.zpr", mode=1)
    assert r["texGroups"] == 1, r
    assert r["decodedTex"] == [0], f"JPEG がデコードされていない {r}"
    assert coverage(r) > 1, r


def test_画像の_4_隅が対応する_UV_位置に貼られる():
    # 無照明で読む（ライティングの色かみを除外して画像そのものの色を見る）
    r = open_sample("plane_uv.zpr", mode=3, case="uvcorners")
    assert r["inView"], f"サンプル点が画面外 {r}"
    for corner in r["corners"]:
        assert corner["colorOk"], f"テクスチャが別の場所に貼れている {corner}"
    assert r["texPass"], r


def test_UVが反転や上下逆なしで正しい向きに貼られる():
    r = open_sample("plane_uv.zpr", mode=4, case="uvcorners")
    assert r["inView"], f"サンプル点が画面外 {r}"
    for corner in r["corners"]:
        assert corner["ok"], f"UV の向きが違いそう {corner}"
    assert r["uvPass"], r


def test_画像を共有する平面でもテクスチャは重複しない():
    r = open_sample("plane_uv_pair.zpr", mode=1)
    assert r["faces"] == 4, r
    assert r["decodedTex"] == [0], f"テクスチャが 1 枚しか要らないところで複数デコードしている {r}"


def test_面UVのない面は頂点色で描画対象に残る():
    r = open_sample("mixed.zpr", mode=1)
    assert r["texGroups"] == 1, r
    assert r["plainFaces"] == 12, f"テクスチャ無し面が消えている {r}"
    assert coverage(r) > 0.5, r


def test_ZPrint_由来の_cp932_テクスチャ名が文字化けしない():
    # Blender 側のエクスポートアドオンは cp932 で名前を書く
    make_named_sample("name_cp932.zpr", "チェッカー".encode("cp932"))
    r = open_sample("name_cp932.zpr", mode=1)
    assert r["decodedTex"] == [0], f"テクスチャが読めない {r}"
    assert r["texNames"] == ["チェッカー"], f"日本語名が化けている {r['texNames']}"


def test_UTF8_のテクスチャ名はそのまま通る():
    make_named_sample("name_utf8.zpr", "uvprobe チェッカー".encode("utf-8"))
    r = open_sample("name_utf8.zpr", mode=1)
    assert r["texNames"] == ["uvprobe チェッカー"], f"UTF-8 名を壊している {r['texNames']}"


def test_名前が読めないバイト列でも開ける():
    # どの文字コードでもない字节列でも、例外ではなく中身だけ表示する
    make_named_sample("name_binary.zpr", b"\xff\xfe\x81\x81\x00\x81")
    r = open_sample("name_binary.zpr", mode=1)
    assert "ERROR" not in r, r
    assert r["texGroups"] == 1, r


def test_ワイヤーフレームは使ったときだけ構築される():
    plain = open_sample("cube_color.zpr", mode=0, case="wire", wire="0")
    assert plain["wireBuf"] is False, f"使わないワイヤーバッファを作っている {plain}"
    wire = open_sample("cube_color.zpr", mode=2)
    assert wire["wireBuf"] is True, f"ワイヤーモードで線が引けない {wire}"


def test_三角形の頂点索引は頂点バッファの範囲内に収まる():
    # 範囲外だと実機の drawElements は INVALID_OPERATION で何も描かない。
    # SwiftShader だけは化けたものを描いてしまうので、数値で押さえる
    for name in ("cube_color.zpr", "two_cubes.zpr", "plane_uv.zpr", "plane_uv_pair.zpr", "mixed.zpr", "grid.zpr"):
        b = open_sample(name, mode=2, case="buffers")["buffers"]
        assert b["idxAllMax"] < b["posVerts"], f"{name}: 頂点索引が範囲外 {b}"
        assert b["wireMax"] < b["posVerts"], f"{name}: ワイヤー索引が範囲外 {b}"


def test_色モードの上にワイヤーが重なる():
    off = open_sample("cube_color.zpr", mode=0, case="wire", wire="0")
    on = open_sample("cube_color.zpr", mode=0, case="wire")
    assert off["wirePx"] < 100, f"ワイヤー重ねを消したのに線が残っている {off}"
    assert on["wirePx"] > 200, f"色モードに線が重ならない {on}"
    assert coverage(on, "coverageNoGrid") > 0.5, f"線を重ねると面が見えなくなる {on}"


def test_テクスチャの上にワイヤーが重なる():
    on = open_sample("plane_uv.zpr", mode=1, case="wire")
    assert on["wirePx"] > 200, f"テクスチャ面に線が重ならない {on}"
    assert coverage(on, "coverageNoGrid") > 0.5, f"線を重ねるとテクスチャが見えなくなる {on}"


def test_ワイヤーフレームの線が背景に対して見える():
    # 線色は背景の輝度で裏返る。方眼を消した状態でその色のピクセルを数える
    r = open_sample("cube_color.zpr", mode=2, case="wire")
    assert r["wirePx"] > 200, f"ワイヤー線が描画されていない {r}"
    assert coverage(r, "coverageNoGrid") > 0.5, f"ワイヤーモードでメッシュが映っていない {r}"


def test_フラットモードはライティングを通さない():
    lit = open_sample("cube_color.zpr", mode=0)
    flat = open_sample("cube_color.zpr", mode=3)
    assert flat["avg"] != lit["avg"], f"モード切り替えが効いていない {lit['avg']} {flat['avg']}"
    assert coverage(flat) > 0.5, flat


def test_パンはドラッグした方向にシーンが追従する():
    # 期待軸はビュー行列から取っているので、pan の数式を写した自己証明にはなっていない
    p = open_sample("cube_color.zpr", mode=0, case="pan")["pan"]
    assert p["rightDotX"] < 0, f"左右のパンが逆 {p}"
    assert p["downDotY"] > 0, f"上下のパンが逆 {p}"
    assert abs(p["rightDotY"]) < abs(p["rightDotX"]) * 0.02, f"横ドラッグが上下に漏れる {p}"
    assert abs(p["downDotX"]) < abs(p["downDotY"]) * 0.02, f"縦ドラッグが左右に漏れる {p}"


def test_ライティングは無彩色になる():
    # 色なしメッシュ（白塗り）の平均色が照明の色そのものになる。
    # 光源の向きベクトルを色に流用していた頃は、ここで R だけ 13 ほど落ちていた
    r = open_sample("two_cubes.zpr", mode=0, case="wire", wire="0")
    avg = r["avgNoGrid"]
    assert max(avg) - min(avg) <= 10, f"照明に色かみが出ている {avg} {r}"
    assert all(v > 120 for v in avg), f"照明が暗すぎる {avg} {r}"


def test_リセットはフィットより少し引いた位置に戻る():
    r = open_sample("cube_color.zpr", mode=0, case="reset")
    assert r["resetDist"] > r["fitDist"] * 1.2, f"リセットが手前すぎる {r}"
    assert r["resetDist"] < r["fitDist"] * 3, f"リセットは引けばいいというものではない {r}"


def test_グリッドが敷かれる():
    r = open_sample("two_cubes.zpr", mode=0)
    assert r["grid"] is True, r


def test_ZPRでないファイルは理由を添えて断る():
    r = read_page({"f": "tests/samples/not_zpr.bin", "mode": 0})
    assert r.get("opened") is False, f"読み進めてしまっている {r}"
    assert "0x03AA" in r["toast"], r


def test_途中で切れたファイルでもページは落ちない():
    r = read_page({"f": "tests/samples/truncated.zpr", "mode": 0})
    assert "ERROR" not in r, r
    assert r.get("glError", 0) == 0, r


def test_18万面でも開ける():
    started = time.monotonic()
    r = open_sample("grid.zpr", mode=0)
    elapsed = time.monotonic() - started
    assert r["faces"] > 150000, r
    assert r["glError"] == 0, r
    assert coverage(r) > 1, r
    assert elapsed < 60, f"遅すぎる {elapsed:.1f}s"


def main():
    if not Path(CHROME).exists():
        print(f"skip: Chrome が見つからない {CHROME}")
        sys.exit(0)
    subprocess.run([sys.executable, str(ROOT / "tests" / "build_test_page.py")], check=True,
                   stdout=subprocess.DEVNULL)
    if not require_samples():
        sys.exit(0)
    make_broken_samples()

    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except Exception:
                failed += 1
                print("FAIL", name)
                traceback.print_exc()
    print(f"{failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    # import しただけで全テストが走り出すのを防ぐ（skip 挙動を確認したい時に読む）
    main()
