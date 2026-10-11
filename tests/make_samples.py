"""検証用サンプル .zpr を Blender で作る。Blender 上で実行する。

    "/Applications/Blender/Blender 4.5 LTS.app/Contents/MacOS/Blender" \\
        -b --factory-startup --python tests/make_samples.py

出力は tests/samples/。ビューアのヘッドレス検証（tests/test_zpr_viewer.py）が読む。
"""
import importlib.util
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "samples"
OUT.mkdir(parents=True, exist_ok=True)

# エクスポートアドオン（io_export_zpr.py）はビューアの git 管理外に置く運用。
# ZPR_ADDON で場所を指名するのが一番確実で、指定がなければ見慣れた位置に順に当たる
CANDIDATES = [
    Path(os.environ["ZPR_ADDON"]) if "ZPR_ADDON" in os.environ else None,
    ROOT / "io_export_zpr.py",
    ROOT / "blender-addon-export-zpr" / "io_export_zpr.py",
    ROOT.parent / "blender-addon-export-zpr" / "io_export_zpr.py",
    ROOT.parent / "io_export_zpr.py",
]
ADDON = next((p for p in CANDIDATES if p and p.exists()), None)
if ADDON is None:
    sys.exit("io_export_zpr.py が見つかりません。ZPR_ADDON にパスを渡してください。探した場所: "
             + ", ".join(str(p) for p in CANDIDATES if p))

spec = importlib.util.spec_from_file_location("io_export_zpr", ADDON)
zpr = importlib.util.module_from_spec(spec)
sys.modules["io_export_zpr"] = zpr
spec.loader.exec_module(zpr)
zpr.register()


def reset():
    """シーンもデータブロックも消える。画像の読み直しはこれの後に行うこと。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def export(name, **kwargs):
    path = OUT / name
    result = bpy.ops.export_scene.zpr(filepath=str(path), **kwargs)
    assert result == {"FINISHED"}, result
    print(f"  {name}: {path.stat().st_size} bytes")
    return path


def solid_image(name, corners):
    """4 隅だけを色分けした画像を作って読み直す（UV の向き検証用）。
    PNG と JPEG の両方を出す（JPEG の方は名前の違うテクスチャを手で組むサンプルで使う）"""
    w = h = 64
    px = []
    for y in range(h):                      # Blender の pixels は y=0 が画像の下端
        for x in range(w):
            left, right = x < 12, x >= w - 12
            bottom, top = y < 12, y >= h - 12
            color = (corners["top_left"] if left and top else
                     corners["top_right"] if right and top else
                     corners["bottom_left"] if left and bottom else
                     corners["bottom_right"] if right and bottom else (0.5, 0.5, 0.5, 1))
            px += list(color)
    img = bpy.data.images.new(name, w, h)
    img.pixels[:] = px
    for fmt, suffix in (("PNG", ".png"), ("JPEG", ".jpg")):
        out = OUT / f"{name}{suffix}"
        img.filepath_raw = str(out)
        img.file_format = fmt
        img.save()
    return bpy.data.images.load(str(OUT / f"{name}.png"))


def textured_plane(image, location):
    bpy.ops.mesh.primitive_plane_add(size=100, location=location)
    obj = bpy.context.active_object
    mat = bpy.data.materials.new("tex_" + image.name)
    mat.use_nodes = True
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    mat.node_tree.links.new(node.outputs[0], mat.node_tree.nodes["Principled BSDF"].inputs[0])
    obj.data.materials.append(mat)
    return obj


CORNER_COLORS = {
    "top_left": (1, 0, 0, 1),        # 赤
    "top_right": (0, 1, 0, 1),       # 緑
    "bottom_left": (0, 0, 1, 1),     # 青
    "bottom_right": (1, 0, 1, 1),    # マゼンタ
}
CHECKER_COLORS = {
    "top_left": (1, 1, 0, 1), "top_right": (0, 1, 1, 1),
    "bottom_left": (1, 0, 1, 1), "bottom_right": (1, 1, 1, 1),
}

reset()
bpy.ops.mesh.primitive_cube_add(size=2, location=(1, 0, 0))
cube = bpy.context.active_object
attr = cube.data.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
for i, d in enumerate(attr.data):
    d.color_srgb = ((i % 3) / 2.0, (i % 5) / 4.0, 1.0 - (i % 4) / 4.0, 1.0)
cube.data.color_attributes.active_color = attr
export("cube_color.zpr")

reset()
bpy.ops.mesh.primitive_cube_add()
bpy.ops.mesh.primitive_cube_add(location=(5, 0, 0))
export("two_cubes.zpr")

reset()
textured_plane(solid_image("uvprobe", CORNER_COLORS), (0, 0, 0))
export("plane_uv.zpr")

reset()
probe = solid_image("uvprobe2", CORNER_COLORS)
textured_plane(probe, (0, 0, 0))
textured_plane(probe, (150, 0, 0))
export("plane_uv_pair.zpr")

reset()
bpy.ops.mesh.primitive_grid_add(x_subdivisions=300, y_subdivisions=300, size=200)
bpy.ops.object.shade_smooth()
export("grid.zpr", use_colors=False, use_textures=False)

reset()
textured_plane(solid_image("checker", CHECKER_COLORS), (0, 0, 200))
bpy.ops.mesh.primitive_cube_add(location=(0, 0, -150))
bpy.context.active_object.data.materials.append(bpy.data.materials.new("plain"))
export("mixed.zpr")

zpr.unregister()
print("samples:", sorted(p.name for p in OUT.glob("*.zpr")))
