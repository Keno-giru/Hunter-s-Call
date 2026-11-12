from datetime import date, datetime, timezone

import pytest

from galileo_norm import (
    Decision, PlayerRecord, Provenance, display_minute, frame_to_seconds,
    kmh_to_ms, match_player, ms_to_kmh, name_similarity, new_id,
    normalise_name, out_of_bounds,
)

UTC = timezone.utc


def test_normalise_name_strips_accents_and_punctuation():
    assert normalise_name("Vinícius Júnior") == "vinicius junior"
    assert normalise_name("  Martin Ødegaard ") == "martin odegaard"
    assert normalise_name("N'Golo Kanté") == "n golo kante"


def test_name_similarity_cases():
    assert name_similarity("Frenkie de Jong", "Frenkie De Jong") == 1.0
    assert name_similarity("F. de Jong", "Frenkie de Jong") == 0.85
    assert name_similarity("Frenkie de Jong", "Luuk de Jong") < 0.95
    assert name_similarity("Memphis Depay", "Cody Gakpo") < 0.6


def test_dob_conflict_is_hard_veto():
    a = PlayerRecord("Frenkie de Jong", date(1997, 5, 12))
    b = PlayerRecord("Luuk de Jong", date(1990, 8, 27))
    assert match_player(a, b)[0] is Decision.NEW


def test_merge_requires_corroboration():
    ts = {("tm_x", "2025/26")}
    exact_no_corrob = match_player(PlayerRecord("Jan Jansen"), PlayerRecord("Jan Jansen"))
    assert exact_no_corrob[0] is Decision.NEW  # name alone never merges
    same_team = match_player(PlayerRecord("Vinícius Júnior", team_seasons=ts),
                             PlayerRecord("Vinicius Junior", team_seasons=ts))
    assert same_team[0] is Decision.MERGE
    initials = match_player(PlayerRecord("F. de Jong", team_seasons=ts),
                            PlayerRecord("Frenkie de Jong", team_seasons=ts))
    assert initials[0] is Decision.REVIEW
    dob = match_player(PlayerRecord("F. de Jong", date(1997, 5, 12)),
                       PlayerRecord("Frenkie de Jong", date(1997, 5, 12)))
    assert dob[0] is Decision.MERGE


def test_provenance_validation():
    now = datetime(2026, 11, 8, 17, 0, tzinfo=UTC)
    ok = Provenance("api-football", "123", now, "reported", 0.7, "API-Football ToS",
                    published_at=datetime(2026, 11, 8, 16, 0, tzinfo=UTC))
    assert ok.validate() == []
    naive = Provenance("x", "1", datetime(2026, 11, 8), "reported", 0.5, "lic")
    assert any("timezone" in e for e in naive.validate())
    single = Provenance("x", "1", now, "confirmed", 0.9, "lic")
    assert any("independent" in e for e in single.validate())
    future = Provenance("x", "1", now, "rumour", 0.2, "lic",
                        published_at=datetime(2026, 11, 9, tzinfo=UTC))
    assert any("after" in e for e in future.validate())


def test_units_and_time():
    assert ms_to_kmh(7.0) == pytest.approx(25.2)
    assert kmh_to_ms(19.8) == pytest.approx(5.5)
    assert frame_to_seconds(250, 0, 25) == 10.0
    with pytest.raises(ValueError):
        frame_to_seconds(10, 20, 25)
    assert display_minute(1, 0) == "1"
    assert display_minute(1, 44 * 60 + 59) == "45"
    assert display_minute(1, 45 * 60 + 30) == "45+1"
    assert display_minute(2, 0) == "46"
    assert display_minute(2, 47 * 60) == "90+3"


def test_ids_and_bounds():
    assert new_id("plr").startswith("plr_")
    with pytest.raises(ValueError):
        new_id("Player")
    assert out_of_bounds([(0, 0), (52.5, 34), (58.0, 0), (0, -40)], 105, 68) == 2


@pytest.mark.integration
def test_statsbomb_open_data_canonical_orientation():
    """Pulls one StatsBomb open-data match (GitHub). Skips if offline."""
    import warnings
    kloppy = pytest.importorskip("kloppy")
    from kloppy import statsbomb
    from galileo_norm import to_canonical
    warnings.simplefilter("ignore")
    try:
        ds = statsbomb.load_open_data(match_id=3788741)
    except Exception as exc:  # network / proxy
        pytest.skip(f"open data unreachable: {exc}")
    out, meta = to_canonical(ds)
    assert meta["pitch_dims_source"] == "default"
    assert meta["orientation"] == "STATIC_HOME_AWAY"
    home = ds.metadata.teams[0]
    shots = [e for e in out.events if e.event_name == "shot" and e.coordinates]
    hx = [e.coordinates.x for e in shots if e.team == home]
    ax = [e.coordinates.x for e in shots if e.team != home]
    assert hx and ax
    assert sum(hx) / len(hx) > 0 and sum(ax) / len(ax) < 0
    first_pass = next(e for e in out.events if e.event_name == "pass" and e.coordinates)
    assert abs(first_pass.coordinates.x) < 3 and abs(first_pass.coordinates.y) < 3
    pts = [(e.coordinates.x, e.coordinates.y) for e in out.events if e.coordinates]
    assert out_of_bounds(pts, 105, 68) == 0
