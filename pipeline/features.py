"""
Break-point detection uses two strategies: read from SwingVision's Points sheet
when available, otherwise reconstruct game boundaries from serve-sequence changes.
"""

import pandas as pd
import numpy as np


PLAYER = "Bernardo Munk-Mesa"


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


def bp_from_points_sheet(shots: pd.DataFrame, points: pd.DataFrame) -> pd.DataFrame:
    if points.empty or "break_point" not in points.columns:
        return pd.DataFrame()

    join_cols = ["match_file", "point"] if "match_file" in points.columns else ["point"]
    bp_map = points[join_cols + ["break_point"]].dropna(subset=["break_point"])

    return bp_map.rename(columns={"break_point": "is_break_point"})


def _last_shot_per_point(shots: pd.DataFrame) -> pd.DataFrame:
    key = ["match_file", "point"] if "match_file" in shots.columns else ["point"]
    return shots.sort_values("shot").groupby(key, as_index=False).last()


def _server_won(last_shot_player: str, last_shot_result: str, server_name: str) -> bool:
    hit_in = str(last_shot_result).lower() == "in"
    hitter_is_sv = server_name.lower() in str(last_shot_player).lower()
    return hitter_is_sv == hit_in


def _detect_game_boundaries(shots: pd.DataFrame, server_name: str) -> pd.DataFrame:
    """
    SwingVision sets Set=Game=0 when score isn't tracked, but Point still
    increments per rally. Detect game boundaries by watching when the server
    changes across sequential points.
    """
    serve_types = {"serve", "first_serve", "second_serve"}
    sv_shots = shots[shots["type"].isin(serve_types)].sort_values("point")

    key = ["match_file", "point"] if "match_file" in shots.columns else ["point"]
    server_by_pt = sv_shots.groupby(key, as_index=False)["player"].first().rename(
        columns={"player": "server"}
    )

    group_cols = ["match_file"] if "match_file" in server_by_pt.columns else []

    def assign_games(sub: pd.DataFrame) -> pd.DataFrame:
        sub = sub.sort_values("point").copy()
        sub["inferred_game"] = (sub["server"] != sub["server"].shift()).cumsum()
        return sub

    if group_cols:
        return server_by_pt.groupby(group_cols, group_keys=False).apply(assign_games).reset_index(drop=True)
    return assign_games(server_by_pt)


def _is_break_point(server_pts: int, recv_pts: int) -> bool:
    if recv_pts == 3 and server_pts < 3:
        return True
    if recv_pts > 3 and recv_pts == server_pts + 1:
        return True
    return False


def bp_from_reconstruction(shots: pd.DataFrame, server_name: str) -> pd.DataFrame:
    game_map = _detect_game_boundaries(shots, server_name)
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
                "inferred_game": row.inferred_game,
                "is_break_point": _is_break_point(sp, rp),
            })
            if row.server_won:
                sp += 1
            else:
                rp += 1

    return pd.DataFrame(records) if records else pd.DataFrame()


def build_serve_df(shots: pd.DataFrame, points: pd.DataFrame,
                   server_name: str = PLAYER) -> pd.DataFrame:
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

    # Point outcome — did Bernardo win the point?
    last = _last_shot_per_point(shots)
    last["server_won"] = last.apply(
        lambda r: _server_won(r["player"], r["result"], server_name), axis=1
    )
    serves = serves.merge(last[key + ["server_won"]], on=key, how="left")

    return serves
