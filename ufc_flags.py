"""
ufc_flags.py - a country flag next to each fighter's name.

The Odds API does NOT provide fighter nationalities, so this is a hand-kept
list, written from general knowledge. It is a DRAFT: please skim it.

 * A fighter not on the list simply shows without a flag. The run log prints
   "[flag] unmapped fighter: <name>" so you can see who to add.
 * Lines marked "# check" are ones where the "right" flag is debatable
   (born in one country, represents or fights out of another). Change them to
   whatever you prefer.
 * Names are matched ignoring accents, punctuation and "Jr." so small spelling
   differences are fine. If the API spells a name differently, add that
   spelling as another line.
"""

import re
import unicodedata

UFC_FLAGS = {
    # ---- Heavyweight ----
    "Tom Aspinall": "🇬🇧", "Ciryl Gane": "🇫🇷", "Sergei Pavlovich": "🇷🇺",
    "Sergey Pavlovich": "🇷🇺", "Alexander Volkov": "🇷🇺", "Curtis Blaydes": "🇺🇸",
    "Derrick Lewis": "🇺🇸", "Jailton Almeida": "🇧🇷", "Marcin Tybura": "🇵🇱",
    "Waldo Cortes-Acosta": "🇩🇴", "Serghei Spivac": "🇲🇩", "Tai Tuivasa": "🇦🇺",
    "Justin Tafa": "🇦🇺", "Josh Hokit": "🇺🇸", "Stipe Miocic": "🇺🇸",
    "Jon Jones": "🇺🇸", "Alexandr Romanov": "🇲🇩", "Shamil Gaziev": "🇷🇺",
    "Jhonata Diniz": "🇧🇷", "Mick Parkin": "🇦🇺",

    # ---- Light heavyweight ----
    "Alex Pereira": "🇧🇷", "Magomed Ankalaev": "🇷🇺", "Jiri Prochazka": "🇨🇿",
    "Jamahal Hill": "🇺🇸", "Carlos Ulberg": "🇳🇿", "Khalil Rountree Jr.": "🇺🇸",
    "Jan Blachowicz": "🇵🇱", "Azamat Murzakanov": "🇷🇺", "Nikita Krylov": "🇺🇦",
    "Dominick Reyes": "🇺🇸", "Johnny Walker": "🇧🇷", "Volkan Oezdemir": "🇨🇭",
    "Jimmy Crute": "🇦🇺", "Zhang Mingyang": "🇨🇳", "Oumar Sy": "🇫🇷",
    "Navajo Stirling": "🇺🇸", "Aleksandar Rakic": "🇦🇹", "Anthony Smith": "🇺🇸",

    # ---- Middleweight ----
    "Dricus du Plessis": "🇿🇦", "Sean Strickland": "🇺🇸", "Nassourdine Imavov": "🇫🇷",
    "Israel Adesanya": "🇳🇿", "Robert Whittaker": "🇦🇺", "Caio Borralho": "🇧🇷",
    "Reinier de Ridder": "🇳🇱", "Bo Nickal": "🇺🇸", "Paulo Costa": "🇧🇷",
    "Paulo Henrique Costa": "🇧🇷", "Jared Cannonier": "🇺🇸", "Marvin Vettori": "🇮🇹",
    "Brendan Allen": "🇺🇸", "Roman Dolidze": "🇬🇪", "Michel Pereira": "🇧🇷",
    "Joe Pyfer": "🇺🇸", "Joseph Pyfer": "🇺🇸", "Anthony Hernandez": "🇺🇸",
    "Chris Curtis": "🇺🇸", "Ikram Aliskerov": "🇷🇺", "Abusupiyan Magomedov": "🇷🇺",
    "Khamzat Chimaev": "🇦🇪",  # check: born in Chechnya, raised in Sweden, UFC lists UAE

    # ---- Welterweight ----
    "Jack Della Maddalena": "🇦🇺", "Belal Muhammad": "🇺🇸",  # check: walks out for Palestine
    "Leon Edwards": "🇬🇧", "Kamaru Usman": "🇳🇬",  # check: Nigerian-born, lives in the US
    "Colby Covington": "🇺🇸", "Shavkat Rakhmonov": "🇰🇿", "Ian Machado Garry": "🇮🇪",
    "Gilbert Burns": "🇧🇷", "Michael Morales": "🇪🇨", "Carlos Prates": "🇧🇷",
    "Geoff Neal": "🇺🇸", "Sean Brady": "🇺🇸", "Joaquin Buckley": "🇺🇸",
    "Stephen Thompson": "🇺🇸", "Vicente Luque": "🇧🇷", "Jorge Masvidal": "🇺🇸",
    "Daniel Rodriguez": "🇺🇸", "Kevin Holland": "🇺🇸", "Randy Brown": "🇯🇲",
    "Rinat Fakhretdinov": "🇷🇺", "Mike Malott": "🇨🇦", "Michael Chiesa": "🇺🇸",
    "Gabriel Bonfim": "🇧🇷",

    # ---- Lightweight ----
    "Islam Makhachev": "🇷🇺", "Charles Oliveira": "🇧🇷", "Arman Tsarukyan": "🇦🇲",
    "Justin Gaethje": "🇺🇸", "Dustin Poirier": "🇺🇸", "Paddy Pimblett": "🇬🇧",
    "Dan Hooker": "🇳🇿", "Mateusz Gamrot": "🇵🇱", "Renato Moicano": "🇧🇷",
    "Rafael Fiziev": "🇦🇿",  # check: born in Kyrgyzstan, fights for Azerbaijan
    "Benoit Saint Denis": "🇫🇷", "Michael Chandler": "🇺🇸", "Grant Dawson": "🇺🇸",
    "Jalin Turner": "🇺🇸", "Ignacio Bahamondes": "🇨🇱", "Chase Hooper": "🇺🇸",
    "Bobby Green": "🇺🇸", "Conor McGregor": "🇮🇪", "Daniel Zellhuber": "🇲🇽",

    # ---- Featherweight ----
    "Ilia Topuria": "🇪🇸",  # check: Georgian-Spanish, born in Germany
    "Alexander Volkanovski": "🇦🇺", "Movsar Evloev": "🇷🇺", "Aljamain Sterling": "🇺🇸",
    "Yair Rodriguez": "🇲🇽", "Brian Ortega": "🇺🇸", "Lerone Murphy": "🇬🇧",
    "Arnold Allen": "🇬🇧", "Josh Emmett": "🇺🇸", "Diego Lopes": "🇧🇷",
    "Jean Silva": "🇧🇷", "Steve Garcia": "🇺🇸", "Calvin Kattar": "🇺🇸",
    "Bryce Mitchell": "🇺🇸", "Giga Chikadze": "🇬🇪", "Dan Ige": "🇺🇸",
    "Edson Barboza": "🇧🇷", "Youssef Zalal": "🇲🇦", "Max Holloway": "🇺🇸",
    "Aaron Pico": "🇺🇸", "Nate Landwehr": "🇺🇸",

    # ---- Bantamweight ----
    "Merab Dvalishvili": "🇬🇪", "Petr Yan": "🇷🇺", "Sean O'Malley": "🇺🇸",
    "Umar Nurmagomedov": "🇷🇺", "Cory Sandhagen": "🇺🇸", "Song Yadong": "🇨🇳",
    "Henry Cejudo": "🇺🇸", "Marlon Vera": "🇪🇨", "Deiveson Figueiredo": "🇧🇷",
    "Mario Bautista": "🇺🇸", "Aiemann Zahabi": "🇨🇦", "Rob Font": "🇺🇸",
    "Raul Rosas Jr.": "🇺🇸", "Kyler Phillips": "🇺🇸", "Payton Talbott": "🇺🇸",
    "Montel Jackson": "🇺🇸", "Vinicius Oliveira": "🇧🇷", "David Martinez": "🇺🇸",

    # ---- Flyweight ----
    "Alexandre Pantoja": "🇧🇷", "Brandon Royval": "🇺🇸", "Brandon Moreno": "🇲🇽",
    "Joshua Van": "🇲🇲", "Kai Kara-France": "🇳🇿", "Tatsuro Taira": "🇯🇵",
    "Asu Almabayev": "🇰🇿", "Charles Johnson": "🇺🇸", "Tagir Ulanbekov": "🇷🇺",
    "Steve Erceg": "🇦🇺",

    # ---- Women ----
    "Amanda Nunes": "🇧🇷", "Kayla Harrison": "🇺🇸", "Valentina Shevchenko": "🇰🇬",
    "Alexa Grasso": "🇲🇽", "Natalia Silva": "🇧🇷", "Zhang Weili": "🇨🇳",
    "Tatiana Suarez": "🇺🇸", "Manon Fiorot": "🇫🇷", "Erin Blanchfield": "🇺🇸",
    "Julianna Pena": "🇺🇸", "Raquel Pennington": "🇺🇸", "Mackenzie Dern": "🇧🇷",
    "Virna Jandiroba": "🇧🇷", "Jessica Andrade": "🇧🇷", "Rose Namajunas": "🇺🇸",
    "Joanne Wood": "🇬🇧", "Maycee Barber": "🇺🇸", "Jasmine Jasudavicius": "🇨🇦",
    "Yan Xiaonan": "🇨🇳", "Carla Esparza": "🇺🇸", "Marina Rodriguez": "🇧🇷",
    "Mayra Bueno Silva": "🇧🇷", "Ketlen Vieira": "🇧🇷", "Macy Chiasson": "🇺🇸",
}

# Added after comparing against the live feed: other spellings the API uses,
# plus a few fighters who appeared in upcoming fights.
# Left out on purpose because I wasn't sure which flag fits: Manel Kape,
# Bolaji Oki, Losene Keita, Abubakar Vagaev, Noah Gugnon, Kody Steele.
UFC_FLAGS.update({
    "Alex Volkanovski": "🇦🇺", "Abusupyian Magomedov": "🇷🇺",
    "Abdulrakhman Yakhyaev": "🇷🇺", "Cam Rowston": "🇦🇺", "Daniel Santos": "🇧🇷",
    "Jacob Malkoun": "🇦🇺", "Lone'er Kavanagh": "🇬🇧", "Nurullo Aliev": "🇹🇯",
    "Ramazonbek Temirov": "🇺🇿", "Rizvan Kuniev": "🇷🇺",
})

# Words ignored when matching names.
_IGNORE = {"jr", "sr", "ii", "iii"}


def _norm(name):
    """Lowercase, strip accents and punctuation, drop 'Jr.' and similar."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return " ".join(w for w in re.findall(r"[a-z0-9]+", s) if w not in _IGNORE)


_LOOKUP = {_norm(name): flag for name, flag in UFC_FLAGS.items()}


def fighter_flag(name):
    """The flag for a fighter, or "" if they aren't on the list."""
    flag = _LOOKUP.get(_norm(name))
    if flag is None:
        print(f"[flag] unmapped fighter: {name}")
        return ""
    return flag
