"""
Feature engineering on top of raw SwingVision shot data.

Two strategies for break-point detection, applied depending on data quality:

  A) Points sheet available  → use SwingVision's own Break Point flag.
     Join Shots → Points on (match_file, point) to get the flag directly.

  B) No Points sheet (or empty) → reconstruct game structure from serve
     sequence. SwingVision sets Set=0, Game=0 for sessions recorded without
     score tracking, but Point increments per rally. We detect game boundaries
     by watching when the server changes, then walk point scores to flag BP.
"""

import pandas as pd
import numpy as np


PLAYER = "Bernardo Munk-Mesa"


# ── serve classification ──────────────────────────────────────────────────────

def serve_number(type_str: str) -> int:
    t = str(type_str).lower()
    return 2 if "second" in t else 1


def classify_direction(direction: str) -> str:
    """
    Map SwingVision direction labels to T / Wide / Body.

    SwingVision uses rally-style labels even on serves ('cross court',
    'down the line') because the direction is computed from ball trajectory,
    not from serve terminology. Mappings are derived from the observed
    relationship between label and Bounce (x) in this dataset.
    """
    d = str(direction).lower()
    if "down the t" in d or "cross court" in d:
        return "T"
    if "wide" in d or "down the line" in d or "inside out" in d:
        return "Wide"
    if "body" in d or "inside in" in d:
        return "Body"
    return "Other"


# ── strategy A: join from Points sheet ───────────────────────────────────────

def bp_from_points_sheet(shots: pd.DataFrame, points: pd.DataFrame) -> pd.DataFrame:
    """
    When SwingVision exported a Points sheet with a Break Point column,
    join it to the serve rows by (match_file, point).
    Returns only rows that matched.
    """
    if points.empty or "break_point" not in points.columns:
        return pd.DataFrame()

    join_cols = ["match_file", "point"] if "match_file" in points.columns else ["point"]
    bp_map = points[join_cols + ["break_point"]].dropna(subset=["break_point"])

    return bp_map.rename(columns={"break_point": "is_break_point"})


# ── strategy B: reconstruct from serve sequence ───────────────────────────────

def _last_shot_per_point(shots: pd.DataFrame) -> pd.DataFrame:
    key = ["match_file", "point"] if "match_file" in shots.columns else ["point"]
    return shots.sort_values("shot").groupby(key, as_index=False).last()


def _server_won(last_shot_player: str, last_shot_result: str, server_name: str) -> bool:
    """Infer whether the server won a point from the final shot of that rally."""
    hit_in       = str(last_shot_result).lower() == "in"
    hitter_is_sv = server_name.lower() in str(last_shot_player).lower()
    return hitter_is_sv == hit_in   # server wins if they hit in, or opponent errors


def _detect_game_boundaries(shots: pd.DataFrame, server_name: str) -> pd.DataFrame:
    """
    Reconstruct game-level groupings for files where Set=Game=0 (SwingVision
    recorded without score tracking). A new game starts whenever the server
    changes from one point to the next.

    Returns columns: match_file, point, server, inferred_game
    """
    serve_types = {"serve", "first_serve", "second_serve"}
    sv_shots = shots[shots["type"].isin(serve_types)].sort_values("point")

    key = ["match_file", "point"] if "match_file" in shots.columns else ["point"]
    # One server per point (first serve shot recorded)
    server_by_pt = sv_shots.groupby(key, as_index=False)["player"].first().rename(
        columns={"player": "server"}
    )

    group_cols = ["match_file"] if "match_file" in server_by_pt.columns else []

    def assign_games(sub: pd.DataFrame) -> pd.DataFrame:
        sub = sub.sort_values("point").copy()
        sub["inferred_game"] = (sub["server"] != sub["server"].shift()).cumsum()
        return sub

    return server_by_pt.groupby(group_cols, group_keys=False).apply(assign_games)


def _is_break_point(server_pts: int, recv_pts: int) -> bool:
    if recv_pts == 3 and server_pts < 3:
        return True
    if recv_pts > 3 and recv_pts == server_pts + 1:
        return True
    return False


def bp_from_reconstruction(shots: pd.DataFrame, server_name: str) -> pd.DataFrame:
    """
    Walk reconstructed games for server_name's service games and flag break points.
    """
    game_map   = _detect_game_boundaries(shots, server_name)
    last_shots = _last_shot_per_point(shots)

    key = ["match_file", "point"] if "match_file" in shots.columns else ["point"]
    merged = game_map.merge(last_shots[key + ["player", "result"]], on=key, how="left")

    sname = server_name.lower()
    merged = merged[merged["server"].str.lower().str.contains(sname, na=False)]
    merged["server_won"] = merged.apply(
        lambda r: _server_won(r["player"], r["result"], server_name), axis=1
    )

    records = []
    group_cols = (["match_file", "inferred_game"] if "match_file" in merged.columns
                  else ["inferred_game"])

    for _, grp in merged.groupby(group_cols):
        sp = rp = 0
        for row in grp.sort_values("point").itertuples(index=False):
            records.append({
                **{c: getattr(row, c) for c in key},
                "inferred_game":  row.inferred_game,
                "is_break_point": _is_break_point(sp, rp),
            })
            if row.server_won:
                sp += 1
            else:
                rp += 1

    return pd.DataFrame(records) if records else pd.DataFrame()


# ── main pipeline step ────────────────────────────────────────────────────────

def build_serve_df(shots: pd.DataFrame, points: pd.DataFrame,
                   server_name: str = PLAYER) -> pd.DataFrame:
    """
    Filter shots to server_name's serves and attach:
      - serve_num (1 or 2)
      - direction_label (T / Wide / Body / Other)
      - is_break_point (from Points sheet when available, else reconstructed)
    """
    is_server = shots["player"].str.contains(server_name, case=False, na=False)
    is_serve  = (
        shots["type"].str.contains("serve", na=False)
        & ~shots["type"].str.contains("return|plus_one", na=False)
    )

    serves = shots[is_server & is_serve].copy()
    serves["serve_num"]       = serves["type"].apply(serve_number)
    serves["direction_label"] = serves["direction"].apply(classify_direction)

    key = ["match_file", "point"] if "match_file" in serves.columns else ["point"]

    # Strategy A: use Points sheet break-point flags directly
    bp_direct = bp_from_points_sheet(shots, points)

    if not bp_direct.empty:
        # Merge the direct flags; fall back to reconstruction for unmatched rows
        serves = serves.merge(bp_direct, on=key, how="left")
        unmatched = serves["is_break_point"].isna()
        if unmatched.any():
            bp_rec = bp_from_reconstruction(
                shots[shots["match_file"].isin(
                    serves.loc[unmatched, "match_file"].unique()
                )],
                server_name,
            )
            if not bp_rec.empty:
                serves.loc[unmatched, "is_break_point"] = serves.loc[
                    unmatched, key
                ].merge(bp_rec[key + ["is_break_point"]], on=key, how="left")[
                    "is_break_point"
                ].values
    else:
        # Strategy B only
        bp_rec = bp_from_reconstruction(shots, server_name)
        if not bp_rec.empty:
            serves = serves.merge(bp_rec[key + ["is_break_point"]], on=key, how="left")
        else:
            serves["is_break_point"] = False

    serves["is_break_point"] = serves["is_break_point"].infer_objects(copy=False).fillna(False).astype(bool)
    return serves
