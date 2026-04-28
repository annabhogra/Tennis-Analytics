"""
Run the full pipeline → viz/data.json.

Usage:
    python export.py [--player "Bernardo Munk-Mesa"] [--data ../data] [--out ../viz/data.json]

SwingVision coordinate reference (metres):
    x=0 centre service line, x<0 deuce box, x>0 ad box
    y=0 near baseline, y≈11.885 net, y≈18.285 far service line
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from ingest import load_matches
from features import build_serve_df, classify_direction

COURT = {
    "net_y":          11.885,
    "service_line_y": 18.285,
    "singles_half_x": 4.115,
}

EXPORT_COLS = [
    "bounce_x", "bounce_y", "bounce_zone",
    "serve_num", "is_break_point", "direction_label",
    "result", "speed_mph", "match_file",
]


def direction_breakdown(serves: pd.DataFrame) -> dict:
    """Percentage of T / Wide / Body by (serve_num, pressure condition)."""
    out = {}
    for num in (1, 2):
        for label, flag in (("all", None), ("break_point", True), ("normal", False)):
            sub = serves[(serves["serve_num"] == num) & (serves["result"] == "in")]
            if flag is not None:
                sub = sub[sub["is_break_point"] == flag]
            counts = sub["direction_label"].value_counts()
            total  = counts.sum()
            out[f"s{num}_{label}"] = {
                d: {"n": int(counts.get(d, 0)),
                    "pct": round(counts.get(d, 0) / total * 100, 1) if total else 0}
                for d in ("T", "Wide", "Body", "Other")
            }
    return out


def win_rates(serves: pd.DataFrame) -> dict:
    """Point win % by direction label, split by pressure condition."""
    out = {}
    for label, flag in (("all", None), ("break_point", True), ("normal", False)):
        sub = serves[serves["result"] == "in"]
        if flag is not None:
            sub = sub[sub["is_break_point"] == flag]
        dir_stats = {}
        for d in ("T", "Wide", "Body"):
            d_sub = sub[sub["direction_label"] == d]
            n = len(d_sub)
            won = int(d_sub["server_won"].sum()) if "server_won" in d_sub.columns and n > 0 else 0
            dir_stats[d] = {
                "n": n,
                "won": won,
                "win_pct": round(won / n * 100, 1) if n > 0 else None,
            }
        out[f"s1_{label}"] = dir_stats
    return out


def run(data_dir: str, player: str, out_path: str) -> None:
    shots, points = load_matches(data_dir)
    serves = build_serve_df(shots, points, server_name=player)

    in_play = serves[serves["result"] == "in"]
    n_bp    = serves["is_break_point"].sum()
    n_files = serves["match_file"].nunique() if "match_file" in serves.columns else "?"

    print(f"{player}: {len(serves)} serves across {n_files} match(es)")
    print(f"  in-play: {len(in_play)}  |  on break point: {n_bp}")

    present_cols = [c for c in EXPORT_COLS if c in serves.columns]
    points_out   = (
        serves[present_cols]
        .dropna(subset=["bounce_x", "bounce_y"])
        .assign(is_break_point=lambda d: d["is_break_point"].astype(bool))
        .to_dict(orient="records")
    )

    payload = {
        "player":              player,
        "court":               COURT,
        "n_matches":           serves["match_file"].nunique() if "match_file" in serves.columns else 1,
        "direction_breakdown": direction_breakdown(serves),
        "win_rates":           win_rates(serves),
        "points":              points_out,
    }

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"→ {out_path}  ({len(points_out)} points exported)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", default="Bernardo Munk-Mesa")
    parser.add_argument("--data",   default="../data")
    parser.add_argument("--out",    default="../viz/data.json")
    args = parser.parse_args()
    run(args.data, args.player, args.out)
