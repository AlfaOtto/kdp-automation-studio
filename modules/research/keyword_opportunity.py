"""
Golden Keyword Opportunity Finder
===================================
Stratégie experte : trouver des keywords avec FORTE DEMANDE + FAIBLE CONCURRENCE.

Méthode utilisée :
- L'API autocomplete d'Amazon retourne les suggestions DANS L'ORDRE de fréquence de recherche.
  → Position 0 = le plus recherché. On utilise ça comme proxy de volume de recherche GRATUIT.
- On combine : position autocomplete (demande) + nombre de reviews (concurrence)
- Score d'or = forte demande × faible concurrence

C'est la même logique que Publisher Rocket, mais gratuit.
"""
import time
import logging
from typing import List, Dict, Optional, Callable

logger = logging.getLogger(__name__)


# ─── Seeds larges pour expansion autocomplete ──────────────────────────────────
# Ces termes courts déclenchent des dizaines de suggestions ultra-spécifiques.
# La position dans l'autocomplete = signal de volume de recherche Amazon.

GOLDEN_BROAD_SEEDS = {

    # ── QUIZ & TRIVIA ─────────────────────────────────────────────────────────
    "quiz_trivia": [
        "trivia book for",
        "quiz book for",
        "fun facts book for",
        "did you know book",
        "trivia questions",
        "pub quiz book",
        "trivia night book",
        "bible trivia",
        "sports trivia",
        "movie trivia",
        "music trivia book",
        "history trivia",
        "science trivia",
        "kids trivia",
        "would you rather book",
        "never have i ever book",
        "truth or dare book",
        "this or that book",
    ],

    # ── NICHES BIZARRES & INSOLITES ───────────────────────────────────────────
    "bizarre_unusual": [
        "dark humor journal",
        "sarcastic notebook",
        "funny log book",
        "conspiracy theory notebook",
        "paranormal investigation journal",
        "ghost hunting log",
        "true crime journal",
        "serial killer trivia",
        "cryptid research log",
        "bigfoot activity book",
        "alien encounter journal",
        "horror coloring book",
        "gothic journal",
        "witchcraft moon journal",
        "tarot reading journal",
        "astrology journal",
        "numerology workbook",
        "doomsday prepper log",
        "zombie survival journal",
        "cursed coloring book",
        "dark academia journal",
        "nihilism notebook",
        "existential crisis journal",
        "introvert survival guide",
        "antisocial activity book",
    ],

    # ── DEMOGRAPHY NICHES (public ultra-précis) ───────────────────────────────
    "demographic_specific": [
        "journal for men who",
        "notebook for people who",
        "activity book for adults who",
        "planner for people with",
        "workbook for women who",
        "gift book for someone who",
        "book for cat people",
        "book for dog moms",
        "book for plant parents",
        "book for gamers",
        "book for runners",
        "book for hikers",
        "book for cyclists",
        "book for swimmers",
    ],

    # ── UNTAPPED LOGS & TRACKERS ──────────────────────────────────────────────
    "untapped_logs": [
        "log book for hobbyist",
        "collector log book",
        "vintage collector log",
        "sneaker collection log",
        "vinyl record collection log",
        "comic book collection log",
        "trading card log book",
        "lego collection log",
        "stamp collector log",
        "coin collector log",
        "sports card collector",
        "diecast car collector log",
        "funko pop collection log",
        "recipe creation log",
        "homebrew recipe journal",
        "candle making log",
        "soap making recipe log",
        "resin art project log",
        "3d printing project log",
        "cross stitch project log",
        "embroidery project log",
        "knitting pattern log",
        "crochet project journal",
    ],

    # ── TRENDING SEARCHES ─────────────────────────────────────────────────────
    "trending": [
        "adhd productivity",
        "autism acceptance",
        "neurodivergent journal",
        "highly sensitive person",
        "empath journal",
        "shadow work",
        "inner child healing",
        "decolonize journal",
        "afrofuturism coloring",
        "cottagecore",
        "dark cottagecore",
        "goblincore",
        "fairycore",
        "solarpunk notebook",
        "cyberpunk log book",
        "steampunk journal",
        "retro gaming",
        "analog horror",
        "liminal space",
    ],
}

# Seeds spécifiquement pour quiz books (très rentables, peu concurrencés)
QUIZ_BOOK_SEEDS = [
    "trivia book for seniors",
    "trivia book for kids",
    "pub quiz book",
    "bible trivia book",
    "sports trivia book for men",
    "movie trivia book",
    "music trivia book 70s 80s",
    "history trivia book",
    "science trivia book for kids",
    "geography trivia book",
    "Harry Potter trivia book",
    "Disney trivia book",
    "football trivia book",
    "basketball trivia book",
    "Friends TV show trivia book",
    "Office TV show trivia book",
    "Seinfeld trivia book",
    "road trip trivia book",
    "date night trivia book",
    "family game night trivia",
    "Christmas trivia book",
    "holiday trivia book",
    "black history trivia book",
    "womens history trivia book",
    "1000 trivia questions book",
    "random facts book for adults",
    "weird facts book",
    "amazing facts book for kids",
    "would you rather book adults",
    "would you rather book kids",
    "never have i ever adults",
    "conversation starter book",
    "this or that book couples",
    "icebreaker questions book",
]

# Niches bizarres spécifiques (ultra low competition)
BIZARRE_NICHE_SEEDS = [
    "dark humor journal for adults",
    "sarcastic daily planner",
    "sarcastic notebook for coworkers",
    "conspiracy theory planner",
    "paranormal activity log book",
    "ghost hunting evidence log",
    "cryptid sighting journal",
    "bigfoot tracker log book",
    "ufo sighting journal",
    "alien contact log",
    "true crime notebook",
    "serial killer history trivia",
    "horror movie trivia book",
    "haunted house coloring book",
    "gothic art coloring book",
    "horror coloring book for adults",
    "skeleton anatomy coloring book",
    "macabre coloring book",
    "tarot journal for beginners",
    "moon ritual journal",
    "witch grimoire notebook",
    "spell book journal",
    "zodiac journal for aries",  # Each sign = separate product
    "astrology birth chart journal",
    "crystal healing journal",
    "chakra balancing journal",
    "doomsday prepper supply log",
    "survival prepper journal",
    "zombie apocalypse survival log",
    "dark academia aesthetic journal",
    "nihilism philosophy journal",
    "existential dread journal",
    "antisocial butterfly notebook",
    "introvert social battery tracker",
    "chaotic evil planner",
    "villain era journal",
    "main character energy journal",
    "cottagecore nature journal",
    "goblincore foraging log",
    "weirdcore art journal",
]


def _position_to_demand(position: int) -> float:
    """
    Convertit la position autocomplete en score de demande.
    Position 0 (premier résultat) = plus forte demande = score 95.
    """
    table = {0: 95, 1: 88, 2: 82, 3: 76, 4: 70, 5: 64, 6: 58, 7: 52, 8: 46, 9: 40, 10: 34}
    return float(table.get(position, 28))


def expand_via_autocomplete(
    seeds: List[str],
    region: str = "US",
    status_callback: Optional[Callable] = None,
) -> List[Dict]:
    """
    Expand seed keywords using Amazon autocomplete.
    Returns list of keywords with their demand estimate (from position).

    Key insight : Amazon trie ses suggestions par fréquence de recherche.
    Position 0 = keyword le plus recherché. C'est notre signal de volume GRATUIT.
    """
    from modules.research.keywords import get_keyword_suggestions

    found: Dict[str, Dict] = {}

    for i, seed in enumerate(seeds):
        if status_callback:
            status_callback(f"Autocomplete [{i+1}/{len(seeds)}]: \"{seed}\"...")

        suggestions = get_keyword_suggestions(seed, region=region, limit=11)

        for pos, kw in enumerate(suggestions):
            kw_clean = kw.lower().strip()
            if len(kw_clean.split()) < 2:
                continue
            # Garder le meilleur rang (plus haute demande) pour les doublons
            if kw_clean not in found or found[kw_clean]["autocomplete_position"] > pos:
                found[kw_clean] = {
                    "keyword":              kw_clean,
                    "seed":                 seed,
                    "autocomplete_position": pos,
                    "demand_from_search":   _position_to_demand(pos),
                }
        time.sleep(0.35)

    # Trier par demande estimée
    result = sorted(found.values(), key=lambda x: x["demand_from_search"], reverse=True)
    return result


def score_golden_opportunity(
    keyword_data: Dict,
    competition_score: float,
    demand_score: float,
    avg_reviews: float,
) -> Dict:
    """
    Calcule le score "Golden" d'une opportunité.

    Golden Score = combinaison de :
    - demand_from_search (autocomplete position) → proxy volume de recherche Amazon
    - competition_score (reviews des top produits) → difficulté à ranker
    - demand_score (BSR ou reviews count) → validation que les gens achètent

    Un keyword GOLDEN = beaucoup de gens cherchent + peu de livres compétitifs.
    """
    autocomplete_demand = keyword_data.get("demand_from_search", 50.0)

    # Formule Golden : 40% demande search + 40% compétition + 20% demande achat
    golden = (
        autocomplete_demand * 0.40
        + competition_score  * 0.40
        + demand_score       * 0.20
    )

    # Bonus si reviews TRÈS faibles (< 10) = niche quasi-inexploitée
    if avg_reviews < 10:
        golden = min(golden * 1.15, 100)
    elif avg_reviews < 25:
        golden = min(golden * 1.05, 100)

    tier = (
        "🏆 GOLDEN"   if golden >= 75 else
        "🌟 EXCELLENT" if golden >= 62 else
        "✅ BON"       if golden >= 50 else
        "⚠️ MOYEN"     if golden >= 38 else
        "❌ À ÉVITER"
    )

    return {
        "golden_score":         round(golden, 1),
        "autocomplete_demand":  round(autocomplete_demand, 1),
        "tier_golden":          tier,
        "is_golden":            golden >= 62,
    }
