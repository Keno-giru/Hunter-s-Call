"""Catalogue of data sources: what each holds, its licence, how to get it and which converter applies.

Facts checked on the source pages in Nov 2026. Kaggle downloads run on your machine with your own
Kaggle API token (~/.kaggle/kaggle.json or KAGGLE_USERNAME / KAGGLE_KEY). Licences are summaries:
read the source page before publishing anything derived from a dataset.
"""

SOURCES = [
    # ------------------------------------------------------------ Kaggle
    {"id": "teamtrack", "provider": "kaggle", "kaggle": "atomscott/teamtrack", "kind": ["footage", "detection", "tracking"],
     "licence": "MIT", "size": "17.73 GB",
     "what": "Full-pitch video (soccer side fisheye 8K and drone top view 4K, 30 min each; also basketball and handball) "
             "with 4.37 M boxes. Three layouts: teamtrack (SportsLabKit CSV), teamtrack-mot (MOTChallenge), "
             "teamtrack-trajectory (positions in pitch coordinates).",
     "use": "detection training (mot), footage + tracking ingest (positions-csv after `galileo.py inspect`)",
     "url": "https://www.kaggle.com/datasets/atomscott/teamtrack"},
    {"id": "soccertrack", "provider": "kaggle", "kaggle": "atomscott/soccertrack", "kind": ["footage", "detection", "tracking"],
     "licence": "LGPL-3.0", "size": "large (several GB, check the page)",
     "what": "11v11 university matches: wide-view 8K and drone 4K video at 30 fps with boxes for players and ball, "
             "player ids, and 10 Hz GNSS positions per player.",
     "use": "detection training; footage with ground-truth positions for testing calibration",
     "url": "https://www.kaggle.com/datasets/atomscott/soccertrack"},
    {"id": "field-keypoints", "provider": "kaggle", "kaggle": "hamzaboulahia/football-field-keypoints-dataset",
     "kind": ["keypoints"], "licence": "Apache-2.0", "size": "342 images",
     "what": "Tactical view from behind a goal; 28 landmark classes as YOLO boxes (corners, 6 m and 18 m boxes, arcs, "
             "halfway line). train 262 / val 80.",
     "use": "pitch keypoint model -> auto calibration (`galileo.py train-set keypoints`)",
     "url": "https://www.kaggle.com/datasets/hamzaboulahia/football-field-keypoints-dataset"},
    {"id": "players-detection", "provider": "kaggle", "kaggle": "hamzaboulahia/football-players-detection-dataset",
     "kind": ["detection"], "licence": "Apache-2.0", "size": "600 images",
     "what": "Same tactical view; YOLO boxes for player / referee / ball. train 520 / val 80.",
     "use": "detection training (`galileo.py train-set detection`)",
     "url": "https://www.kaggle.com/datasets/hamzaboulahia/football-players-detection-dataset"},
    {"id": "transfermarkt", "provider": "kaggle", "kaggle": "davidcariboo/player-scores", "kind": ["context"],
     "licence": "CC0-1.0", "size": "CSV set",
     "what": "88k+ games, 50k+ players, 1.89 M appearances, 1.27 M game events (goals, cards, subs), lineups, "
             "valuations, transfers. Updates paused: current to 6 July 2026.",
     "use": "rosters, names and minutes to enrich packs; long-run player context",
     "url": "https://www.kaggle.com/datasets/davidcariboo/player-scores"},
    {"id": "european-soccer", "provider": "kaggle", "kaggle": "hugomathien/soccer", "kind": ["context"],
     "licence": "non-commercial (author's request; attributes from EA FIFA, odds from football-data.co.uk)",
     "size": "SQLite",
     "what": "25k+ matches, 10k+ players, 11 leagues, 2008-2016; lineups with formation X/Y; event summaries.",
     "use": "formation priors and role labels; historical context",
     "url": "https://www.kaggle.com/datasets/hugomathien/soccer"},
    {"id": "dfl-shootout", "provider": "kaggle", "kaggle": None, "kind": ["footage"], "licence": "competition rules",
     "size": "n/a",
     "what": "DFL Bundesliga Data Shootout (2022): Bundesliga video with play / challenge / throw-in labels. "
             "The competition page now says the data is no longer available.",
     "use": "not obtainable; its label scheme is mirrored by `galileo.py clips` for your own footage",
     "url": "https://www.kaggle.com/competitions/dfl-bundesliga-data-shootout/data"},
    # ------------------------------------------------------------ open repositories (kloppy loads these)
    {"id": "metrica", "provider": "github", "kind": ["tracking", "events"],
     "licence": "free sample; acknowledge Metrica Sports if used publicly", "size": "~190 MB (3 games)",
     "what": "3 anonymised full games: tracking 25 Hz for all players and ball, synchronised events, 105 x 68 m.",
     "use": "`galileo.py convert metrica --game 1|2|3`",
     "url": "https://github.com/metrica-sports/sample-data"},
    {"id": "skillcorner", "provider": "github", "kind": ["tracking", "events"],
     "licence": "SkillCorner Open Data (credit SkillCorner; repo MIT)", "size": "per match",
     "what": "A-League 2024/25 broadcast tracking at 10 Hz with dynamic events and phases (the hub's sample pack).",
     "use": "`galileo.py convert skillcorner --match <id>`",
     "url": "https://github.com/SkillCorner/opendata"},
    {"id": "idsse", "provider": "figshare", "kind": ["tracking", "events"], "licence": "CC-BY-4.0", "size": "~7 matches",
     "what": "IDSSE: 7 Bundesliga 2022/23 matches, TRACAB tracking at 25 fps for all players and ball, official events.",
     "use": "`galileo.py convert idsse --match <id>` (kloppy sportec loader)",
     "url": "https://doi.org/10.1038/s41597-025-04505-y"},
    {"id": "statsbomb", "provider": "github", "kind": ["events"], "licence": "StatsBomb open data user agreement (non-commercial)",
     "size": "large repo",
     "what": "Event data for many competitions; 360 freeze frames (player locations in camera view) for selected ones.",
     "use": "`galileo.py events statsbomb --match <id>` -> events.csv for action models",
     "url": "https://github.com/statsbomb/open-data"},
    {"id": "wyscout", "provider": "figshare", "kind": ["events"], "licence": "CC-BY-4.0", "size": "~1.9k matches",
     "what": "Pappalardo et al. 2019: every event of 2017/18 top-5 leagues, World Cup 2018 and Euro 2016.",
     "use": "event models (xT/VAEP via socceraction)",
     "url": "https://figshare.com/collections/Soccer_match_event_dataset/4415000"},
    {"id": "soccernet", "provider": "soccernet", "kind": ["footage", "detection", "keypoints", "tracking"],
     "licence": "NDA for videos; annotations per task", "size": "very large",
     "what": "550 broadcast games, tracking (200 clips, MOT format), game-state reconstruction, camera calibration.",
     "use": "MOT -> `galileo.py train-set detection --mot`; calibration research",
     "url": "https://www.soccer-net.org"},
]

BY_ID = {s["id"]: s for s in SOURCES}


def kaggle_command(src, dest):
    slug = src.get("kaggle")
    if not slug:
        return None
    return ["kaggle", "datasets", "download", "-d", slug, "-p", str(dest), "--unzip"]
