import re
import unicodedata

# Kit-color circles for each club. One circle = one main color, two = two-color kit.
SOCCER_EMOJI = {
    # ---- Premier League 2026-27 ----
    "Arsenal": "🔴⚪",
    "Aston Villa": "🟤🔵",
    "Bournemouth": "🔴⚫",
    "Brentford": "🔴⚪",
    "Brighton and Hove Albion": "🔵⚪",
    "Chelsea": "🔵",
    "Coventry City": "🔵⚪",
    "Crystal Palace": "🔴🔵",
    "Everton": "🔵",
    "Fulham": "⚪⚫",
    "Hull City": "🟠⚫",
    "Ipswich Town": "🔵⚪",
    "Leeds United": "⚪",
    "Liverpool": "🔴",
    "Manchester City": "🔵",
    "Manchester United": "🔴",
    "Newcastle United": "⚫⚪",
    "Nottingham Forest": "🔴",
    "Sunderland": "🔴⚪",
    "Tottenham Hotspur": "⚪🔵",

    # ---- La Liga 2026-27 ----
    "Alavés": "🔵⚪",
    "Athletic Bilbao": "🔴⚪",
    "Atlético Madrid": "🔴⚪",
    "Barcelona": "🔵🔴",
    "Celta Vigo": "🔵",
    "Deportivo La Coruña": "🔵⚪",
    "Elche": "⚪🟢",
    "Espanyol": "🔵⚪",
    "Getafe": "🔵",
    "Levante": "🔵🔴",
    "Málaga": "🔵⚪",
    "Osasuna": "🔴🔵",
    "Racing Santander": "⚪🟢",
    "Rayo Vallecano": "⚪🔴",
    "Real Betis": "🟢⚪",
    "Real Madrid": "⚪",
    "Real Sociedad": "🔵⚪",
    "Sevilla": "⚪🔴",
    "Valencia": "⚪⚫",
    "Villarreal": "🟡",

    # ---- Serie A 2026-27 ----
    "Atalanta": "🔵⚫",
    "Bologna": "🔴🔵",
    "Cagliari": "🔴🔵",
    "Como": "🔵",
    "Fiorentina": "🟣",
    "Frosinone": "🟡🔵",
    "Genoa": "🔴🔵",
    "Inter Milan": "🔵⚫",
    "Juventus": "⚫⚪",
    "Lazio": "🔵⚪",
    "Lecce": "🟡🔴",
    "AC Milan": "🔴⚫",
    "Monza": "🔴⚪",
    "Napoli": "🔵",
    "Parma": "🟡🔵",
    "AS Roma": "🔴🟡",
    "Sassuolo": "🟢⚫",
    "Torino": "🟤",
    "Udinese": "⚫⚪",
    "Venezia": "⚫🟠",

    # ---- Bundesliga 2026-27 ----
    "Augsburg": "🔴🟢",
    "Union Berlin": "🔴⚪",
    "Werder Bremen": "🟢⚪",
    "Borussia Dortmund": "🟡⚫",
    "SV Elversberg": "⚫⚪",
    "Eintracht Frankfurt": "⚫🔴",
    "SC Freiburg": "🔴⚪",
    "Hamburger SV": "⚪🔵",
    "TSG Hoffenheim": "🔵⚪",
    "1. FC Köln": "⚪🔴",
    "RB Leipzig": "⚪🔴",
    "Bayer Leverkusen": "🔴⚫",
    "Mainz 05": "🔴⚪",
    "Borussia Mönchengladbach": "⚪🟢",
    "Bayern Munich": "🔴⚪",
    "SC Paderborn": "🔵⚫",
    "Schalke 04": "🔵⚪",
    "VfB Stuttgart": "⚪🔴",

    # ---- MLS 2026 ----
    "Atlanta United FC": "🔴⚫",
    "Austin FC": "🟢⚫",
    "CF Montréal": "🔵⚫",
    "Charlotte FC": "🔵⚫",
    "Chicago Fire FC": "🔴🔵",
    "Colorado Rapids": "🟤🔵",
    "Columbus Crew": "🟡⚫",
    "D.C. United": "⚫🔴",
    "FC Cincinnati": "🟠🔵",
    "FC Dallas": "🔴🔵",
    "Houston Dynamo FC": "🟠⚫",
    "Inter Miami CF": "🩷⚫",
    "LA Galaxy": "🔵🟡",
    "Los Angeles FC": "⚫🟡",
    "Minnesota United FC": "⚫🔵",
    "Nashville SC": "🟡🔵",
    "New England Revolution": "🔵🔴",
    "New York City FC": "🔵⚪",
    "New York Red Bulls": "🔴⚪",
    "Orlando City SC": "🟣",
    "Philadelphia Union": "🔵🟡",
    "Portland Timbers": "🟢🟡",
    "Real Salt Lake": "🔴🔵",
    "San Diego FC": "🔵⚫",
    "San Jose Earthquakes": "⚫🔵",
    "Seattle Sounders FC": "🟢🔵",
    "Sporting Kansas City": "🔵⚪",
    "St. Louis City SC": "🔴🔵",
    "Toronto FC": "🔴⚫",
    "Vancouver Whitecaps FC": "⚪🔵",
}

# ---- Added later: Ligue 1 and European-competition clubs from outside the
# big-five leagues, using the spellings The Odds API uses. These colors were
# filled in from general knowledge, so double-check any you care about.
# Clubs whose colors weren't certain (Sabah FK, FC Ararat-Armenia, NK Celje,
# OFI Crete, Torreense) are left out on purpose and show a plain soccer ball.
SOCCER_EMOJI.update({
    # Ligue 1
    "AS Monaco": "🔴⚪", "Angers": "⚫⚪", "Auxerre": "⚪🔵", "Brest": "🔴⚪",
    "Le Havre": "🔵", "Le Mans FC": "🟡🔴", "Lille": "🔴", "Lorient": "🟠⚫",
    "Lyon": "⚪🔴", "Marseille": "⚪🔵", "Nice": "🔴⚫", "Paris FC": "🔵⚪",
    "Paris Saint Germain": "🔵🔴", "RC Lens": "🟡🔴", "Rennes": "🔴⚫",
    "Strasbourg": "🔵⚪", "Toulouse": "🟣⚪", "Troyes": "🔵⚪",
    # Champions League regulars
    "AEK Athens": "🟡⚫", "Bodø/Glimt": "🟡⚫", "Club Brugge": "🔵⚫",
    "Fenerbahce": "🟡🔵", "Feyenoord": "🔴⚪", "Galatasaray": "🟡🔴",
    "LASK": "⚪⚫", "PSV Eindhoven": "🔴⚪", "Porto": "🔵⚪",
    "Shakhtar Donetsk": "🟠⚫", "Slavia Praha": "🔴⚪", "Sporting Lisbon": "🟢⚪",
    "Viking FK": "🔵⚪", "ŠK Slovan Bratislava": "🔵⚪",
    # Europa League regulars
    "AZ Alkmaar": "🔴⚪", "Anderlecht": "🟣⚪", "Benfica": "🔴⚪",
    "Besiktas JK": "⚫⚪", "Celtic": "🟢⚪", "Dinamo Zagreb": "🔵",
    "Ferencváros TC": "🟢⚪", "Hapoel Be'er Sheva": "🔴⚪",
    "Jagiellonia Białystok": "🟡🔴", "Lech Poznań": "🔵⚪", "Lillestrom": "🟡⚫",
    "NEC Nijmegen": "🟢🔴", "Olympiakos Piraeus": "🔴⚪", "Omonoia FC": "🟢⚪",
    "PFC Levski Sofia": "🔵⚪", "SK Sturm Graz": "⚫⚪", "Salzburg": "🔴⚪",
    "Sparta Prague": "🔴🔵", "Union Saint-Gilloise": "🟡🔵",
    "Viktoria Plzeň": "🔴🔵",
})

# Other spellings the odds API (or anyone) might use -> the name used above.
SOCCER_ALIASES = {
    "AFC Bournemouth": "Bournemouth",
    "Brighton & Hove Albion": "Brighton and Hove Albion",
    "Brighton": "Brighton and Hove Albion",
    "Tottenham": "Tottenham Hotspur",
    "Spurs": "Tottenham Hotspur",
    "Man City": "Manchester City",
    "Man United": "Manchester United",
    "Newcastle": "Newcastle United",
    "Leeds": "Leeds United",
    "Ipswich": "Ipswich Town",
    "Athletic Club": "Athletic Bilbao",
    "Atletico de Madrid": "Atlético Madrid",
    "Deportivo": "Deportivo La Coruña",
    "RC Deportivo": "Deportivo La Coruña",
    "RCD Espanyol": "Espanyol",
    "Betis": "Real Betis",
    "Racing": "Racing Santander",
    "Rayo": "Rayo Vallecano",
    "Inter": "Inter Milan",
    "Internazionale": "Inter Milan",
    "Milan": "AC Milan",
    "Roma": "AS Roma",
    "Bayern München": "Bayern Munich",
    "Bayern Munchen": "Bayern Munich",
    "FC Koln": "1. FC Köln",
    "FC Koeln": "1. FC Köln",
    "Cologne": "1. FC Köln",
    "Köln": "1. FC Köln",
    "Gladbach": "Borussia Mönchengladbach",
    "Borussia Moenchengladbach": "Borussia Mönchengladbach",
    "Frankfurt": "Eintracht Frankfurt",
    "Freiburg": "SC Freiburg",
    "Hoffenheim": "TSG Hoffenheim",
    "Hamburg": "Hamburger SV",
    "Leipzig": "RB Leipzig",
    "Leverkusen": "Bayer Leverkusen",
    "Mainz": "Mainz 05",
    "Paderborn": "SC Paderborn",
    "Schalke": "Schalke 04",
    "Stuttgart": "VfB Stuttgart",
    "Elversberg": "SV Elversberg",
    "Montreal Impact": "CF Montréal",
    "DC United": "D.C. United",
    "LAFC": "Los Angeles FC",
    "Minnesota United": "Minnesota United FC",
    "NYCFC": "New York City FC",
    "Sporting KC": "Sporting Kansas City",
    "St Louis City": "St. Louis City SC",
    "Vancouver Whitecaps": "Vancouver Whitecaps FC",
}

# Spellings The Odds API actually uses that differ from the names above.
SOCCER_ALIASES.update({
    "CA Osasuna": "Osasuna",
    "Real Racing Club de Santander": "Racing Santander",
    "Atalanta BC": "Atalanta",
    "FSV Mainz 05": "Mainz 05",
})

_DROP = {"fc", "cf", "afc", "sc", "sv", "club", "de", "the"}

def _norm(name: str) -> str:
    """Lowercase, strip accents/punctuation, drop 'FC'/'CF'/numbers etc."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", "and")
    words = re.findall(r"[a-z]+", s)
    return " ".join(w for w in words if w not in _DROP)

_LOOKUP = {_norm(k): v for k, v in SOCCER_EMOJI.items()}
_LOOKUP.update({_norm(a): SOCCER_EMOJI[c] for a, c in SOCCER_ALIASES.items()})

def soccer_emoji(name: str) -> str:
    emoji = _LOOKUP.get(_norm(name))
    if emoji is None:
        print(f"[emoji] unmapped soccer team: {name}")
        return "⚽"
    return emoji

def soccer_label(name: str) -> str:
    return f"{soccer_emoji(name)} {name}"
