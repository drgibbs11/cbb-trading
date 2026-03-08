#!/usr/bin/env python3
"""
seed_teams.py — Populate cbb_team_mapping in Supabase.
Run on every deploy: python cbb/seed_teams.py
"""

import os
import re
from supabase import create_client, Client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Each row: (kalshi_name, espn_id, espn_name, espn_abbr, conference)
# kalshi_name must be: lowercase, trimmed, no punctuation except &, single spaces
TEAMS = [
    # ACC
    ("duke", "150", "Duke Blue Devils", "DUKE", "ACC"),
    ("duke blue devils", "150", "Duke Blue Devils", "DUKE", "ACC"),
    ("north carolina", "153", "North Carolina Tar Heels", "UNC", "ACC"),
    ("unc", "153", "North Carolina Tar Heels", "UNC", "ACC"),
    ("tar heels", "153", "North Carolina Tar Heels", "UNC", "ACC"),
    ("virginia", "258", "Virginia Cavaliers", "UVA", "ACC"),
    ("uva", "258", "Virginia Cavaliers", "UVA", "ACC"),
    ("nc state", "152", "NC State Wolfpack", "NCST", "ACC"),
    ("ncsu", "152", "NC State Wolfpack", "NCST", "ACC"),
    ("clemson", "228", "Clemson Tigers", "CLEM", "ACC"),
    ("miami", "2390", "Miami Hurricanes", "MIA", "ACC"),
    ("florida state", "52", "Florida State Seminoles", "FSU", "ACC"),
    ("fsu", "52", "Florida State Seminoles", "FSU", "ACC"),
    ("georgia tech", "59", "Georgia Tech Yellow Jackets", "GT", "ACC"),
    ("wake forest", "154", "Wake Forest Demon Deacons", "WAKE", "ACC"),
    ("boston college", "103", "Boston College Eagles", "BC", "ACC"),
    ("bc", "103", "Boston College Eagles", "BC", "ACC"),
    ("pittsburgh", "221", "Pittsburgh Panthers", "PITT", "ACC"),
    ("pitt", "221", "Pittsburgh Panthers", "PITT", "ACC"),
    ("virginia tech", "259", "Virginia Tech Hokies", "VT", "ACC"),
    ("vt", "259", "Virginia Tech Hokies", "VT", "ACC"),
    ("louisville", "97", "Louisville Cardinals", "LOU", "ACC"),
    ("notre dame", "87", "Notre Dame Fighting Irish", "ND", "ACC"),
    ("syracuse", "183", "Syracuse Orange", "SYR", "ACC"),
    ("stanford", "24", "Stanford Cardinal", "STAN", "ACC"),
    ("cal", "25", "California Golden Bears", "CAL", "ACC"),
    ("california", "25", "California Golden Bears", "CAL", "ACC"),
    ("smu", "2567", "SMU Mustangs", "SMU", "ACC"),
    
    # Big Ten
    ("michigan", "130", "Michigan Wolverines", "MICH", "Big Ten"),
    ("michigan state", "127", "Michigan State Spartans", "MSU", "Big Ten"),
    ("msu", "127", "Michigan State Spartans", "MSU", "Big Ten"),
    ("ohio state", "194", "Ohio State Buckeyes", "OSU", "Big Ten"),
    ("osu", "194", "Ohio State Buckeyes", "OSU", "Big Ten"),
    ("indiana", "84", "Indiana Hoosiers", "IND", "Big Ten"),
    ("purdue", "2509", "Purdue Boilermakers", "PUR", "Big Ten"),
    ("iowa", "2294", "Iowa Hawkeyes", "IOWA", "Big Ten"),
    ("illinois", "356", "Illinois Fighting Illini", "ILL", "Big Ten"),
    ("maryland", "120", "Maryland Terrapins", "MD", "Big Ten"),
    ("minnesota", "135", "Minnesota Golden Gophers", "MINN", "Big Ten"),
    ("nebraska", "158", "Nebraska Cornhuskers", "NEB", "Big Ten"),
    ("northwestern", "77", "Northwestern Wildcats", "NW", "Big Ten"),
    ("penn state", "213", "Penn State Nittany Lions", "PSU", "Big Ten"),
    ("psu", "213", "Penn State Nittany Lions", "PSU", "Big Ten"),
    ("rutgers", "164", "Rutgers Scarlet Knights", "RUTG", "Big Ten"),
    ("wisconsin", "275", "Wisconsin Badgers", "WIS", "Big Ten"),
    ("ucla", "26", "UCLA Bruins", "UCLA", "Big Ten"),
    ("usc", "30", "USC Trojans", "USC", "Big Ten"),
    ("oregon", "2483", "Oregon Ducks", "ORE", "Big Ten"),
    ("washington", "264", "Washington Huskies", "WASH", "Big Ten"),
    
    # Big 12
    ("kansas", "2305", "Kansas Jayhawks", "KU", "Big 12"),
    ("ku", "2305", "Kansas Jayhawks", "KU", "Big 12"),
    ("baylor", "239", "Baylor Bears", "BAY", "Big 12"),
    ("texas", "251", "Texas Longhorns", "TEX", "Big 12"),
    ("texas tech", "2641", "Texas Tech Red Raiders", "TTU", "Big 12"),
    ("ttu", "2641", "Texas Tech Red Raiders", "TTU", "Big 12"),
    ("oklahoma", "201", "Oklahoma Sooners", "OU", "Big 12"),
    ("ou", "201", "Oklahoma Sooners", "OU", "Big 12"),
    ("oklahoma state", "197", "Oklahoma State Cowboys", "OKST", "Big 12"),
    ("okstate", "197", "Oklahoma State Cowboys", "OKST", "Big 12"),
    ("iowa state", "66", "Iowa State Cyclones", "ISU", "Big 12"),
    ("tcu", "2628", "TCU Horned Frogs", "TCU", "Big 12"),
    ("west virginia", "277", "West Virginia Mountaineers", "WVU", "Big 12"),
    ("wvu", "277", "West Virginia Mountaineers", "WVU", "Big 12"),
    ("kansas state", "2306", "Kansas State Wildcats", "KSU", "Big 12"),
    ("kstate", "2306", "Kansas State Wildcats", "KSU", "Big 12"),
    ("cincinnati", "2132", "Cincinnati Bearcats", "CIN", "Big 12"),
    ("ucf", "2116", "UCF Knights", "UCF", "Big 12"),
    ("byu", "252", "BYU Cougars", "BYU", "Big 12"),
    ("houston", "248", "Houston Cougars", "HOU", "Big 12"),
    ("arizona", "12", "Arizona Wildcats", "ARIZ", "Big 12"),
    ("arizona state", "9", "Arizona State Sun Devils", "ASU", "Big 12"),
    ("asu", "9", "Arizona State Sun Devils", "ASU", "Big 12"),
    ("utah", "254", "Utah Utes", "UTAH", "Big 12"),
    ("colorado", "38", "Colorado Buffaloes", "COLO", "Big 12"),
    
    # SEC
    ("alabama", "333", "Alabama Crimson Tide", "ALA", "SEC"),
    ("kentucky", "96", "Kentucky Wildcats", "UK", "SEC"),
    ("uk", "96", "Kentucky Wildcats", "UK", "SEC"),
    ("tennessee", "2633", "Tennessee Volunteers", "TENN", "SEC"),
    ("vols", "2633", "Tennessee Volunteers", "TENN", "SEC"),
    ("arkansas", "8", "Arkansas Razorbacks", "ARK", "SEC"),
    ("auburn", "2", "Auburn Tigers", "AUB", "SEC"),
    ("florida", "57", "Florida Gators", "FLA", "SEC"),
    ("georgia", "61", "Georgia Bulldogs", "UGA", "SEC"),
    ("lsu", "99", "LSU Tigers", "LSU", "SEC"),
    ("ole miss", "145", "Ole Miss Rebels", "MISS", "SEC"),
    ("mississippi state", "344", "Mississippi State Bulldogs", "MSST", "SEC"),
    ("missouri", "142", "Missouri Tigers", "MIZ", "SEC"),
    ("mizzou", "142", "Missouri Tigers", "MIZ", "SEC"),
    ("south carolina", "2579", "South Carolina Gamecocks", "SC", "SEC"),
    ("texas a&m", "245", "Texas A&M Aggies", "TAMU", "SEC"),
    ("vanderbilt", "238", "Vanderbilt Commodores", "VAN", "SEC"),
    
    # Big East
    ("uconn", "41", "Connecticut Huskies", "UCONN", "Big East"),
    ("villanova", "222", "Villanova Wildcats", "NOVA", "Big East"),
    ("marquette", "269", "Marquette Golden Eagles", "MARQ", "Big East"),
    ("st johns", "2599", "St. John's Red Storm", "STJ", "Big East"),
    ("georgetown", "46", "Georgetown Hoyas", "GTWN", "Big East"),
    ("seton hall", "2550", "Seton Hall Pirates", "HALL", "Big East"),
    ("providence", "2507", "Providence Friars", "PROV", "Big East"),
    ("creighton", "156", "Creighton Bluejays", "CREI", "Big East"),
    ("xavier", "2752", "Xavier Musketeers", "XAV", "Big East"),
    ("depaul", "305", "DePaul Blue Demons", "DEP", "Big East"),
    ("butler", "2086", "Butler Bulldogs", "BUT", "Big East"),
    
    # WCC
    ("gonzaga", "2250", "Gonzaga Bulldogs", "GONZ", "WCC"),
    ("saint mary's", "2608", "Saint Mary's Gaels", "SMC", "WCC"),
    ("san francisco", "2650", "San Francisco Dons", "SF", "WCC"),
    ("loyola marymount", "2361", "Loyola Marymount Lions", "LMU", "WCC"),
    ("lmu", "2361", "Loyola Marymount Lions", "LMU", "WCC"),
    ("pepperdine", "2492", "Pepperdine Waves", "PEPP", "WCC"),
    ("santa clara", "2615", "Santa Clara Broncos", "SCU", "WCC"),
    ("portland", "2501", "Portland Pilots", "PORT", "WCC"),
    
    # A-10
    ("dayton", "2168", "Dayton Flyers", "DAY", "A-10"),
    ("vcu", "2670", "VCU Rams", "VCU", "A-10"),
    ("richmond", "257", "Richmond Spiders", "RICH", "A-10"),
    ("loyola chicago", "309", "Loyola Chicago Ramblers", "LOYC", "A-10"),
    ("davidson", "2166", "Davidson Wildcats", "DAV", "A-10"),
    ("saint louis", "139", "Saint Louis Billikens", "SLU", "A-10"),
    
    # Mountain West
    ("san diego state", "21", "San Diego State Aztecs", "SDSU", "Mountain West"),
    ("sdsu", "21", "San Diego State Aztecs", "SDSU", "Mountain West"),
    ("nevada", "2440", "Nevada Wolf Pack", "NEV", "Mountain West"),
    ("unlv", "2439", "UNLV Rebels", "UNLV", "Mountain West"),
    ("boise state", "68", "Boise State Broncos", "BSU", "Mountain West"),
    ("new mexico", "167", "New Mexico Lobos", "UNM", "Mountain West"),
    ("colorado state", "36", "Colorado State Rams", "CSU", "Mountain West"),
    ("csu", "36", "Colorado State Rams", "CSU", "Mountain West"),
    ("fresno state", "278", "Fresno State Bulldogs", "FRES", "Mountain West"),
    ("wyoming", "2751", "Wyoming Cowboys", "WYO", "Mountain West"),
    ("utah state", "328", "Utah State Aggies", "USU", "Mountain West"),
]


def normalize(raw: str) -> str:
    """Must match engine normalization exactly."""
    s = raw.lower().strip()
    s = re.sub(r"[^a-z0-9 &]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def seed():
    rows = []
    seen = set()
    for (kalshi_name, espn_id, espn_name, espn_abbr, conference) in TEAMS:
        key = normalize(kalshi_name)
        if key in seen:
            print(f"  DUPLICATE KEY skipped: '{key}'")
            continue
        seen.add(key)
        rows.append({
            "kalshi_name": key,
            "espn_id": espn_id,
            "espn_name": espn_name,
            "espn_abbr": espn_abbr,
            "conference": conference,
        })

    print(f"Upserting {len(rows)} team mapping rows...")

    # Batch upsert in chunks of 100
    chunk_size = 100
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        result = supabase.table("cbb_team_mapping").upsert(
            chunk,
            on_conflict="kalshi_name"
        ).execute()
        print(f"  Chunk {i // chunk_size + 1}: {len(chunk)} rows upserted")

    print("Done. cbb_team_mapping is up to date.")


if __name__ == "__main__":
    seed()
