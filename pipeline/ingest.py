"""Load and normalize SwingVision Pro exports (CSV or multi-sheet XLSX)."""

import pandas as pd
from pathlib import Path


def load(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (shots_df, points_df). points_df is empty when the sheet doesn't exist."""
    p = Path(path)

    if p.suffix in (".xlsx", ".xls"):
        raw = pd.read_excel(p, sheet_name=None, engine="openpyxl")
        shots_key = next((k for k in raw if "shot" in k.lower()), list(raw)[0])
        points_key = next((k for k in raw if "point" in k.lower()), None)

        shots = _normalize_shots(raw[shots_key].copy())
        points = _normalize_points(raw[points_key].copy()) if points_key else pd.DataFrame()
    else:
        shots = _normalize_shots(pd.read_csv(p))
        points = pd.DataFrame()

    return shots, points


def load_matches(data_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Concatenate all match files in data_dir into (shots, points) DataFrames."""
    paths = sorted(Path(data_dir).glob("*.csv")) + sorted(Path(data_dir).glob("*.xlsx"))
    if not paths:
        raise FileNotFoundError(f"No match files found in {data_dir}")

    all_shots, all_points = [], []
    for p in paths:
        shots, points = load(p)
        shots["match_file"] = p.stem
        if not points.empty:
            points["match_file"] = p.stem
        all_shots.append(shots)
        all_points.append(points)

    shots_df = pd.concat(all_shots, ignore_index=True)
    points_df = pd.concat([df for df in all_points if not df.empty], ignore_index=True)
    return shots_df, points_df


def _clean_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase + underscore column names: 'Bounce (x)' → 'bounce_x'."""
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace(r"[^a-z0-9]+", "_", regex=True)
        .str.strip("_")
    )
    return df


def _normalize_shots(df: pd.DataFrame) -> pd.DataFrame:
    df = _clean_cols(df)

    for col in ("bounce_x", "bounce_y", "hit_x", "hit_y", "hit_z", "speed_mph", "shot"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ("player", "type", "stroke", "result", "direction",
                "spin", "bounce_zone", "bounce_depth", "bounce_side"):
        if col in df.columns:
            df[col] = df[col].str.strip()

    df["result"] = df["result"].str.lower()
    # SwingVision match exports use "First Serve" / "Second Serve"; rally exports say "Serve".
    # Normalise to snake_case so downstream code uses a single namespace.
    df["type"] = df["type"].str.lower().str.replace(r"\s+", "_", regex=True)

    return df


def _normalize_points(df: pd.DataFrame) -> pd.DataFrame:
    df = _clean_cols(df)
    df = df.dropna(subset=["point"], how="all")

    for col in ("point", "game", "set"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    if "break_point" in df.columns:
        df["break_point"] = df["break_point"].astype(bool)

    return df
