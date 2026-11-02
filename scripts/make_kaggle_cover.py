"""Genera kaggle/dataset-cover-image.png: la pirámide regional de data/processed/region.json.

    pip install matplotlib && python scripts/make_kaggle_cover.py

Se ejecuta a mano cuando cambia la pirámide regional; la imagen queda versionada y build_kaggle_dataset.py solo la
copia. Kaggle exige al menos 560 × 280 px y recorta en proporción 2:1.
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MALE, FEMALE, INK, MUTED = "#041c59", "#4e00ff", "#0b1220", "#5b6478"


def main() -> None:
    pyr = json.loads((ROOT / "data/processed/region.json").read_text(encoding="utf8"))["pyramid"]
    year = max(pyr["years"])  # el año más reciente con pirámide de los 20 países
    v, groups = pyr["years"][year], pyr["age_groups"]
    m = [x / 1e6 for x in v["m"]]
    f = [x / 1e6 for x in v["f"]]
    fig = plt.figure(figsize=(16, 8), dpi=100, facecolor="white")
    ax = fig.add_axes((0.52, 0.1, 0.44, 0.8))
    y = range(len(groups))
    ax.barh(y, [-x for x in m], color=MALE, height=0.82)
    ax.barh(y, f, color=FEMALE, height=0.82)
    ax.set_yticks(list(y), groups, fontsize=11, color=MUTED)
    lim = max(m + f) * 1.08
    ax.set_xlim(-lim, lim)
    ticks = [t for t in range(-30, 31, 10) if abs(t) <= lim]
    ax.set_xticks(ticks, [f"{abs(t)} M" for t in ticks], fontsize=11, color=MUTED)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#d0d5df")
    ax.tick_params(length=0)
    ax.text(-lim * 0.95, len(groups) - 0.2, "Men", color=MALE, fontsize=14, weight="bold")
    ax.text(lim * 0.95, len(groups) - 0.2, "Women", color=FEMALE, fontsize=14, weight="bold", ha="right")
    fig.text(0.05, 0.70, "Latin America\nPopulation", fontsize=46, weight="bold", color=INK, va="bottom", linespacing=1.05)
    fig.text(0.05, 0.62, "20 countries · official population series, projections\nand age pyramids, 1950-2100",
             fontsize=17, color=MUTED, va="top", linespacing=1.4)
    kind = " (projections)" if v["n_projection"] == v["n_countries"] else " (includes projections)" if v["n_projection"] else ""
    fig.text(0.05, 0.12, f"Age pyramid {year}{kind}: sum of the 20 published\npyramids (derived, not an official figure)",
             fontsize=13, color=MUTED, va="bottom", linespacing=1.4)
    out = ROOT / "kaggle" / "dataset-cover-image.png"
    fig.savefig(out, dpi=100, facecolor="white")
    print(out.relative_to(ROOT))


if __name__ == "__main__":
    main()
