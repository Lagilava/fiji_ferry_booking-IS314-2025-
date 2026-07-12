"""Editorial content and photography for each port.

Single source of truth shared by the destinations page and the homepage, so the
two can't drift apart. Photos are real, licensed pictures of the actual places,
stored locally under ``static/images/destinations/`` rather than hot-linked from
a stock-photo CDN — the old remote URLs were unverified and several showed the
wrong subject entirely (Levuka rendered as a city skyline), while four ports had
no entry at all and silently fell back to one generic wave photo.

Attribution is a licence condition for the CC BY / CC BY-SA images below; the
credit line is rendered on the destinations page.
"""

DEFAULT_IMAGE = "images/destinations/suva.jpg"
DEFAULT_TAGLINE = "Fiji destination"
DEFAULT_BLURB = "A beautiful Fijian destination accessible by ferry."

# name -> {image (static path), tagline, blurb, credit}
PORTS = {
    "Nadi": {
        "image": "images/destinations/nadi.jpg",
        "tagline": "Western gateway",
        "blurb": "Fiji's vibrant western gateway — world-class resorts, duty-free shopping, "
                 "and the international airport.",
        "credit": "Maksym Kozlenko / Wikimedia Commons · CC BY-SA 4.0",
    },
    "Suva": {
        "image": "images/destinations/suva.jpg",
        "tagline": "Capital city",
        "blurb": "The capital: colonial architecture, the finest museums, and a lively "
                 "harbour waterfront where the cruise ships berth.",
        "credit": "Stemoc / Wikimedia Commons · CC0",
    },
    "Lautoka": {
        "image": "images/destinations/lautoka.jpg",
        "tagline": "Sugar city",
        "blurb": "Fiji's sugar city — flame trees along Vitogo Parade, a rich agricultural "
                 "heritage, and the northern gateway to the Yasawas.",
        "credit": "Kgx / Wikimedia Commons · CC BY-SA 4.0",
    },
    "Levuka": {
        "image": "images/destinations/levuka.jpg",
        "tagline": "Historic capital",
        "blurb": "Fiji's first capital and a UNESCO World Heritage Site — the colonial "
                 "shopfronts of Beach Street have barely changed in a century.",
        "credit": "Anton Leddin / Wikimedia Commons · CC BY-SA 3.0",
    },
    "Savusavu": {
        "image": "images/destinations/savusavu.jpg",
        "tagline": "Hidden gem",
        "blurb": "Hidden gem of Vanua Levu: hot springs, world-class pearl farms, and a "
                 "sheltered bay beloved by yachties.",
        "credit": "Spicy / Wikimedia Commons · CC BY 4.0",
    },
    "Taveuni": {
        "image": "images/destinations/taveuni.jpg",
        "tagline": "The Garden Island",
        "blurb": "The Garden Island — rainforest waterfalls, the Bouma trails, and some of "
                 "the finest soft-coral diving on earth.",
        "credit": "M Sundstrom / Wikimedia Commons · CC BY-SA 2.0",
    },
    "Kadavu (Vunisea)": {
        "image": "images/destinations/kadavu.jpg",
        "tagline": "Great Astrolabe Reef",
        "blurb": "Wild and unspoilt, fringed by the Great Astrolabe Reef — manta rays, "
                 "kayaking, and villages far from the tourist trail.",
        "credit": "Duncan Wright / Wikimedia Commons · CC BY-SA 3.0",
    },
    "Nabouwalu": {
        "image": "images/destinations/nabouwalu.jpg",
        "tagline": "Bua gateway",
        "blurb": "The quiet southern gateway to Vanua Levu, where the Bligh Water crossing "
                 "lands and the road north to Labasa begins.",
        "credit": "Mds08011 / Wikimedia Commons · CC BY 4.0",
    },
    "Natovi": {
        "image": "images/destinations/natovi.jpg",
        "tagline": "Inter-island hub",
        "blurb": "The busy jetty on Viti Levu's east coast connecting crossings to Ovalau, "
                 "Vanua Levu and beyond.",
        "credit": "catlin.wolfard / Wikimedia Commons · CC BY-SA 3.0",
    },
    "Rotuma": {
        "image": "images/destinations/rotuma.jpg",
        "tagline": "Fiji's far north",
        "blurb": "Remote and culturally distinct, 460 km north of the rest of Fiji — white "
                 "sand, volcanic peaks, and its own language.",
        "credit": "Mattbray / Wikimedia Commons · Public domain",
    },
}


def port_media(name):
    """Editorial content for a port, tolerant of names like ``Kadavu (Vunisea)``.

    Falls back to the bare first word so a renamed or newly seeded port still
    resolves, then to a neutral default rather than a wrong photo.
    """
    if name in PORTS:
        return PORTS[name]
    first = (name or "").split()[0] if name else ""
    for key, data in PORTS.items():
        if key.split()[0] == first:
            return data
    return {"image": DEFAULT_IMAGE, "tagline": DEFAULT_TAGLINE,
            "blurb": DEFAULT_BLURB, "credit": ""}
