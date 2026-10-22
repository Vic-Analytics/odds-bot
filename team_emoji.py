"""
team_emoji.py - a little emoji for each team, shown next to the team name.

TO CHANGE AN EMOJI: edit the line for that team below.
TO ADD A LEAGUE: add a new dictionary and list it in TEAM_EMOJI at the bottom.

How matching works: the API gives full names like "Houston Texans" or
"St. Louis Blues". We match on the NICKNAME at the end ("Texans", "Blues"),
so city spellings ("LA" vs "Los Angeles") don't matter. A team with no match
simply shows without an emoji.
"""

from config import SPORTS
from soccer_emoji import soccer_emoji
from ufc_flags import fighter_flag

NFL = {
    "Cardinals": "🐦", "Falcons": "🪶", "Ravens": "🐦‍⬛", "Bills": "🦬",
    "Panthers": "🐈‍⬛", "Bears": "🐻", "Bengals": "🐯", "Browns": "🐶",
    "Cowboys": "🤠", "Broncos": "🏔️", "Lions": "🦁", "Packers": "🧀",
    "Texans": "🐂", "Colts": "🐴", "Jaguars": "🐆", "Chiefs": "🏹",
    "Raiders": "☠️", "Chargers": "⚡", "Rams": "🐏", "Dolphins": "🐬",
    "Vikings": "⚔️", "Patriots": "🇺🇸", "Saints": "⚜️", "Giants": "🗽",
    "Jets": "✈️", "Eagles": "🦅", "Steelers": "⚙️", "49ers": "⛏️",
    "Seahawks": "🌲", "Buccaneers": "⚓", "Titans": "🔱", "Commanders": "🪖",
}

NBA = {
    "Hawks": "🦅", "Celtics": "☘️", "Nets": "🕸️", "Hornets": "🐝",
    "Bulls": "🐂", "Cavaliers": "🗡️", "Mavericks": "🐎", "Nuggets": "🥇",
    "Pistons": "⚙️", "Warriors": "🌉", "Rockets": "🚀", "Pacers": "🏎️",
    "Clippers": "⛵", "Lakers": "🌴", "Grizzlies": "🐻", "Heat": "🔥",
    "Bucks": "🦌", "Timberwolves": "🐺", "Pelicans": "⚜️", "Knicks": "🗽",
    "Thunder": "⛈️", "Magic": "✨", "76ers": "🔔", "Suns": "☀️",
    "Trail Blazers": "🌲", "Kings": "👑", "Spurs": "🌵", "Raptors": "🦖",
    "Jazz": "🎷", "Wizards": "🧙",
}

NHL = {
    "Ducks": "🦆", "Bruins": "🐻", "Sabres": "🗡️", "Flames": "🔥",
    "Hurricanes": "🌀", "Blackhawks": "🪶", "Avalanche": "🏔️", "Blue Jackets": "🧥",
    "Stars": "⭐", "Red Wings": "🛞", "Oilers": "🛢️", "Panthers": "🐆",
    "Kings": "👑", "Wild": "🌲", "Canadiens": "⚜️", "Predators": "🐯",
    "Devils": "😈", "Islanders": "🏝️", "Rangers": "🗽", "Senators": "🏛️",
    "Flyers": "🟠", "Penguins": "🐧", "Sharks": "🦈", "Kraken": "🐙",
    "Blues": "🎵", "Lightning": "⚡", "Maple Leafs": "🍁",
    "Mammoth": "🦣", "Hockey Club": "🦣",   # Utah's team has used both names
    "Canucks": "🐳", "Golden Knights": "🛡️", "Capitals": "🦅", "Jets": "✈️",
}

MLB = {
    "Diamondbacks": "🐍", "Braves": "🪓", "Athletics": "🐘", "Orioles": "🟠",
    "Red Sox": "🧦", "Cubs": "🐻", "White Sox": "🖤", "Reds": "🔴",
    "Guardians": "🛡️", "Rockies": "🏔️", "Tigers": "🐯", "Astros": "🌠",
    "Royals": "👑", "Angels": "😇", "Dodgers": "💙", "Marlins": "🐟",
    "Brewers": "🍺", "Twins": "👬", "Mets": "🍎", "Yankees": "🎩",
    "Phillies": "🔔", "Pirates": "🏴‍☠️", "Padres": "🟤", "Giants": "🌉",
    "Mariners": "🧭", "Cardinals": "🐦", "Rays": "☀️", "Rangers": "🤠",
    "Blue Jays": "🍁", "Nationals": "🏛️",
}

WNBA = {
    "Dream": "🌙", "Sky": "☁️", "Sun": "☀️",
    "Comets": "☄️",          # a Houston team starting in 2027, per your list (unverified)
    "Wings": "🪽",           # newer emoji; swap to 🕊️ if it shows as a box
    "Valkyries": "⚔️", "Fever": "🌡️", "Aces": "♠️", "Sparks": "✨",
    "Lynx": "🐈", "Liberty": "🗽", "Mercury": "🪐", "Fire": "🔥",
    "Storm": "⛈️", "Tempo": "🎵", "Mystics": "🔮",
}

# Which dictionary belongs to which league name in config.py's SPORTS.
TEAM_EMOJI = {"NFL": NFL, "NBA": NBA, "NHL": NHL, "MLB": MLB, "WNBA": WNBA}


def emoji_for(sport_name, team_name):
    """Return the emoji for a team, or "" if the league or team isn't mapped."""
    nicknames = TEAM_EMOJI.get(sport_name)
    if not nicknames:
        return ""
    name = team_name.strip().lower()
    for nickname, emoji in nicknames.items():
        nick = nickname.lower()
        # Match whole words at the END of the name: "kings" matches
        # "Los Angeles Kings" but not something like "Bookings".
        if name == nick or name.endswith(" " + nick):
            return emoji
    return ""


def team_label(sport_name, team_name):
    """The team name with its emoji in front, e.g. '🐂 Houston Texans'."""
    is_soccer = SPORTS.get(sport_name, "").startswith("soccer_")

    # In soccer, every row gets exactly two emoji so the names line up:
    # clubs show two kit-color dots, and the Draw row gets two handshakes.
    # (Telegram text isn't monospaced, so matching the emoji width is what
    # keeps the team names and the Draw label in a straight column.)
    if team_name == "Draw":
        return "\U0001F91D\U0001F91D Draw" if is_soccer else team_name

    # Soccer clubs get kit-color dots from soccer_emoji.py (a club it doesn't
    # know shows a plain soccer ball and is reported in the run log).
    if is_soccer:
        dots = soccer_emoji(team_name)
        if len(dots) == 1:        # a one-color kit: show the dot twice
            dots = dots * 2
        return f"{dots} {team_name}"

    # Fighters get a country flag from ufc_flags.py, if they're on that list.
    if SPORTS.get(sport_name, "").startswith("mma_"):
        flag = fighter_flag(team_name)
        return f"{flag} {team_name}" if flag else team_name

    emoji = emoji_for(sport_name, team_name)
    return f"{emoji} {team_name}" if emoji else team_name
