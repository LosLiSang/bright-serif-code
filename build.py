"""Build Bright Serif Code.

Latin, symbols and ligatures come from LXGW Bright Code. CJK glyphs come from
Noto Serif SC, which uses the Source Han Serif design.

    uv run build.py
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["fonttools>=4.50"]
# ///
import argparse
import glob
import os
import subprocess
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

BRIGHT_VERSION = "v2.922"
NOTO_VERSION = "Serif2.003"
VERSION = "1.000"

BRIGHT_URL = f"https://github.com/lxgw/LxgwBright-Code/releases/download/{BRIGHT_VERSION}/LxgwBrightCode.7z"
NOTO_URL = f"https://github.com/notofonts/noto-cjk/raw/{NOTO_VERSION}/Serif/Variable/TTF/Subset/NotoSerifSC-VF.ttf"

FAMILY = "Bright Serif Code"
PS_FAMILY = "BrightSerifCode"
REPO = "https://github.com/LosLiSang/bright-serif-code"

CJK_RANGES = [
    (0x2E80, 0x2FFF),    # radicals, ideographic description characters
    (0x3000, 0x303F),    # CJK symbols and punctuation
    (0x3040, 0x30FF),    # kana
    (0x3100, 0x312F), (0x3190, 0x31FF),
    (0x3200, 0x33FF),    # enclosed and compatibility characters
    (0x3400, 0x4DBF),    # extension A
    (0x4E00, 0x9FFF),    # unified ideographs
    (0xF900, 0xFAFF),    # compatibility ideographs
    (0xFE10, 0xFE1F), (0xFE30, 0xFE4F),
    (0xFF01, 0xFF60), (0xFFE0, 0xFFE6),  # fullwidth forms
    (0x20000, 0x3FFFF),  # extension B and later
]

COPYRIGHT = (
    f"Copyright 2026 LosLiSang ({REPO})\n"
    "Copyright 2022-2026 LXGW (https://github.com/lxgw/LxgwBright-Code)\n"
    "Copyright 2020 The Klee Project Authors (https://github.com/fontworks-fonts/Klee)\n"
    "Copyright 2023 GitHub, Inc. (https://github.com/githubnext/monaspace)\n"
    "Copyright 2017-2023 Adobe (http://www.adobe.com/)"
)


def in_cjk(cp):
    return any(lo <= cp <= hi for lo, hi in CJK_RANGES)


def download(url, dest):
    if not os.path.exists(dest):
        print(f"download {url}")
        urllib.request.urlretrieve(url, dest + ".part")
        os.replace(dest + ".part", dest)
    return dest


def fetch_sources(work):
    os.makedirs(work, exist_ok=True)
    bright_dir = os.path.join(work, "bright")
    if not glob.glob(f"{bright_dir}/**/*.ttf", recursive=True):
        archive = download(BRIGHT_URL, os.path.join(work, "bright.7z"))
        os.makedirs(bright_dir, exist_ok=True)
        # bsdtar (Windows 10+, macOS, libarchive-tools on Linux) reads 7z
        tar = os.path.join(os.environ.get("SystemRoot", ""), "System32", "tar.exe")
        subprocess.run([tar if os.path.exists(tar) else "tar", "-xf", archive, "-C", bright_dir], check=True)
    noto = download(NOTO_URL, os.path.join(work, "NotoSerifSC-VF.ttf"))
    return sorted(glob.glob(f"{bright_dir}/**/*.ttf", recursive=True)), noto


def noto_instance(noto_path, weight, work):
    cache = os.path.join(work, f"noto-{weight}.ttf")
    if not os.path.exists(cache):
        instantiateVariableFont(TTFont(noto_path), {"wght": weight}).save(cache + ".part")
        os.replace(cache + ".part", cache)
    return TTFont(cache)


def warm_noto(noto_path, weight, work):
    noto_instance(noto_path, weight, work)


def rename(font, style):
    ps_style = style.replace(" ", "")
    is_ribbi = style in ("Regular", "Italic", "Bold", "Bold Italic")
    family = FAMILY if is_ribbi else f"{FAMILY} {style.replace(' Italic', '').replace('Italic', '')}".strip()
    subfamily = style if is_ribbi else ("Italic" if "Italic" in style else "Regular")
    values = {
        0: COPYRIGHT,
        1: family,
        2: subfamily,
        3: f"{FAMILY} {style} Version {VERSION}",
        4: f"{FAMILY} {style}",
        5: f"Version {VERSION}",
        6: f"{PS_FAMILY}-{ps_style}",
        11: REPO,
        16: FAMILY,
        17: style,
        19: "永和九年，岁在癸丑。printf(\"Hello, world!\")",
    }
    name = font["name"]
    keep = [r for r in name.names if r.nameID >= 256 or r.nameID in (7, 8, 9, 12, 13, 14)]
    name.names = keep
    for nid, value in values.items():
        name.setName(value, nid, 3, 1, 0x409)
        if nid <= 6:
            name.setName(value, nid, 1, 0, 0)
    font["OS/2"].achVendID = "NONE"
    font["head"].fontRevision = float(VERSION)


def merge(path, noto_path, work, out_dir):
    base = TTFont(path)
    weight = base["OS/2"].usWeightClass
    # LXGWBrightCode-ExtraLightItalic -> "ExtraLight Italic"
    style = os.path.splitext(os.path.basename(path))[0].split("-", 1)[1]
    style = style.replace("Italic", " Italic").strip() or "Regular"
    noto = noto_instance(noto_path, max(200, weight), work)
    noto_upm, full = noto["head"].unitsPerEm, base["head"].unitsPerEm
    scale = full / noto_upm  # one CJK glyph = two Latin cells

    ncmap, bcmap = noto.getBestCmap(), base.getBestCmap()
    nadv, ngs = noto["hmtx"].metrics, noto.getGlyphSet()
    glyf, hmtx = base["glyf"], base["hmtx"]
    order = list(base.getGlyphOrder())

    mapping, made = {}, {}
    for cp, ng in ncmap.items():
        if not in_cjk(cp) or nadv[ng][0] != noto_upm:
            continue
        if cp in bcmap and hmtx[bcmap[cp]][0] != full:
            continue  # keep Bright Code's half-width forms, such as curly quotes
        if ng not in made:
            pen = TTGlyphPen(None)
            ngs[ng].draw(TransformPen(pen, (scale, 0, 0, scale, 0, 0)))
            glyph = pen.glyph()
            new_name = f"nsc.{ng}"
            glyf[new_name] = glyph
            glyph.recalcBounds(glyf)
            hmtx[new_name] = (full, getattr(glyph, "xMin", 0))
            order.append(new_name)
            made[ng] = new_name
        mapping[cp] = made[ng]

    base.setGlyphOrder(order)
    for table in base["cmap"].tables:
        if not table.isUnicode():
            continue
        for cp, glyph_name in mapping.items():
            if table.format == 4 and cp > 0xFFFF:
                continue
            table.cmap[cp] = glyph_name

    opts = Options()
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.name_legacy = True
    opts.glyph_names = True
    opts.notdef_outline = True
    opts.legacy_kern = True
    opts.hinting = True
    opts.drop_tables = []
    subsetter = Subsetter(opts)
    subsetter.populate(unicodes=base.getBestCmap().keys())
    subsetter.subset(base)

    rename(base, style)
    out = os.path.join(out_dir, f"{PS_FAMILY}-{style.replace(' ', '')}.ttf")
    base.save(out)
    print(f"{out}: wght={weight}, CJK code points={len(mapping)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", default="build")
    parser.add_argument("--out", default="dist")
    args = parser.parse_args()
    bright_fonts, noto = fetch_sources(args.work)
    os.makedirs(args.out, exist_ok=True)
    # Instantiate each weight once up front so parallel workers don't race on the cache.
    weights = sorted({max(200, TTFont(p, lazy=True)["OS/2"].usWeightClass) for p in bright_fonts})
    with ProcessPoolExecutor() as pool:
        list(pool.map(warm_noto, [noto] * len(weights), weights, [args.work] * len(weights)))
        list(pool.map(merge, bright_fonts, [noto] * len(bright_fonts),
                      [args.work] * len(bright_fonts), [args.out] * len(bright_fonts)))


if __name__ == "__main__":
    main()
