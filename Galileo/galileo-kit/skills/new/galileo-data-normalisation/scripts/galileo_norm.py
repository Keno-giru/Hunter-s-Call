"""Galileo canonical frame, entity matching, provenance and unit helpers.

Canonical frame (D-001): metres, centre origin, y up, STATIC_HOME_AWAY.
All coordinate conversion goes through kloppy (zone-aware for Opta/Wyscout).
Tests: test_galileo_norm.py (pytest).
"""
from __future__ import annotations

import difflib
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Iterable, Optional

DEFAULT_PITCH = (105.0, 68.0)
PITCH_DIMS_SOURCES = {"venue_registry", "provider_metadata", "default", "supplied"}
CANONICAL = {
    "units": "m",
    "origin": "CENTER",
    "vertical": "BOTTOM_TO_TOP",
    "orientation": "STATIC_HOME_AWAY",
}

# ---------------------------------------------------------------- coordinates


def canonical_coordinate_system(pitch_length: float, pitch_width: float):
    from kloppy.domain import SecondSpectrumCoordinateSystem

    return SecondSpectrumCoordinateSystem(
        pitch_length=pitch_length, pitch_width=pitch_width
    )


def to_canonical(
    dataset,
    pitch_length: Optional[float] = None,
    pitch_width: Optional[float] = None,
    pitch_dims_source: Optional[str] = None,
):
    """Transform a kloppy dataset to the Galileo canonical frame.

    Pitch dims must be passed with their source; if omitted, 105x68 is used
    and the source is recorded as 'default' (distance metrics then carry
    reduced confidence). Returns (dataset, frame_meta).
    """
    from kloppy.domain import Orientation

    if pitch_length is None or pitch_width is None:
        pitch_length, pitch_width = DEFAULT_PITCH
        pitch_dims_source = "default"
    if pitch_dims_source not in PITCH_DIMS_SOURCES:
        raise ValueError(
            f"pitch_dims_source must be one of {sorted(PITCH_DIMS_SOURCES)}"
        )
    md = dataset.metadata
    out = dataset.transform(
        to_coordinate_system=canonical_coordinate_system(pitch_length, pitch_width),
        to_orientation=Orientation.STATIC_HOME_AWAY,
    )
    meta = {
        **CANONICAL,
        "pitch_length": float(pitch_length),
        "pitch_width": float(pitch_width),
        "pitch_dims_source": pitch_dims_source,
        "from_coordinate_system": type(md.coordinate_system).__name__,
        "from_orientation": md.orientation.name if md.orientation else None,
    }
    return out, meta


def out_of_bounds(points: Iterable[tuple[float, float]], length: float, width: float,
                  margin: float = 5.0) -> int:
    """Count points outside the pitch +/- margin (canonical frame). Never clip."""
    hx, hy = length / 2 + margin, width / 2 + margin
    return sum(1 for x, y in points if abs(x) > hx or abs(y) > hy)


# ---------------------------------------------------------------- identity


def new_id(prefix: str) -> str:
    if not re.fullmatch(r"[a-z]{2,4}", prefix):
        raise ValueError("prefix like 'plr', 'tm', 'fx', 'comp'")
    return f"{prefix}_{uuid.uuid4().hex}"


def normalise_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("ß", "ss").replace("ø", "o").replace("æ", "ae").replace("ł", "l")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _initial_compatible(a: list[str], b: list[str]) -> bool:
    """'f de jong' vs 'frenkie de jong': same tokens except initials matching."""
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x == y:
            continue
        short, long_ = (x, y) if len(x) < len(y) else (y, x)
        if not (len(short) == 1 and long_.startswith(short)):
            return False
    return True


def name_similarity(a: str, b: str) -> float:
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = na.split(), nb.split()
    if _initial_compatible(ta, tb):
        return 0.85
    sa, sb = " ".join(sorted(ta)), " ".join(sorted(tb))
    seq = difflib.SequenceMatcher(None, sa, sb).ratio()
    # surname (last token) mismatch caps the score
    if ta[-1] != tb[-1] and difflib.SequenceMatcher(None, ta[-1], tb[-1]).ratio() < 0.8:
        seq = min(seq, 0.6)
    return round(seq, 4)


class Decision(str, Enum):
    MERGE = "MERGE"
    REVIEW = "REVIEW"
    NEW = "NEW"


@dataclass
class PlayerRecord:
    name: str
    dob: Optional[date] = None
    team_seasons: set[tuple[str, str]] = field(default_factory=set)  # (team_id, season)
    nationality: Optional[str] = None


def match_player(rec: PlayerRecord, cand: PlayerRecord) -> tuple[Decision, float, list[str]]:
    """Decide whether rec and cand are the same player. Never auto-merge on name alone."""
    reasons: list[str] = []
    sim = name_similarity(rec.name, cand.name)
    reasons.append(f"name_sim={sim}")
    if rec.dob and cand.dob and rec.dob != cand.dob:
        return Decision.NEW, 0.0, reasons + ["dob_conflict_veto"]
    if rec.nationality and cand.nationality and rec.nationality != cand.nationality:
        reasons.append("nationality_differs")  # weak: dual nationals exist
    dob_match = bool(rec.dob and cand.dob and rec.dob == cand.dob)
    team_overlap = bool(rec.team_seasons & cand.team_seasons)
    if dob_match:
        reasons.append("dob_match")
    if team_overlap:
        reasons.append("team_season_overlap")
    if dob_match and sim >= 0.85:
        return Decision.MERGE, min(1.0, 0.6 + 0.4 * sim), reasons
    if team_overlap and sim >= 0.95:
        return Decision.MERGE, 0.9 * sim, reasons
    if sim >= 0.75 and (dob_match or team_overlap):
        return Decision.REVIEW, 0.5 * sim, reasons
    return Decision.NEW, 0.0, reasons


# ---------------------------------------------------------------- provenance

STATUSES = {"confirmed", "reported", "rumour", "inferred"}


@dataclass(frozen=True)
class Provenance:
    source: str
    source_id: str
    retrieved_at: datetime
    status: str
    confidence: float
    licence: str
    published_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    source_url: Optional[str] = None
    independent_sources: int = 1

    def validate(self) -> list[str]:
        errs = []
        for f_ in ("retrieved_at", "published_at", "verified_at"):
            v = getattr(self, f_)
            if v is not None and (v.tzinfo is None or v.utcoffset() is None):
                errs.append(f"{f_} must be timezone-aware")
        if self.status not in STATUSES:
            errs.append(f"status must be one of {sorted(STATUSES)}")
        if not 0.0 <= self.confidence <= 1.0:
            errs.append("confidence must be in [0,1]")
        if (self.published_at and self.retrieved_at and self.published_at.tzinfo
                and self.retrieved_at.tzinfo and self.published_at > self.retrieved_at):
            errs.append("published_at after retrieved_at")
        if self.status == "confirmed" and self.independent_sources < 2:
            errs.append("confirmed requires >=2 independent sources")
        if not self.licence:
            errs.append("licence required")
        return errs


# ---------------------------------------------------------------- units & time

KMH_PER_MS = 3.6


def ms_to_kmh(v: float) -> float:
    return v * KMH_PER_MS


def kmh_to_ms(v: float) -> float:
    return v / KMH_PER_MS


def frame_to_seconds(frame_id: int, period_start_frame: int, frame_rate_hz: float) -> float:
    if frame_rate_hz <= 0:
        raise ValueError("frame_rate_hz must be > 0")
    if frame_id < period_start_frame:
        raise ValueError("frame before period start")
    return (frame_id - period_start_frame) / frame_rate_hz


def display_minute(period: int, seconds_in_period: float) -> str:
    """45+2 style display minute from (period, seconds). Regulation periods only."""
    base = {1: 0, 2: 45, 3: 90, 4: 105}.get(period)
    if base is None:
        raise ValueError("period must be 1-4")
    length = 45 if period in (1, 2) else 15
    m = int(seconds_in_period // 60)
    if m < length:
        return str(base + m + 1)
    return f"{base + length}+{m - length + 1}"
