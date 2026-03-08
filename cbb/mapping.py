import re


def normalize(raw: str) -> str:
    """
    Normalize a raw Kalshi team name for lookup.
    Must be byte-for-byte identical to seed_teams.normalize().
    Steps: lowercase → strip → remove all punctuation except & → collapse spaces
    """
    s = raw.lower().strip()
    s = re.sub(r"[^a-z0-9 &]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def strip_ranking(raw: str) -> str:
    """
    Remove ESPN/Kalshi ranking prefix like 'No. 3 Michigan' → 'Michigan'
    Handles: 'No. 3', 'No 3', '#3', '(3)'
    """
    s = re.sub(r"^(no\.?\s*\d+\s+|#\d+\s+|\(\d+\)\s*)", "", raw, flags=re.IGNORECASE)
    return s.strip()


def lookup_team(supabase_client, raw_kalshi_name: str) -> dict | None:
    """
    Look up a team in the Supabase cbb_team_mapping table.
    Returns dict with keys: espn_id, espn_name, espn_abbr, conference
    Returns None if not found.
    """
    cleaned = strip_ranking(raw_kalshi_name)
    key = normalize(cleaned)

    result = supabase_client.table("cbb_team_mapping") \
        .select("espn_id, espn_name, espn_abbr, conference") \
        .eq("kalshi_name", key) \
        .limit(1) \
        .execute()

    if result.data:
        return result.data[0]
    return None


def parse_kalshi_title(title: str) -> tuple[str, str] | None:
    """
    Parse a Kalshi event title into two team name strings.
    Handles formats:
      'Duke vs North Carolina'
      'Will Duke win vs North Carolina?'
      'Michigan State vs Purdue'
    Returns (team_a, team_b) or None if unparseable.
    """
    # Strip 'Will ... win' wrapper
    title = re.sub(r"^will\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+win\??$", "", title, flags=re.IGNORECASE)
    title = title.rstrip("?").strip()

    # Split on ' vs ' (with optional period)
    parts = re.split(r"\s+vs\.?\s+", title, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None

    return parts[0].strip(), parts[1].strip()
