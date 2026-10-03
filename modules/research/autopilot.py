"""
Autopilot Research Engine — v2
Trois modes de scan combinés :
  1. MICRO-NICHES   — base de données curated hyper-spécifiques
  2. GOLDEN KEYWORDS — fort volume recherche + faible concurrence (via autocomplete)
  3. QUIZ & BIZARRE  — catégories sous-exploitées, niches insolites
"""
import re
import time
import logging
from typing import List, Dict, Optional, Callable

logger = logging.getLogger(__name__)

# Amazon listing metadata that leaks into scraped/autocomplete keywords and must
# be stripped so a niche is a real search phrase, not a book's full catalog title
# (e.g. "diabetic recipes for one and two paperback january 1 2009").
_META_DATE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+\d{1,2}(st|nd|rd|th)?\s*,?\s*\d{4}\b.*$", re.I)
_META_SUFFIX = re.compile(
    r"\b(paperback|hardcover|hardback|kindle edition|kindle|audiobook|audio cd|"
    r"spiral[- ]?bound|board book|mass market( paperback)?|large print edition|"
    r"illustrated edition|free (kindle|book|download)|on kindle|amazon)\b.*$", re.I)
_META_YEAR = re.compile(r"\b(1[89]|20)\d{2}\b")


def _clean_niche_keyword(kw: str) -> str:
    """Strip Amazon catalog metadata (format words, publication dates, years) that
    contaminate scraped keywords, leaving a clean searchable niche phrase."""
    s = (kw or "").strip()
    s = _META_DATE.sub("", s)
    s = _META_SUFFIX.sub("", s)
    s = _META_YEAR.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" -–—,·|")
    return s

LOW_COMPETITION_MAX_REVIEWS = 50
MIN_DEMAND_SCORE            = 25

# ── Critères "La Crème" (ultra-stricts) ──────────────────────────────────────
CREME_MAX_REVIEWS    = 200  # Les avis seuls ne disqualifient plus : ce qui compte
                            # = un BON BSR (demande réelle) + une concurrence FAIBLE
                            # RELATIVE à la demande (jugée par le score/BSR en Phase 2).
                            # On garde un plafond large pour écarter le franchement saturé.
CREME_MIN_SCORE      = 60   # Score global minimum
CREME_MIN_PRODUCTS   = 3    # Marché existe (au moins 3 livres trouvés)
CREME_MIN_QUALITY    = 40   # 40% des produits ont des données valides

# ── Seeds hand-picked pour La Crème, organisées par CATÉGORIE ────────────────
# L'UI permet d'inclure/exclure chaque catégorie. Ajoute librement de nouveaux
# seeds dans la bonne section pour faire grandir le pool.
CREME_SEEDS_BY_CATEGORY: Dict[str, List[str]] = {
    "📔 Logs spécialisés (santé)": [
        "cpap therapy sleep log",
        "insulin dosage daily tracker",
        "perimenopause symptom tracker",
        "continuous glucose log book",
        "autoimmune flare tracker journal",
        "ivf injection log book",
        "migraine trigger tracker journal",
        "fibromyalgia symptom log",
        "lupus flare tracker journal",
        "endometriosis pain tracker",
        "ibs food trigger log",
        "blood pressure daily log seniors",
    ],
    "💼 Professions ultra-niche": [
        "tattoo artist appointment book",
        "nail technician client record",
        "etsy seller daily planner",
        "virtual assistant client planner",
        "dog trainer session log",
        "falconry training log book",
        "beekeeper hive inspection log",
        "doula client visit log",
        "pet sitter daily report log",
        "house cleaner client log",
        "freelance writer project planner",
        "podcast episode planner log",
    ],
    "🎨 Hobbies & loisirs niche": [
        "sourdough starter discard log",
        "aquarium fish keeper log",
        "vinyl record collection log",
        "funko pop collection tracker",
        "trading card binder log",
        "candle making recipe log",
        "soap making recipe notebook",
        "mushroom foraging field log",
        "bird watching life list journal",
        "fountain pen ink swatch journal",
        "cigar tasting log book",
        "whisky tasting journal log",
        "tea tasting log book",
        "perfume scent journal log",
    ],
    "🧩 Quiz & Trivia books": [
        "schitts creek trivia book",
        "the office trivia quiz book",
        "90s hip hop trivia book",
        "wwe wrestling trivia book",
        "date night trivia book couples",
        "road trip trivia kids family",
        "harry potter trivia quiz adults",
        "marvel mcu trivia quiz book",
        "stranger things trivia book",
        "ted lasso trivia quiz book",
        "f1 formula 1 trivia book",
        "nba basketball trivia book adults",
        "80s movie trivia book adults",
        "true crime trivia quiz book",
        "bridgerton trivia quiz book",
        "yellowstone tv show trivia book",
        "outlander trivia book fans",
        "succession hbo trivia book",
        "premier league football trivia",
        "disney princess trivia book kids",
        "minecraft trivia book kids",
        "pokemon trivia quiz book kids",
        "thanksgiving trivia book family",
        "christmas trivia quiz book family",
    ],
    "🖍️ Coloring books adultes (tendance)": [
        "mushroom coloring book adults",
        "frog coloring book adults",
        "axolotl coloring book adults",
        "cottagecore coloring book adults",
        "dark academia coloring book",
        "celestial moon coloring book",
        "witchy aesthetic coloring book",
        "underwater creatures coloring book",
        "crystals gemstones coloring book",
        "art nouveau coloring book adults",
        "skeleton flowers coloring book",
        "haunted house coloring book adults",
        "gothic art coloring book adults",
        "macabre anatomy coloring book",
        "japanese folklore coloring book adults",
        "tarot card coloring book adults",
        "zodiac sign coloring book adults",
        "fantasy castles coloring book adults",
        "vintage botanical coloring book",
        "stained glass coloring book adults",
        "vintage cars coloring book adults",
        "succulents cacti coloring book adults",
        "deep sea creatures coloring book",
        "bioluminescent ocean coloring book",
    ],
    "🧒 Coloring books enfants & ados": [
        "dinosaur coloring book boys ages 4-8",
        "unicorn coloring book girls ages 4-8",
        "construction trucks coloring book toddlers",
        "space rockets coloring book kids",
        "mermaid coloring book girls",
        "dragon coloring book kids",
        "farm animals coloring book toddlers",
        "ocean animals coloring book preschool",
        "robot coloring book kids",
        "fairy garden coloring book girls",
        "monster trucks coloring book boys",
        "princess castle coloring book girls",
        "pokemon style coloring book kids",
        "anime chibi coloring book teens",
        "kawaii food coloring book teens",
        "cute animals coloring book toddlers",
    ],
    "🧠 Puzzles & jeux de réflexion (gros volumes annuels)": [
        # Mazes — top kids + seniors large print
        "mazes for kids ages 4-8",
        "mazes for kids ages 6-8",
        "large print mazes for seniors",
        "mazes for adults travel size",
        "maze book for dementia patients",
        "100 mazes for kids workbook",
        # Sudoku — saturé en général, micro-niches en or
        "sudoku for seniors large print",
        "sudoku for kids 4x4 9x9",
        "easy sudoku puzzles for beginners",
        "extreme sudoku puzzles for experts",
        "sudoku puzzle book for adults extra large print",
        # Word search — thématiques quasi infinies
        "word search large print for seniors",
        "christmas word search book adults",
        "bible word search large print",
        "true crime word search puzzle book",
        "90s movies word search book",
        "animal word search book for kids",
        "halloween word search book adults",
        # Cryptograms — sous-exploité
        "cryptogram puzzle book for adults",
        "large print cryptograms for seniors",
        "bible cryptogram puzzles",
        "inspirational quote cryptograms",
        # Logic puzzles (trend 2026)
        "logic grid puzzles for adults",
        "einstein logic puzzles book",
        "lateral thinking puzzles adults",
        # Nonograms / Picross
        "nonogram puzzle book for adults",
        "picross logic puzzle book",
        # Kakuro / KenKen — niches fidèles
        "kakuro puzzle book for adults",
        "kenken math puzzles book",
        # Dot-to-dot
        "extreme dot to dot for adults",
        "dot to dot for seniors large print",
        # Combo / activity
        "brain games for seniors all in one",
        "ultimate brain health puzzle book",
        "activity book for adults variety puzzles",
    ],
    "🤖 IA & workflows tech (2026, quasi-vierge)": [
        "ai prompt tracker journal",
        "chatgpt prompt log notebook",
        "ai art prompt journal midjourney",
        "midjourney prompt log book",
        "stable diffusion prompt journal",
        "ai content creator planner",
        "ai workflow project log book",
        "ai agent build log notebook",
        "llm experiment tracking journal",
        "ai marketing campaign planner",
        "ai side hustle daily planner",
        "ai automation project tracker",
        "no code builder project journal",
        "ai consultant client log book",
        "prompt engineering practice workbook",
        "ai startup founder daily journal",
        "ai influencer content planner",
        "vibe coding daily log",
        "ai newsletter writer planner",
        "ai research paper reading log",
    ],
    "✨ Bizarre / tendance (marchés quasi-vierges)": [
        "goblincore foraging field notes",
        "ghost hunting evidence log",
        "villain era journal",
        "dark academia aesthetic journal",
        "cryptid research field notes",
        "paranormal investigation log",
        "tarot reading journal tracker",
        "moon ritual witch journal",
        "manifestation journal 369 method",
        "shadow work journal beginners",
        "dream journal lucid dreaming",
        "ufo sighting log book",
    ],

    # ════════════ HIGH-CONTENT (vrai contenu rédigé, pas templates) ════════════
    # Seeds ULTRA-spécifiques longue-traîne → on chasse les poches non-saturées
    # à forte demande. Niches "sûres" (cuisine simple, guides débutants) où
    # Claude est fiable + vérification web possible.
    "🍳 Recettes & cuisine (high-content)": [
        "air fryer recipes for two",
        "air fryer recipes for seniors",
        "high protein air fryer cookbook",
        "dump dinner slow cooker recipes",
        "5 ingredient mediterranean diet recipes",
        "diabetic air fryer cookbook for beginners",
        "anti inflammatory smoothie recipes",
        "high protein smoothie recipes weight loss",
        "one pot pasta recipes for beginners",
        "no bake dessert recipes easy",
        "meal prep recipes for busy moms",
        "gluten free air fryer recipes",
        "bariatric recipes after surgery",
        "toddler meal recipes picky eaters",
        "cozy fall soup recipes",
        "mug cake recipes microwave",
    ],
    "📖 Guides pratiques how-to (high-content)": [
        "container gardening for small spaces",
        "raised bed gardening for beginners",
        "worm composting for beginners",
        "backyard chicken keeping for beginners",
        "beekeeping for beginners step by step",
        "soy candle making for beginners",
        "beginner crochet patterns step by step",
        "macrame for beginners patterns",
        "sourdough starter guide for beginners",
        "indoor herb garden for beginners",
        "hydroponics for beginners at home",
        "foraging wild edibles for beginners",
        "beginner watercolor techniques guide",
        "resin art for beginners guide",
    ],
    "📚 Éducatif & faits (high-content)": [
        "fun facts for curious kids",
        "weird animal facts for kids",
        "space facts for kids age 8 12",
        "why questions answered for kids",
        "amazing human body facts for kids",
        "ocean facts for kids",
        "world geography facts for kids",
        "bug facts for curious kids",
        "dinosaur facts for kids",
        "history facts for curious minds",
    ],
    "🧘 Self-help & défis (high-content)": [
        "30 day self love challenge workbook",
        "morning routine guide for productivity",
        "beginner meditation guide 10 minutes",
        "dopamine detox guide beginners",
        "digital declutter 30 day plan",
        "habit building guide for beginners",
        "shadow work prompts and guide",
        "5 minute journaling guide for anxiety",
        "burnout recovery guide for beginners",
        "minimalism guide for beginners",
    ],
}

# Categories that produce HIGH-CONTENT books (real written content, not blank
# templates / puzzles). Used to flag results + route to the high-content
# creation pipeline later (Phase 2).
HIGH_CONTENT_CATEGORIES = {
    "🍳 Recettes & cuisine (high-content)",
    "📖 Guides pratiques how-to (high-content)",
    "📚 Éducatif & faits (high-content)",
    "🧘 Self-help & défis (high-content)",
}

# Flat list for backward compatibility (used by legacy code paths)
CREME_SEEDS: List[str] = [s for seeds in CREME_SEEDS_BY_CATEGORY.values() for s in seeds]
CREME_CATEGORY_NAMES: List[str] = list(CREME_SEEDS_BY_CATEGORY.keys())

# Set of all seeds known to be high-content (for fast membership checks)
_HIGH_CONTENT_SEEDS = {
    s.lower() for cat, seeds in CREME_SEEDS_BY_CATEGORY.items()
    if cat in HIGH_CONTENT_CATEGORIES for s in seeds
}
# Keyword markers that signal a high-content book regardless of source seed.
# ÉLARGI : ne plus se limiter à la cuisine — attraper aussi les guides/how-to
# de TOUS les domaines (jardinage, dressage, artisanat, DIY, hobbies, fitness…).
# Un livre "à écrire" = recettes OU guide/tuto/technique, quel que soit le sujet.
_HIGH_CONTENT_MARKERS = (
    # ── Cuisine ──
    "recipe", "recipes", "cookbook", "cooking", "meals", "smoothie", "soup",
    # ── Guides / how-to (tous domaines) ──
    "guide", "how to", "how-to", "for beginners", "step by step", "handbook",
    "manual", "techniques", "tips and tricks", "basics", "lessons", "learn to",
    # ── Faire / fabriquer / cultiver (domaines non-cuisine) ──
    "training", "gardening", "growing", "diy", "making", "build", "building",
    "construction", "projects", "patterns", "care guide", "grooming",
    # ── Méthodes / protocoles / régimes (guides rédigés) ──
    "protocol", "protocols", "regimen", "methods", "routines", "therapy protocol",
    # ── Éducatif / self-help / fitness ──
    "facts for", "facts about", "challenge workbook", "30 day", "routine",
    "workout", "exercises", "meditation",
    # ── Religion & spiritualité (contenu rédigé) ──
    "bible", "prayer", "devotional", "quran", "islam", "buddhism", "scripture",
    "christian", "catholic", "faith", "stoicism", "gratitude practice",
    # ── Apprentissage / langues / compétences ──
    "learn ", "study skills", "study guide", "public speaking", "memory improvement",
    "vocabulary", "grammar", "calligraphy",
    # ── Anecdotes & histoires vraies (adulte) ──
    "anecdotes", "true stories", "short stories", "fascinating", "mind blowing",
    "strange but true", "unbelievable", "interesting facts",
)
# Words that, despite a marker, are still LOW-content templates (exclude).
_LOW_CONTENT_OVERRIDE = ("log", "logbook", "tracker", "journal", "planner",
                         "notebook", "diary", "coloring", "colouring")


def is_high_content_niche(niche: str) -> bool:
    """
    True if a niche/seed should be built as a HIGH-CONTENT book (real written
    content: recipes, guides, facts) rather than a low-content template.
    Used to flag scan results and route to the high-content creation pipeline.
    """
    n = (niche or "").lower().strip()
    if not n:
        return False
    if n in _HIGH_CONTENT_SEEDS:
        return True
    has_marker = any(m in n for m in _HIGH_CONTENT_MARKERS)
    if not has_marker:
        return False
    # "recipe journal" / "recipe tracker" = blank template, NOT high-content
    if any(w in n.split() for w in _LOW_CONTENT_OVERRIDE):
        # allow "guide"/"recipes"/"cookbook" to win over a trailing template word
        if not any(strong in n for strong in
                   ("recipes", "cookbook", "guide", "how to", "how-to",
                    "facts for", "facts about", "step by step")):
            return False
    return True


# ── Hyper-niche expander ─────────────────────────────────────────────────────
# Décline chaque seed en variantes hyper-spécifiques par audience.
# Pro-tip 2026 : "anxiety journal for teens" >> "anxiety journal" (générique).

HYPER_NICHE_AUDIENCES: List[str] = [
    "for beginners",
    "for teens",
    "for seniors large print",
    "for women",
    "for men",
    "for professionals",
]


def expand_hyper_niche(seed: str, max_variants: int = 4) -> List[str]:
    """
    Décline un seed en variantes "{seed} {audience}".
    Évite la duplication si le seed contient déjà une audience.
    """
    s_low = seed.lower()
    skip_words = ("for ", "kids", "adults", "teens", "seniors", "women", "men",
                  "boys", "girls", "toddlers", "couples", "family")
    if any(w in s_low for w in skip_words):
        return [seed]   # déjà ciblé, ne pas re-décliner

    out = [seed]
    for aud in HYPER_NICHE_AUDIENCES[:max_variants]:
        out.append(f"{seed} {aud}")
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  BASE DE NICHES CURATED
# ══════════════════════════════════════════════════════════════════════════════

MICRO_NICHES = {
    "journals_profession": [
        "nurse self care journal", "social worker burnout journal",
        "teacher gratitude journal", "paramedic mental health journal",
        "firefighter daily reflection journal", "police officer wellness journal",
        "veterinarian journal notebook", "hair stylist client notes journal",
        "dental hygienist daily journal", "pharmacist daily log journal",
        "physical therapist patient notes", "speech therapist session log",
    ],
    "journals_condition": [
        "pcos symptoms tracker journal", "perimenopause journal for women",
        "ivf journey journal tracker", "first year sobriety journal",
        "chronic pain daily tracker journal", "lupus symptoms tracker journal",
        "fibromyalgia daily log journal", "eating disorder recovery journal",
        "intrusive thoughts journal cbt", "agoraphobia exposure therapy journal",
        "cpap therapy sleep log", "migraine trigger tracker journal",
    ],
    "journals_audience": [
        "single mom daily journal", "military spouse deployment journal",
        "divorced dad parenting journal", "foster parent daily journal",
        "caregiver burnout journal", "bereaved parent grief journal",
        "journal for black women healing", "teen boy mental health journal",
        "christian woman prayer journal", "muslim woman reflection journal",
    ],
    "planners_profession": [
        "homeschool mom weekly planner", "etsy seller shop planner",
        "instagram content creator planner", "real estate agent planner",
        "dog trainer appointment planner", "yoga instructor class planner",
        "personal trainer client planner", "tattoo artist appointment planner",
        "nail technician client planner", "freelance graphic designer planner",
    ],
    "planners_specific": [
        "adhd daily planner with time blocks", "adhd meal planner for adults",
        "neurodivergent daily routine planner", "menstrual cycle planner tracker",
        "fertility tracking planner", "postpartum recovery planner",
        "grief daily planner", "sober living daily planner",
        "chronic illness daily planner",
    ],
    "coloring_trending": [
        "axolotl coloring book adults", "mushroom coloring book adults",
        "frog coloring book adults", "cottagecore coloring book",
        "dark academia coloring book", "horror coloring book adults",
        "skeleton flowers coloring book", "crystals gemstones coloring book",
        "art nouveau coloring book adults", "celestial moon coloring book",
        "witchy aesthetic coloring book", "underwater creatures coloring book",
    ],
    "coloring_audience": [
        "coloring book for nurses", "coloring book for teachers",
        "coloring book for cancer patients", "coloring book for dementia large print",
        "christian coloring book for women", "cat mom coloring book",
        "dog lover coloring book adults", "horse lover coloring book adults",
    ],
    "logs_hobby": [
        "sourdough starter log book", "home brew beer recipe log",
        "fermentation recipe notebook", "mushroom foraging journal log",
        "beekeeper hive inspection log", "aquarium fish keeper log book",
        "terrarium plant care log", "ham radio operator log book",
        "rock climbing training log", "bouldering training journal",
        "vinyl record collection log", "sneaker collection log book",
        "funko pop collection log", "trading card collection log",
    ],
    "logs_health": [
        "continuous glucose monitor log", "insulin dosage tracker log",
        "chemotherapy side effects log", "blood pressure weekly log",
        "autoimmune flare up tracker", "food sensitivity elimination log",
        "supplement tracking log book", "intermittent fasting log book",
    ],
    "ebooks_micro": [
        "anxious attachment style guide", "people pleasing recovery guide",
        "highly sensitive person survival guide", "adult child alcoholic recovery",
        "complex ptsd self help guide", "narcissistic mother recovery",
        "financial recovery after divorce", "money mindset for single moms",
        "gut health hashimotos diet", "anti inflammatory diet lupus",
    ],
}

# ── QUIZ & TRIVIA (catégorie très rentable, souvent ignorée) ──────────────────
QUIZ_NICHES = [
    "trivia book for seniors large print",
    "pub quiz book for adults",
    "bible trivia book for teens",
    "sports trivia book for men",
    "movie trivia book for adults",
    "music trivia book 70s 80s 90s",
    "history trivia book for kids",
    "science trivia book for kids",
    "Harry Potter trivia quiz book",
    "Disney trivia book for kids",
    "Friends TV show trivia book",
    "The Office trivia quiz book",
    "football trivia book for fans",
    "basketball trivia book nba",
    "christmas trivia book adults",
    "road trip trivia book family",
    "date night trivia book couples",
    "black history trivia book",
    "womens history trivia book",
    "1000 trivia questions and answers",
    "weird facts book for adults",
    "amazing facts book for curious kids",
    "random fun facts book",
    "would you rather book for adults",
    "would you rather book for kids",
    "never have i ever book adults",
    "conversation starter book couples",
    "this or that book for teens",
    "icebreaker questions book work",
    "truth or dare book adults",
    "yes or no question book",
    "fill in the blank book funny",
    "mad libs style book adults",
]

# ── NICHES BIZARRES & INSOLITES (ultra low competition) ──────────────────────
BIZARRE_NICHES = [
    "dark humor daily planner",
    "sarcastic notebook for adults",
    "sarcastic daily planner coworker",
    "conspiracy theory notebook",
    "paranormal investigation log book",
    "ghost hunting evidence journal",
    "cryptid sighting log book",
    "bigfoot tracker notebook",
    "ufo sighting journal log",
    "true crime trivia book",
    "horror movie trivia book adults",
    "haunted locations coloring book",
    "gothic art coloring book adults",
    "macabre anatomy coloring book",
    "tarot journal for beginners",
    "moon ritual journal witch",
    "witch grimoire notebook blank",
    "spell book journal pages",
    "astrology birth chart journal",
    "crystal healing log book",
    "chakra meditation journal",
    "doomsday prepper supply checklist",
    "survival preparedness log book",
    "zombie apocalypse survival log",
    "dark academia aesthetic journal",
    "villain era daily journal",
    "main character energy journal",
    "goblincore nature foraging log",
    "weirdcore art journal sketchbook",
    "cottagecore nature journal",
    "introvert social battery tracker",
    "antisocial butterfly notebook",
    "chaos gremlin planner",
    "chaotic neutral daily planner",
    "morally grey character journal",
    "existential dread daily log",
    "nihilist gratitude journal funny",
    "lazy girl wellness journal",
    "unhinged daily planner funny",
    "hot mess mom planner",
    "feral goblin notebook",
    "cryptid enthusiast field notes",
    "sea creature anatomy coloring book",
    "deep sea horror coloring book",
    "fungi mushroom anatomy notebook",
    "insect entomology coloring book",
    "bone anatomy artist reference",
]

CATEGORIES = {
    "🗒️ Journals & Planners spécifiques":   ["journals_profession","journals_condition","journals_audience","planners_profession","planners_specific"],
    "🎨 Coloring books tendance 2024-2025": ["coloring_trending","coloring_audience"],
    "📓 Log books & notebooks spécialisés": ["logs_hobby","logs_health"],
    "📚 Ebooks & workbooks micro-niches":   ["ebooks_micro"],
    "🧩 Quiz & Trivia books":               ["quiz"],
    "😈 Niches bizarres & insolites":       ["bizarre"],
    "🌟 Tout scanner (max opportunités)":   ["all"],
}


def get_seeds(category: str, max_count: int = 20) -> List[str]:
    keys = CATEGORIES.get(category, ["all"])

    if "all" in keys:
        combined = (
            [kw for lst in MICRO_NICHES.values() for kw in lst]
            + QUIZ_NICHES
            + BIZARRE_NICHES
        )
    elif "quiz" in keys:
        combined = QUIZ_NICHES
    elif "bizarre" in keys:
        combined = BIZARRE_NICHES
    else:
        combined = [kw for key in keys for kw in MICRO_NICHES.get(key, [])]

    seen, result = set(), []
    for kw in combined:
        if kw not in seen:
            seen.add(kw)
            result.append(kw)
    return result[:max_count]


# ══════════════════════════════════════════════════════════════════════════════
#  CLAUDE AI — génération de niches contextuelles
# ══════════════════════════════════════════════════════════════════════════════

# ── HIGH-CONTENT DISCOVERY ENGINE (vast field, not a fixed list) ─────────────
# Broad roots spanning the MAJOR high-content KDP markets. Each root is expanded
# via Amazon autocomplete (real demand) → hundreds of actual searched sub-niches.
_HIGH_CONTENT_ROOTS = [
    # Cooking (biggest high-content market)
    "air fryer recipes", "slow cooker recipes", "instant pot recipes",
    "keto recipes", "vegan recipes", "smoothie recipes", "meal prep recipes",
    "budget meals cookbook", "soup recipes", "dessert recipes", "bread recipes",
    "mediterranean diet recipes", "diabetic recipes", "high protein recipes",
    "cooking for one cookbook", "5 ingredient recipes", "dump dinner recipes",
    "cast iron recipes", "blackstone griddle recipes", "ninja foodi recipes",
    # Gardening
    "gardening for beginners", "vegetable gardening", "container gardening",
    "herb garden guide", "raised bed gardening", "hydroponics for beginners",
    # Crafts / DIY
    "crochet patterns", "knitting patterns for beginners", "candle making",
    "soap making recipes", "resin art for beginners", "macrame patterns",
    "polymer clay projects", "woodworking projects for beginners",
    # Health / diet / wellness
    "anti inflammatory diet", "intermittent fasting guide", "gut health diet",
    "low carb diet for beginners", "essential oils guide", "herbal remedies",
    # Fitness
    "home workout for beginners", "yoga for beginners", "stretching exercises",
    "calisthenics for beginners",
    # Pets
    "dog training for beginners", "puppy training guide", "cat care guide",
    "aquarium setup guide",
    # Kids education
    "science experiments for kids", "facts for kids", "learn to draw for kids",
    "activities for kids book",
    # Hobbies
    "fishing for beginners", "chess for beginners", "photography for beginners",
    "watercolor for beginners", "bird watching guide", "drawing for beginners",
    # Money / business
    "budgeting for beginners", "side hustle ideas", "passive income guide",
    "etsy shop for beginners", "real estate investing for beginners",
    # Self-help / productivity
    "morning routine guide", "habit building guide", "meditation for beginners",
    "productivity guide", "minimalism for beginners", "decluttering guide",
    # Home
    "home organization guide", "cleaning routine guide", "interior design basics",
    # Language
    "learn spanish for beginners", "common spanish phrases", "learn french basics",
    # ── CONDITION / DIET-SPECIFIC (the real high-content whitespace) ──
    # Broad cooking terms are saturated (3000+ reviews); condition-specific
    # cookbooks routinely sit under 25 reviews with steady demand.
    "diabetic recipes", "renal diet recipes", "kidney disease recipes",
    "anti inflammatory recipes", "low sodium recipes", "low fodmap recipes",
    "gastroparesis recipes", "celiac gluten free recipes", "ibs friendly recipes",
    "thyroid diet recipes", "pcos diet recipes", "menopause diet recipes",
    "arthritis diet recipes", "gout diet recipes", "acid reflux diet recipes",
    "bariatric surgery recipes", "dysphagia soft food recipes",
    "high calcium recipes osteoporosis", "low cholesterol recipes",
    "cancer patient recipes chemotherapy", "dementia friendly recipes",
    "heart healthy recipes seniors", "recipes for one senior",
    "soft food recipes after surgery", "toddler recipes picky eaters",
    "high protein recipes seniors", "diverticulitis diet recipes",
    # ── NON-COOKING high-content whitespace (option B — diversify beyond food) ──
    # Gardening
    "square foot gardening", "no dig gardening", "vertical gardening small spaces",
    "companion planting guide", "seed starting for beginners", "raised bed vegetable garden",
    "indoor plant care guide", "succulent care for beginners", "orchid care guide",
    # Crafts / DIY / fiber
    "amigurumi crochet patterns", "beginner knitting patterns", "punch needle for beginners",
    "polymer clay earrings guide", "soap making for beginners", "resin coaster guide",
    "macrame plant hanger patterns", "hand lettering practice guide",
    # Pets / animals
    "puppy training schedule", "reactive dog training guide", "cat behavior guide",
    "chicken keeping for beginners", "betta fish care guide", "reptile care for beginners",
    # Hobbies / skills
    "watercolor for absolute beginners", "acrylic painting techniques", "sketching for beginners",
    "chess openings for beginners", "birdwatching field guide", "fishing knots guide",
    "photography composition guide", "sourdough baking for beginners",
    # Fitness / wellness (non-recipe)
    "chair yoga for seniors", "resistance band workouts", "stretching for flexibility",
    "walking plan for weight loss", "breathwork for anxiety", "meditation for beginners",
    # Home / money / productivity
    "decluttering guide adhd", "home organization system", "budgeting for beginners guide",
    "side hustle ideas guide", "etsy shop for beginners", "notion productivity guide",
    # Kids facts / education
    "fun facts for curious kids", "space facts for kids", "animal facts for kids",
    "human body facts for kids", "dinosaur facts for kids", "how things work for kids",
    # ── Religion & spirituality ──
    "bible study for beginners", "bible study guide", "daily prayer guide",
    "christian devotional for women", "bible verses for anxiety", "catholic prayer book",
    "islam for beginners", "quran study guide", "buddhism for beginners",
    "meditation and mindfulness guide", "stoicism for beginners", "gratitude practice guide",
    # ── Learning & education ──
    "learn spanish for beginners", "learn french for beginners", "study skills for students",
    "how to learn faster", "public speaking for beginners", "memory improvement techniques",
    "learn to code for beginners", "excel for beginners guide", "learn chess for beginners",
    "learn calligraphy for beginners", "grammar guide for adults", "vocabulary builder adults",
    # ── Anecdotes & short true stories (adult, captivating) ──
    "amazing history anecdotes", "fascinating science stories", "weird history facts adults",
    "interesting facts for adults", "unbelievable true stories", "little known history stories",
    "mind blowing facts book", "strange but true stories", "inspiring true short stories",
    # ── More under-served how-to domains ──
    "car maintenance for beginners", "home repair for beginners", "personal finance for beginners",
    "stock market investing for beginners", "cryptocurrency for beginners", "coffee brewing guide",
    "wine tasting for beginners", "digital photography for beginners", "car detailing guide",
    "leather crafting for beginners", "electronics for beginners", "3d printing for beginners",
]

# Cooking-domain markers — used to guarantee non-cooking diversity in the scan cap.
_COOKING_MARKERS = (
    "recipe", "recipes", "cookbook", "cooking", "meal", "meals", "diet", "food",
    "air fryer", "instant pot", "slow cooker", "smoothie", "soup", "dessert",
    "baking", "bread", "sourdough", "keto", "vegan", "snack", "dish", "kitchen",
    "eat", "nutrition cookbook", "casserole", "dump dinner",
)


def _is_cooking_niche(niche: str) -> bool:
    n = (niche or "").lower()
    return any(m in n for m in _COOKING_MARKERS)


# Markers that make a niche ULTRA-SPECIFIC = low competition = worth scanning.
# Learned from real data: "air fryer recipes for two" = 3811 avg reviews (dead),
# "osteoporosis recipes high calcium" = 3 avg reviews (gold).
_SPECIFIC_MARKERS = (
    # medical / dietary conditions — the biggest high-content whitespace
    "osteoporosis", "fibromyalgia", "diabetic", "diabetes", "kidney", "renal",
    "lupus", "celiac", "ibs", "crohn", "gastroparesis", "gout", "thyroid",
    "hashimoto", "pcos", "endometriosis", "anemia", "cholesterol", "hypertension",
    "arthritis", "autoimmune", "menopause", "bariatric", "dysphagia", "gerd",
    "acid reflux", "low sodium", "low fodmap", "low potassium", "anti inflammatory",
    "high calcium", "high protein", "high fiber", "low histamine", "allergy",
    "chemotherapy", "post surgery", "dementia", "alzheimer",
    # audiences
    "for seniors", "for beginners", "for teens", "for kids", "for two",
    "for one", "for men", "for women", "for busy", "for college",
    "large print", "picky eaters", "single", "toddler",
    # constraints / equipment specifics
    "no oven", "no bake", "5 ingredient", "3 ingredient", "budget", "small space",
    "apartment", "beginner", "step by step", "one pot", "30 minute", "15 minute",
    "meal prep", "batch cooking", "freezer",
    # ── NON-CUISINE : jardinage / plantes ──
    "raised bed", "container", "indoor", "hydroponic", "balcony", "urban",
    "vertical", "no dig", "greenhouse", "succulent", "orchid", "bonsai",
    # ── NON-CUISINE : artisanat / DIY / crochet-tricot ──
    "amigurumi", "granny square", "chunky", "left handed", "beginner friendly",
    "weekend project", "no sew", "upcycle", "polymer clay", "macrame", "resin",
    # ── NON-CUISINE : animaux ──
    "puppy", "rescue", "senior dog", "reactive", "crate", "potty training",
    "leash", "aquarium", "reptile", "small dog",
    # ── NON-CUISINE : hobbies / fitness / apprentissage ──
    "chair yoga", "low impact", "no equipment", "resistance band", "mobility",
    "watercolor", "acrylic", "hand lettering", "for left handed", "sketching",
)


def _specificity_score(niche: str) -> float:
    """
    Higher = more specific = more likely to be an unsaturated pocket.
    Broad head terms ("air fryer recipes") score low; long-tail with a
    condition/audience/constraint marker scores high.
    """
    n = (niche or "").lower().strip()
    if not n:
        return 0.0
    words = n.split()
    score = min(len(words), 8) * 1.0            # longer = more specific
    for m in _SPECIFIC_MARKERS:
        if m in n:
            score += 6.0                        # strong specificity signal
    if len(words) <= 3:                         # head term penalty
        score -= 5.0
    return score


# Cache de session (une même niche = un même volume, évite les appels répétés).
_SEARCH_VOL_CACHE: Dict[str, float] = {}


def _search_volume_score(niche: str) -> float:
    """
    VRAI proxy de volume de recherche, via la POSITION dans l'autocomplete Amazon.

    Amazon trie ses suggestions par fréquence de recherche : si la niche exacte
    remonte comme complétion de son terme-tête (ex. "gardening" → "container
    gardening for beginners"), c'est que des acheteurs la cherchent réellement →
    score élevé. Si elle ne remonte jamais → demande non prouvée → score bas.

    Remplace l'ancienne constante 55.0 (qui rendait les 25% "volume de recherche"
    totalement inutiles : même valeur pour toutes les niches).
    """
    n = (niche or "").lower().strip()
    if not n:
        return 40.0
    if n in _SEARCH_VOL_CACHE:
        return _SEARCH_VOL_CACHE[n]

    try:
        from modules.research.keywords import get_keyword_suggestions
        from modules.research.keyword_opportunity import _position_to_demand
    except Exception:
        return 55.0  # fallback neutre si l'autocomplete est indisponible

    words = n.split()
    best: Optional[float] = None
    # On sonde le terme-tête (niche sans son dernier mot) : la niche complète
    # doit apparaître parmi ses complétions, et sa position donne la demande.
    prefix = " ".join(words[:-1]) if len(words) >= 2 else n
    try:
        sugg = get_keyword_suggestions(prefix, limit=10) or []
    except Exception:
        sugg = []
    for pos, s in enumerate(sugg):
        sl = (s or "").lower().strip()
        if sl == n or n in sl or (sl in n and len(sl.split()) >= 2):
            best = _position_to_demand(pos)
            break

    if best is None:
        # Pas une complétion du terme-tête → la niche elle-même est-elle un
        # "stem" vivant (renvoie des sous-suggestions) ? Signal faible.
        try:
            own = get_keyword_suggestions(n, limit=10) or []
        except Exception:
            own = []
        best = 42.0 if len(own) >= 3 else 30.0

    _SEARCH_VOL_CACHE[n] = best
    return best


_FALLBACK_DOMAINS = (
    "cooking & recipes", "gardening & homesteading", "crafts & DIY",
    "health diet & fitness", "kids education & facts", "hobbies & skills",
    "money & side hustles", "self-help & productivity",
    "religion & spirituality", "bible study & devotionals",
    "learning & study skills", "language learning",
    "amazing anecdotes & true stories", "fascinating facts for adults",
    "car & home maintenance", "investing & personal finance",
    "music & instruments", "photography & creative skills",
)


def _discover_domains(api_key: str, n: int = 30) -> List[str]:
    """Ask Claude (cheap Haiku) to brainstorm a WIDE list of high-content KDP
    domains/sub-domains → far more breadth than the 8 fixed ones. Falls back to
    the curated list on any error."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""You are an Amazon KDP expert (US market, 15 years).
List {n} DISTINCT high-content book DOMAINS / sub-domains that sell well and can be
written as real content (cookbooks/recipes, how-to guides, fact books) — NOT blank
journals/planners/coloring/puzzles.

Span widely: cooking (incl. appliance- and medical-condition-specific), gardening,
crafts & fiber arts, DIY & home improvement, health/diet/wellness, fitness, pets,
kids education & facts, STEM for kids, hobbies & skills, money/business/investing,
self-help/productivity, home & organizing, languages, outdoors/survival, and more.

Each domain = a short category phrase (2-5 words). Return ONLY the domains, one per
line, no numbering."""
        msg = client.messages.create(
            model="claude-haiku-4-5", max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        doms = []
        for ln in raw.splitlines():
            d = ln.strip().lstrip("-•*#").strip().lower()
            # skip empties, numbered lines, and header-ish lines
            if len(d) > 3 and d[0].isalpha() and "kdp" not in d and "domain" not in d:
                doms.append(d)
        # dedupe, keep order, ensure the curated ones are included as a safety net
        seen, out = set(), []
        for d in list(doms) + list(_FALLBACK_DOMAINS):
            if d and d not in seen:
                seen.add(d); out.append(d)
        return out[:max(n, len(_FALLBACK_DOMAINS))]
    except Exception as e:
        logger.warning(f"domain discovery failed: {e}")
        return list(_FALLBACK_DOMAINS)


def discover_high_content_niches(
    api_key: str = "",
    max_niches: int = 140,
    use_autocomplete: bool = True,
    use_claude: bool = True,
    status_cb=None,
) -> List[str]:
    """
    DISCOVER high-content niches across a VAST field (not just the curated list).
    Combines:
      1. The 50 curated high-content seeds (known-good starting points)
      2. Amazon autocomplete expansion on ~70 broad roots → real searched
         sub-niches (genuine demand signal)
      3. Claude brainstorming across many domains (breadth + creativity)
    All filtered to high-content (is_high_content_niche) + deduped.

    Returns a large list of candidate niches to feed into run_creme() scoring.
    """
    def s(m):
        if status_cb: status_cb(m)

    found: Dict[str, None] = {}  # ordered set
    # 1. Curated seeds
    for seed in _HIGH_CONTENT_SEEDS:
        found[seed] = None

    # 2. Autocomplete expansion (real demand) — TWO levels for more long-tail
    if use_autocomplete:
        try:
            from modules.research.keywords import get_keyword_suggestions
            import time as _t
            s(f"🔎 Découverte : autocomplete niveau 1 sur {len(_HIGH_CONTENT_ROOTS)} domaines...")
            level1: List[str] = []
            for i, root in enumerate(_HIGH_CONTENT_ROOTS):
                try:
                    for sug in get_keyword_suggestions(root, limit=10):
                        kw = (sug or "").strip().lower()
                        if kw and kw not in found and is_high_content_niche(kw):
                            found[kw] = None
                            level1.append(kw)
                except Exception:
                    pass
                _t.sleep(0.12)
                if len(found) >= max_niches * 2:
                    break
            # Level 2: expand a capped sample of the strongest new sub-niches →
            # surfaces long-tail niches the fixed roots never reach.
            if len(found) < max_niches * 2 and level1:
                s(f"🔎 Découverte : autocomplete niveau 2 (long-tail) sur {min(len(level1), 60)} sous-niches...")
                for kw in level1[:60]:
                    try:
                        for sug in get_keyword_suggestions(kw, limit=8):
                            k2 = (sug or "").strip().lower()
                            if k2 and k2 not in found and is_high_content_niche(k2):
                                found[k2] = None
                    except Exception:
                        pass
                    _t.sleep(0.12)
                    if len(found) >= max_niches * 2:
                        break
        except Exception as e:
            logger.warning(f"autocomplete discovery skipped: {e}")

    # 3. Claude brainstorm across MANY dynamically-discovered domains (breadth)
    if use_claude and api_key:
        domains = _discover_domains(api_key, n=30)
        s(f"🧠 Découverte : brainstorm Claude sur {len(domains)} domaines dynamiques...")
        for domain in domains:
            if len(found) >= max_niches * 2:
                break
            try:
                for kw in _claude_niches(api_key, domain, "high_content"):
                    kw = kw.strip().lower()
                    if kw and kw not in found and is_high_content_niche(kw):
                        found[kw] = None
            except Exception:
                continue

    out = list(found.keys())[:max_niches]
    s(f"✅ Découverte high-content : {len(out)} niches candidates trouvées")
    return out


def _claude_niches(api_key: str, category: str, mode: str, theme: str = "") -> List[str]:
    """Claude génère des niches supplémentaires adaptées au mode."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        mode_instructions = {
            "micro": (
                "Generate ULTRA-SPECIFIC micro-niches targeting a very precise audience "
                "(profession, medical condition, niche hobby, life situation).\n"
                "AVOID generic niches. GOOD examples: 'falconry training log', "
                "'mortician wellness planner', 'sepsis survivor healing journal'."
            ),
            "golden": (
                "Generate keywords with HIGH SEARCH VOLUME but FEW existing books.\n"
                "Look for 'popular topic + unexplored angle' combinations.\n"
                "GOOD examples: 'adhd entrepreneur planner', 'menopause weight loss journal', "
                "'gen z anxiety workbook'."
            ),
            "quiz": (
                "Generate very specific QUIZ BOOK and TRIVIA BOOK ideas.\n"
                "Think: cult TV shows, specific sports, historical periods, "
                "religions, cultures, celebrities, films, music by decade.\n"
                "GOOD examples: 'Schitts Creek trivia book', '90s hip hop trivia', "
                "'WWE wrestling trivia book'."
            ),
            "bizarre": (
                "Generate UNUSUAL, bizarre, dark humor, paranormal, internet niche ideas.\n"
                "Think: internet cultures (memes, gaming, anime), dark humor, paranormal, "
                "trending aesthetics (cottagecore, dark academia, goblincore), adult humor.\n"
                "GOOD examples: 'grim reaper coloring book', 'existential crisis planner funny', "
                "'cryptid field guide notebook'."
            ),
            "high_content": (
                "Generate HIGH-CONTENT book ideas — books with REAL written content "
                "(recipes, step-by-step guides, how-to instructions, fact collections), "
                "NOT blank templates / journals / logs / planners / coloring / puzzles.\n"
                "Target SAFE, simple topics an expert AI can write reliably, with a "
                "SPECIFIC under-served angle (audience, constraint, sub-method).\n"
                "GOOD examples: 'air fryer recipes for one person', "
                "'container gardening for apartment renters', "
                "'beginner sourdough no special equipment', "
                "'budget meal prep for college students', "
                "'15 minute yoga for office workers'.\n"
                "Each MUST clearly be a recipe book, cookbook, guide, how-to, or facts book."
            ),
        }

        instruction = mode_instructions.get(mode, mode_instructions["micro"])

        prompt = f"""You are an Amazon KDP expert with 15 years of experience targeting the US market.
{instruction}

Category: {category}
{f"Focus: {theme}" if theme else ""}

RULES:
- ALL keywords MUST be in ENGLISH (US market)
- 3-6 words per keyword (very specific)
- Low competition likely (few existing Amazon books on this topic)
- Return ONLY the keywords, one per line, nothing else."""

        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        return [
            ln.strip().lower()
            for ln in raw.splitlines()
            if len(ln.strip()) > 5 and not ln.strip()[0].isdigit()
        ]
    except Exception as e:
        logger.warning(f"Claude niche gen error: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
#  GOLDEN KEYWORD — expansion autocomplete
# ══════════════════════════════════════════════════════════════════════════════

GOLDEN_BROAD_SEEDS = [
    "journal for", "planner for", "notebook for", "log book for",
    "workbook for", "activity book for", "coloring book for",
    "trivia book for", "quiz book for", "tracker for",
    "guide for", "diary for", "record book for",
]

def _expand_golden_seeds(
    num: int,
    region: str = "US",
    status_callback: Optional[Callable] = None,
) -> List[Dict]:
    """
    Utilise l'autocomplete Amazon pour trouver des keywords à forte demande.
    Retourne les keywords triés par position (0 = plus recherché).
    """
    from modules.research.keywords import get_keyword_suggestions
    from modules.research.keyword_opportunity import _position_to_demand

    found: Dict[str, Dict] = {}

    seeds_to_use = GOLDEN_BROAD_SEEDS[:min(num // 2 + 3, len(GOLDEN_BROAD_SEEDS))]

    for i, seed in enumerate(seeds_to_use):
        if status_callback:
            status_callback(f"🔎 Autocomplete [{i+1}/{len(seeds_to_use)}] : \"{seed}\"...")

        suggestions = get_keyword_suggestions(seed, region=region, limit=11)
        for pos, kw in enumerate(suggestions):
            kw_c = kw.lower().strip()
            if len(kw_c.split()) < 2:
                continue
            if kw_c not in found or found[kw_c]["autocomplete_position"] > pos:
                found[kw_c] = {
                    "keyword":               kw_c,
                    "seed":                  seed,
                    "autocomplete_position": pos,
                    "demand_from_search":    _position_to_demand(pos),
                    "source":                "golden_autocomplete",
                }
        time.sleep(0.3)

    ranked = sorted(found.values(), key=lambda x: x["demand_from_search"], reverse=True)
    return ranked[:num]


# ══════════════════════════════════════════════════════════════════════════════
#  PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def run_autopilot(
    category: str,
    num_niches: int = 12,
    mode: str = "micro",                   # "micro" | "golden" | "quiz" | "bizarre" | "all"
    use_ai_expansion: bool = True,
    custom_theme: str = "",
    api_key: str = "",
    max_avg_reviews: int = LOW_COMPETITION_MAX_REVIEWS,
    region: str = "US",
    progress_callback: Optional[Callable[[float], None]] = None,
    status_callback:   Optional[Callable[[str],   None]] = None,
    result_callback:   Optional[Callable[[Dict],  None]] = None,
) -> Dict:
    """
    Pipeline complet :
    1. Génère une liste de keywords (selon le mode)
    2. Scanne Amazon pour chacun
    3. Filtre : ne garde QUE les niches < max_avg_reviews reviews
    4. Retourne : opportunités / éliminées / échecs
    """
    from modules.research.scraper import AmazonScraper
    from modules.research.keywords import get_keyword_suggestions
    from modules.research.scorer import calculate_opportunity_score
    from modules.research.keyword_opportunity import score_golden_opportunity

    def prog(v):
        if progress_callback: progress_callback(v)
    def status(msg):
        if status_callback: status_callback(msg)

    # ── 1. Construire la liste de keywords ────────────────────────────────────
    status("🧠 Génération de la liste de keywords...")
    prog(3)

    keyword_items: List[Dict] = []   # chaque item = {keyword, source, demand_from_search?, ...}

    if mode == "golden":
        status("🔑 Mode GOLDEN — expansion via autocomplete Amazon...")
        golden_kws = _expand_golden_seeds(num_niches, region=region, status_callback=status)
        keyword_items = golden_kws
        seeds = [k["keyword"] for k in golden_kws]

    elif mode == "quiz":
        status("🧩 Mode QUIZ & TRIVIA — chargement des niches quiz...")
        seeds = QUIZ_NICHES[:num_niches]
        keyword_items = [{"keyword": s, "source": "quiz_db", "demand_from_search": 50} for s in seeds]

    elif mode == "bizarre":
        status("😈 Mode BIZARRE — chargement des niches insolites...")
        seeds = BIZARRE_NICHES[:num_niches]
        keyword_items = [{"keyword": s, "source": "bizarre_db", "demand_from_search": 50} for s in seeds]

    else:  # micro or all
        seeds = get_seeds(category, max_count=num_niches)
        keyword_items = [{"keyword": s, "source": "micro_db", "demand_from_search": 50} for s in seeds]

    # Enrichissement Claude AI
    if use_ai_expansion and api_key and len(seeds) < num_niches + 5:
        status("✨ Claude AI génère des niches supplémentaires...")
        ai_extras = _claude_niches(api_key, category, mode, custom_theme)
        existing = set(k["keyword"] for k in keyword_items)
        for kw in ai_extras:
            if kw not in existing:
                keyword_items.append({"keyword": kw, "source": "claude_ai", "demand_from_search": 55})
                existing.add(kw)
                if len(keyword_items) >= num_niches + 5:
                    break
        status(f"✅ {len(ai_extras)} niches Claude AI ajoutées")

    if not keyword_items:
        status("❌ Aucun keyword généré.")
        return {"opportunities": [], "skipped": [], "failed": [], "all_results": []}

    # Limiter au nombre demandé
    keyword_items = keyword_items[:num_niches]
    status(f"📋 {len(keyword_items)} niches en file...")
    prog(10)

    # ── 2. Scanner chaque niche ───────────────────────────────────────────────
    opportunities, skipped, failed, all_results = [], [], [], []
    step = 80.0 / max(len(keyword_items), 1)

    try:
        with AmazonScraper() as scraper:
            for i, item in enumerate(keyword_items):
                keyword = item["keyword"]
                demand_from_search = item.get("demand_from_search", 50)

                status(f"🔍 [{i+1}/{len(keyword_items)}] \"{keyword}\"...")

                try:
                    products = scraper.search_books(keyword=keyword, max_results=15)

                    if not products:
                        status(f"⚠️ \"{keyword}\" — aucun résultat")
                        failed.append({"keyword": keyword, "reason": "no_results"})
                        prog(10 + (i+1)*step)
                        time.sleep(1.0)
                        continue

                    scores  = calculate_opportunity_score(products)
                    kw_sugg = get_keyword_suggestions(keyword, limit=5)
                    avg_r   = scores["avg_reviews"]

                    # Score golden (combine autocomplete demand + concurrence réelle)
                    golden_data = score_golden_opportunity(
                        keyword_data       = item,
                        competition_score  = scores["competition_score"],
                        demand_score       = scores["demand_score"],
                        avg_reviews        = avg_r,
                    )

                    # Qualité des données scraping
                    non_zero   = sum(1 for p in products if p.get("reviews", 0) > 0)
                    data_qual  = round(non_zero / len(products) * 100)

                    niche = {
                        "rank":               0,
                        "keyword":            keyword,
                        "source":             item.get("source", "db"),
                        "mode":               mode,

                        # Scores standard
                        "overall":            scores["overall"],
                        "tier":               scores["tier"],
                        "tier_emoji":         scores["tier_emoji"],
                        "tier_label":         scores["tier_label"],
                        "competition_score":  scores["competition_score"],
                        "demand_score":       scores["demand_score"],
                        "avg_reviews":        avg_r,
                        "avg_price":          scores["avg_price"],
                        "avg_rating":         scores["avg_rating"],
                        "recommendation":     scores["recommendation"],

                        # Scores golden
                        "golden_score":       golden_data["golden_score"],
                        "tier_golden":        golden_data["tier_golden"],
                        "is_golden":          golden_data["is_golden"],
                        "autocomplete_demand": golden_data["autocomplete_demand"],

                        # Meta
                        "products_found":     len(products),
                        "related_keywords":   kw_sugg,
                        "data_quality":       data_qual,
                        "products":           products,
                        "scores":             scores,
                    }

                    all_results.append(niche)

                    # ── Filtre concurrence ─────────────────────────────────
                    if avg_r <= max_avg_reviews and scores["demand_score"] >= MIN_DEMAND_SCORE:
                        status(
                            f"✅ OPPORTUNITÉ : \"{keyword}\" | "
                            f"Score {scores['overall']}/100 | "
                            f"Golden {golden_data['golden_score']}/100 {golden_data['tier_golden']} | "
                            f"{int(avg_r)} reviews moy."
                        )
                        opportunities.append(niche)
                        if result_callback:
                            result_callback(niche)
                    else:
                        reason = (
                            f"trop compétitif ({int(avg_r)} reviews)"
                            if avg_r > max_avg_reviews
                            else "demande insuffisante"
                        )
                        status(f"⏭️  Ignoré \"{keyword}\" — {reason}")
                        skipped.append({**niche, "skip_reason": reason})

                except Exception as e:
                    logger.warning(f"Error '{keyword}': {e}")
                    status(f"⚠️ Erreur \"{keyword}\"")
                    failed.append({"keyword": keyword, "reason": str(e)[:80]})

                prog(10 + (i+1)*step)
                time.sleep(1.2)

    except Exception as e:
        status(f"⚠️ Erreur navigateur : {e}")
        logger.error(f"Autopilot error: {e}")

    # ── 3. Tri final ──────────────────────────────────────────────────────────
    # Trier par golden_score si mode golden, sinon par overall
    sort_key = "golden_score" if mode == "golden" else "overall"
    opportunities.sort(key=lambda x: x[sort_key], reverse=True)
    all_results.sort(key=lambda x: x[sort_key], reverse=True)

    for i, r in enumerate(opportunities): r["rank"] = i + 1
    for i, r in enumerate(all_results):   r["all_rank"] = i + 1

    prog(100)
    n = len(opportunities)
    best = opportunities[0]["keyword"] if opportunities else "—"

    if n:
        status(f"🎉 Terminé ! {n} opportunité(s) sur {len(keyword_items)} analysées. Meilleure : \"{best}\"")
    else:
        status(
            f"😔 0 opportunité avec ≤{max_avg_reviews} reviews. "
            f"{len(skipped)} trop compétitives. "
            "Essaie d'augmenter le seuil ou change de mode/catégorie."
        )

    return {
        "opportunities": opportunities,
        "skipped":       skipped,
        "failed":        failed,
        "all_results":   all_results,
        "mode":          mode,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MODE "LA CRÈME" — One-Click, critères ultra-stricts, DEUX PHASES
# ══════════════════════════════════════════════════════════════════════════════

def run_creme(
    api_key: str = "",
    use_ai: bool = True,
    extra_theme: str = "",
    progress_callback: Optional[Callable[[float], None]] = None,
    status_callback:   Optional[Callable[[str],   None]] = None,
    result_callback:   Optional[Callable[[Dict],  None]] = None,
    max_reviews:       int = CREME_MAX_REVIEWS,
    min_score:         int = CREME_MIN_SCORE,
    categories:        Optional[List[str]] = None,
    hyper_niche:       bool = False,
    hyper_variants:    int = 4,
    discover_high_content: bool = False,
    discover_max:      int = 140,
    high_content_only: bool = False,
    low_content_only:  bool = False,
    exclude_keywords:  Optional[set] = None,
    max_seeds:         int = 120,
) -> Dict:
    """
    Scan "La Crème" — one-click, scoring expert 5 critères, DEUX PHASES.

    `discover_high_content=True` runs the VAST high-content discovery engine
    (autocomplete across ~75 domains + Claude brainstorm) and scans those niches
    too — finds winning recipe/guide/facts niches far beyond the fixed seeds.

    Tunable parameters:
      - max_reviews : seuil Phase 1 (avg reviews max pour passer en Phase 2)
      - min_score   : score minimum pour être considéré "crème"
      - categories  : liste des catégories de CREME_SEEDS_BY_CATEGORY à inclure.
                      None = toutes. Ex: ["🧩 Quiz & Trivia books",
                      "🖍️ Coloring books adultes (tendance)"]

    PHASE 1 — scan rapide :
      → Scanne tous les seeds des catégories choisies
      → Filtre brutal : garde uniquement les niches avec ≤ max_reviews reviews moy.
    PHASE 2 — vérification BSR (seulement les niches qui passent Phase 1)
    """
    from modules.research.scraper import AmazonScraper
    from modules.research.keywords import get_keyword_suggestions
    from modules.research.scorer import calculate_expert_creme_score

    def prog(v):
        if progress_callback: progress_callback(v)
    def status(msg):
        if status_callback: status_callback(msg)

    # ── 1. Seeds crème + enrichissement IA ───────────────────────────────────
    status("👑 Chargement des seeds ultra-sélectionnées...")
    prog(2)

    # Build seed list from chosen categories (None = all)
    chosen_cats = categories if categories else list(CREME_SEEDS_BY_CATEGORY.keys())
    seeds: List[str] = []
    for cat in chosen_cats:
        for s in CREME_SEEDS_BY_CATEGORY.get(cat, []):
            if s not in seeds:
                seeds.append(s)
    status(f"📦 {len(seeds)} seeds chargés depuis {len(chosen_cats)} catégorie(s)")

    # ── High-content discovery (vast field) ─────────────────────────────────
    if discover_high_content:
        status("🔍 Découverte high-content sur un champ vaste (autocomplete + Claude)...")
        discovered = discover_high_content_niches(
            api_key=api_key, max_niches=discover_max,
            use_autocomplete=True, use_claude=bool(use_ai and api_key),
            status_cb=status,
        )
        before = len(seeds)
        for d in discovered:
            if d not in seeds:
                seeds.append(d)
        status(f"🔍 +{len(seeds)-before} niches high-content découvertes "
               f"(total {len(seeds)} à scanner)")

    if hyper_niche:
        before = len(seeds)
        expanded: List[str] = []
        seen = set()
        for s in seeds:
            for v in expand_hyper_niche(s, max_variants=hyper_variants):
                if v not in seen:
                    expanded.append(v)
                    seen.add(v)
        seeds = expanded
        status(f"🔬 Hyper-niche : {before} → {len(seeds)} variantes audience-ciblées")

    # ── Nettoyage : retirer les métadonnées Amazon des keywords scrapés ──────
    _before = len(seeds)
    _cleaned, _seen = [], set()
    for s in seeds:
        c = _clean_niche_keyword(s)
        if c and len(c.split()) >= 2 and c.lower() not in _seen:
            _cleaned.append(c)
            _seen.add(c.lower())
    if _cleaned:
        seeds = _cleaned
    _dropped = _before - len(seeds)
    if _dropped > 0:
        status(f"🧹 Nettoyage keywords : {_dropped} niche(s) polluée(s) corrigée(s)/retirée(s)")

    # ── Filtre HIGH-CONTENT uniquement (recettes / guides / faits rédigés) ──
    if high_content_only:
        before = len(seeds)
        seeds = [s for s in seeds if is_high_content_niche(s)]
        status(f"📖 High-content uniquement : {before} → {len(seeds)} niches à contenu rédigé")

    # ── Filtre LOW-CONTENT uniquement (journaux / coloring / puzzles) ────────
    if low_content_only:
        before = len(seeds)
        seeds = [s for s in seeds if not is_high_content_niche(s)]
        status(f"📋 Low-content uniquement : {before} → {len(seeds)} niches template")

    # ── Exclusion des niches déjà scannées (rotation multi-run) ──────────────
    if exclude_keywords:
        _excl = {str(k).lower().strip() for k in exclude_keywords}
        before = len(seeds)
        seeds = [s for s in seeds if s.lower().strip() not in _excl]
        status(f"⏭️  Exclusion de {before - len(seeds)} niche(s) déjà scannée(s) — "
               f"{len(seeds)} nouvelles à couvrir")

    # ── SAFETY CAP : un scan Playwright trop gros sature la RAM et peut faire
    # planter la machine. On plafonne à MAX_SEEDS_PER_SCAN par run ; le reste
    # est sauvegardé pour le prochain scan (rotation).
    MAX_SEEDS_PER_SCAN = max(20, int(max_seeds))
    if len(seeds) > MAX_SEEDS_PER_SCAN:
        import random as _rd
        skipped = len(seeds) - MAX_SEEDS_PER_SCAN
        # SPECIFICITY-FIRST selection with a DIVERSITY QUOTA (option B): reserve
        # ~40% of the cap for NON-cooking high-content so the scan isn't 100%
        # cookbooks. Each bucket keeps its most-specific niches; the remainder is
        # filled from the combined pool. Random tie-break keeps rotation across runs.
        _rd.shuffle(seeds)
        cook = sorted([s for s in seeds if _is_cooking_niche(s)],
                      key=lambda s: -_specificity_score(s))
        noncook = sorted([s for s in seeds if not _is_cooking_niche(s)],
                         key=lambda s: -_specificity_score(s))
        noncook_quota = int(MAX_SEEDS_PER_SCAN * 0.40)      # ≥ 40% non-cooking
        cook_quota = MAX_SEEDS_PER_SCAN - noncook_quota
        picked = noncook[:noncook_quota] + cook[:cook_quota]
        # backfill if one bucket was short
        if len(picked) < MAX_SEEDS_PER_SCAN:
            leftover = [s for s in (noncook[noncook_quota:] + cook[cook_quota:])
                        if s not in picked]
            leftover.sort(key=lambda s: -_specificity_score(s))
            picked += leftover[:MAX_SEEDS_PER_SCAN - len(picked)]
        _rd.shuffle(picked)
        seeds = picked[:MAX_SEEDS_PER_SCAN]
        _nc = sum(1 for s in seeds if not _is_cooking_niche(s))
        status(f"🛡️ Scan plafonné à {MAX_SEEDS_PER_SCAN} niches — priorité SPÉCIFICITÉ "
               f"+ quota diversité ({_nc} non-cuisine / {MAX_SEEDS_PER_SCAN}) · "
               f"{skipped} autres couvertes aux prochains scans")

    if use_ai and api_key:
        status("🤖 Claude AI enrichit la liste avec des niches tendance...")
        # Build category-aware AI prompt — asks for niches matching what user picked
        cat_hint = ""
        if categories:
            cat_keys = []
            cat_to_keyword = {
                "📔 Logs spécialisés (santé)":               "specialized medical/health condition trackers",
                "💼 Professions ultra-niche":                 "specific profession/freelancer planners and logs",
                "🎨 Hobbies & loisirs niche":                 "specialized hobby trackers and collection journals",
                "🧩 Quiz & Trivia books":                     "trivia/quiz books for cult TV shows, sports teams, fandoms, decades",
                "🖍️ Coloring books adultes (tendance)":      "trending adult coloring books (mushrooms, dark academia, witchy, mandala, gothic, celestial)",
                "🧒 Coloring books enfants & ados":           "kids and teens coloring books (dinosaurs, princesses, monsters, kawaii, anime)",
                "✨ Bizarre / tendance (marchés quasi-vierges)":"weird/trending niches (paranormal, witchcraft, dark academia, manifestation)",
                "🧠 Puzzles & jeux de réflexion (gros volumes annuels)":
                    "puzzle books with HUGE annual sales (mazes large print seniors, themed word search, sudoku micro-difficulty, cryptograms, logic puzzles, nonograms, kakuro, kenken)",
                "🤖 IA & workflows tech (2026, quasi-vierge)":
                    "AI workflow trackers / prompt engineering planners (brand new 2026 micro-niche)",
            }
            for c in categories:
                if c in cat_to_keyword:
                    cat_keys.append(cat_to_keyword[c])
            if cat_keys:
                cat_hint = "Focus on these categories: " + "; ".join(cat_keys) + ".\n"
        ai_prompt = (
            "You are a KDP expert targeting the US Amazon market.\n"
            "Generate 10 niche keywords in ENGLISH with VERY LOW COMPETITION.\n"
            "Criteria: ultra-specific, niche audience, very few existing Amazon books.\n"
            f"{cat_hint}"
            f"{'Focus theme: ' + extra_theme if extra_theme else ''}\n"
            "ALL keywords must be in English. Return ONLY the keywords, one per line, nothing else."
        )
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-haiku-4-5", max_tokens=250,
                messages=[{"role": "user", "content": ai_prompt}],
            )
            extras = [
                ln.strip().lower() for ln in msg.content[0].text.strip().splitlines()
                if len(ln.strip()) > 5
            ]
            existing = set(seeds)
            for kw in extras:
                if kw not in existing:
                    seeds.append(kw)
                    existing.add(kw)
            status(f"✅ {len(extras)} niches IA ajoutées")
        except Exception as e:
            logger.warning(f"Claude enrichment: {e}")

    total = len(seeds)
    status(
        f"📋 {total} candidats — "
        f"Phase 1 : scan rapide (filtre ≤ {max_reviews} reviews, "
        f"score min {min_score})..."
    )
    prog(5)

    # ── Helper : construit le dict niche unifié ───────────────────────────────
    def _build_niche(keyword, products, kw_sugg, expert, phase=1):
        ns    = [p for p in products if not p.get("sponsored")]
        avg_r = round(
            sum(p.get("reviews", 0) for p in ns[:10]) / max(len(ns[:10]), 1), 0
        )
        return {
            "keyword":           keyword,
            "products":          products,
            "products_found":    len(products),
            "related_keywords":  kw_sugg,
            "rank":              0,
            "phase":             phase,
            # Expert score — tous les champs de calculate_expert_creme_score
            **expert,
            # Backward-compat avec le reste de l'app
            "avg_reviews":       avg_r,
            "overall":           expert["creme_score"],
            "competition_score": expert["c1_competition"],
            "demand_score":      expert["c2_demand"],
        }

    # ── 2. PHASE 1 : scan rapide ─────────────────────────────────────────────
    phase1_passed = []   # niches avec avg_reviews ≤ CREME_MAX_REVIEWS
    eliminated    = []
    failed        = []
    step_p1       = 58.0 / max(total, 1)

    # CHECKPOINT anti-crash : chaque niche validée est immédiatement écrite sur
    # disque — si la machine plante en plein scan, rien n'est perdu.
    from config import Config as _Cfg
    import json as _json
    from datetime import datetime as _dt
    _ckpt = _Cfg.HISTORY_DIR / f"creme_checkpoint_{_dt.now().strftime('%Y%m%d_%H%M')}.jsonl"
    _ckpt.parent.mkdir(parents=True, exist_ok=True)

    def _checkpoint(niche_dict):
        try:
            with open(_ckpt, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps(niche_dict, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

    try:
        with AmazonScraper() as scraper:

            for i, keyword in enumerate(seeds):
                status(f"🔬 Phase 1 [{i+1}/{total}] \"{keyword}\"...")

                try:
                    products = scraper.search_books(keyword=keyword, max_results=15)

                    if not products:
                        status(f"⚪ Ignoré \"{keyword}\" — aucun résultat")
                        failed.append({"keyword": keyword, "reason": "no_results"})
                        prog(5 + (i+1)*step_p1)
                        time.sleep(0.8)
                        continue

                    kw_sugg = get_keyword_suggestions(keyword, limit=5)

                    # VRAI volume de recherche (position autocomplete), calculé
                    # une fois et réutilisé en Phase 2 via le cache.
                    search_vol = _search_volume_score(keyword)

                    # Score Phase 1 sans BSR
                    expert = calculate_expert_creme_score(
                        products=products,
                        bsr_values=[],
                        autocomplete_demand=search_vol,
                    )

                    niche = _build_niche(keyword, products, kw_sugg, expert, phase=1)
                    avg_r = niche["avg_reviews"]

                    if avg_r <= max_reviews:
                        phase1_passed.append(niche)
                        _checkpoint(niche)   # sauvegarde immédiate anti-crash
                        status(
                            f"✅ Phase 1 OK : \"{keyword}\" "
                            f"({int(avg_r)} reviews) → passe en Phase 2 BSR"
                        )
                    else:
                        eliminated.append({
                            **niche,
                            "skip_reason": (
                                f"trop compétitif "
                                f"({int(avg_r)} reviews moy. > {max_reviews})"
                            ),
                        })
                        status(
                            f"⏭️  Éliminé Phase 1 : \"{keyword}\" "
                            f"({int(avg_r)} reviews)"
                        )

                except Exception as e:
                    logger.warning(f"Phase 1 error '{keyword}': {e}")
                    failed.append({"keyword": keyword, "reason": str(e)[:80]})

                prog(5 + (i+1)*step_p1)
                time.sleep(1.0)

            # ── ADAPTIVE FALLBACK (Phase 1) : if the strict review filter left
            # too few candidates, promote the LEAST-competitive eliminated niches
            # so Phase 2 always has something to score (never an empty scan).
            _MIN_P2 = 8
            if len(phase1_passed) < _MIN_P2 and eliminated:
                _passed_kw = {n.get("keyword") for n in phase1_passed}
                _promotable = sorted(
                    [n for n in eliminated if n.get("keyword") not in _passed_kw],
                    key=lambda n: n.get("avg_reviews", 1e9))
                _promoted = _promotable[:_MIN_P2 - len(phase1_passed)]
                for n in _promoted:
                    n["_relaxed"] = True
                phase1_passed += _promoted
                _prom_kw = {n.get("keyword") for n in _promoted}
                eliminated = [n for n in eliminated if n.get("keyword") not in _prom_kw]
                if _promoted:
                    status(f"🩹 Filtre trop strict — {len(_promoted)} niche(s) les moins "
                           f"compétitives promues en Phase 2 pour ne pas finir à vide")

            # ── Cap Phase 2 : le scraping BSR coûte ~30 s/niche. Comme on laisse
            # désormais passer beaucoup plus de niches (avis non disqualifiants),
            # on ne BSR-vérifie que les MEILLEURES par score Phase 1, EN RÉSERVANT
            # ~45% des places au NON-CUISINE → résultats diversifiés + Phase 2 rapide.
            _P2_CAP = 26
            if len(phase1_passed) > _P2_CAP:
                _sc = lambda n: n.get("creme_score") or n.get("overall") or 0
                _cook = sorted([n for n in phase1_passed if _is_cooking_niche(n.get("keyword", ""))],
                               key=_sc, reverse=True)
                _noncook = sorted([n for n in phase1_passed if not _is_cooking_niche(n.get("keyword", ""))],
                                  key=_sc, reverse=True)
                _nc_quota = int(_P2_CAP * 0.45)
                _picked = _noncook[:_nc_quota] + _cook[:_P2_CAP - _nc_quota]
                if len(_picked) < _P2_CAP:
                    _rest = sorted([n for n in phase1_passed if n not in _picked],
                                   key=_sc, reverse=True)
                    _picked += _rest[:_P2_CAP - len(_picked)]
                phase1_passed = sorted(_picked, key=_sc, reverse=True)
                _ncn = sum(1 for n in phase1_passed if not _is_cooking_niche(n.get("keyword", "")))
                status(f"🎯 Phase 2 limitée aux {len(phase1_passed)} meilleures niches "
                       f"(dont {_ncn} non-cuisine) — BSR vérifié sur celles-là")

            # ── 3. PHASE 2 : vérification BSR ────────────────────────────────
            creme_results = []

            if phase1_passed:
                n_p2 = len(phase1_passed)
                status(
                    f"🔍 Phase 2 — vérification BSR sur "
                    f"{n_p2} niche(s) prometteuse(s)..."
                )
                prog(65)
                step_p2 = 28.0 / max(n_p2, 1)

                for i, niche in enumerate(phase1_passed):
                    keyword  = niche["keyword"]
                    products = niche["products"]
                    status(f"📊 BSR [{i+1}/{n_p2}] \"{keyword}\"...")

                    try:
                        # sample 5 (not 3) top books → fairer BSR verdict, avoids
                        # killing a niche on 3 unlucky outliers.
                        enriched   = scraper.enrich_with_bsr(products, sample_size=5)
                        bsr_values = [
                            p["bsr_main"] for p in enriched
                            if isinstance(p.get("bsr_main"), int)
                        ]

                        # Re-score avec BSR réel (volume depuis le cache Phase 1)
                        expert = calculate_expert_creme_score(
                            products=products,
                            bsr_values=bsr_values,
                            autocomplete_demand=_search_volume_score(keyword),
                        )

                        niche.update({
                            **expert,
                            "phase":             2,
                            "overall":           expert["creme_score"],
                            "competition_score": expert["c1_competition"],
                            "demand_score":      expert["c2_demand"],
                        })

                        # Use the user's min_score threshold instead of the
                        # hardcoded one in the scorer
                        passes_score = expert["creme_score"] >= min_score
                        if expert["is_creme"] and passes_score:
                            creme_results.append(niche)
                            status(
                                f"💎 CRÈME : \"{keyword}\" | "
                                f"Score {expert['creme_score']}/100 | "
                                f"BSR {'✅ RÉEL' if bsr_values else '⚠️ non trouvé'} | "
                                f"{expert['verdict']}"
                            )
                            if result_callback:
                                result_callback(niche)
                        else:
                            reason = expert["action"]
                            if expert["is_creme"] and not passes_score:
                                reason = f"Score {expert['creme_score']} < seuil {min_score}"
                            eliminated.append({
                                **niche,
                                "skip_reason": reason,
                            })
                            status(
                                f"⏭️  Phase 2 éliminé : \"{keyword}\" — "
                                f"{expert['action'][:60]}"
                            )

                    except Exception as e:
                        logger.warning(f"Phase 2 error '{keyword}': {e}")
                        # Garder le score Phase 1 en fallback
                        if niche.get("is_creme"):
                            creme_results.append(niche)
                        else:
                            eliminated.append({
                                **niche,
                                "skip_reason": "Phase 2 — erreur BSR",
                            })

                    prog(65 + (i+1)*step_p2)
                    time.sleep(1.5)

            else:
                creme_results = []
                status(
                    f"😔 Aucune niche ne passe le filtre Phase 1 "
                    f"(≤ {max_reviews} reviews moy.)."
                )

    except Exception as e:
        status(f"⚠️ Erreur navigateur : {e}")
        logger.error(f"run_creme error: {e}")
        creme_results = []

    # ── FINAL FALLBACK : never return an empty scan. If nothing cleared the
    # strict crème bar, surface the top-scoring niches as "best available"
    # candidates (clearly labelled) so the user always has something to act on.
    if not creme_results and eliminated:
        _best = sorted(eliminated, key=lambda x: x.get("creme_score", 0),
                       reverse=True)[:6]
        _best_kw = {n.get("keyword") for n in _best}
        for n in _best:
            n["_best_available"] = True
            n["verdict"] = "🔎 MEILLEURE DISPO"
            n["verdict_color"] = "#D6E4FF"
            n["action"] = ("Aucune n'atteint la barre ultra-stricte — voici les "
                           "meilleures niches de ce scan à considérer / affiner")
        creme_results = _best
        eliminated = [n for n in eliminated if n.get("keyword") not in _best_kw]
        status(f"🔎 0 niche 100% crème — {len(_best)} MEILLEURES niches disponibles "
               f"remontées (au lieu d'un résultat vide)")

    # ── 4. Tri final ──────────────────────────────────────────────────────────
    creme_results.sort(key=lambda x: x["creme_score"], reverse=True)
    all_results = creme_results + eliminated
    all_results.sort(key=lambda x: x.get("creme_score", 0), reverse=True)

    for i, r in enumerate(creme_results): r["rank"] = i + 1
    for i, r in enumerate(all_results):   r["all_rank"] = i + 1

    prog(100)
    n = len(creme_results)
    best = creme_results[0]["keyword"] if creme_results else "—"

    if n:
        status(
            f"👑 Terminé ! {n} niche(s) crème sur {total} analysées. "
            f"N°1 : \"{best}\" ({creme_results[0]['creme_score']}/100)"
        )
    else:
        status(
            f"😔 Aucune niche ne passe les critères ultra-stricts ({total} analysées). "
            "Amazon a peut-être limité les données. Réessaie ou utilise le mode Autopilot standard."
        )

    # ── 4b. Annotation de tendance BSR vs scans précédents ───────────────────
    try:
        from config import Config
        from modules.research.history import annotate_trends
        annotate_trends(creme_results, Config.HISTORY_DIR)
        annotate_trends(eliminated,    Config.HISTORY_DIR)
        n_rising = sum(1 for n in creme_results if n.get("trend_arrow") in ("↑", "↗"))
        if n_rising:
            status(f"📈 {n_rising} niche(s) en hausse vs scan précédent")
    except Exception as e:
        logger.warning(f"Trend annotation skipped: {e}")

    # ── 5. Competitor analysis on the winning niches ─────────────────────────
    # Extracts title patterns, price stats, and cover color palette per niche
    # → saved to LEARNING_DIR for future cover/listing prompt injection.
    try:
        from config import Config
        from modules.learning.competitor import analyze_niche
        learning_dir = Config.LEARNING_DIR
        status(f"🧠 Analyse des concurrents pour {min(n, 10)} niche(s)...")
        for niche_data in creme_results[:10]:   # cap to avoid long waits
            kw = niche_data.get("keyword", "")
            products = niche_data.get("products", [])
            if kw and products:
                try:
                    insights = analyze_niche(
                        learning_dir=learning_dir,
                        niche=kw,
                        products=products,
                        max_covers=4,
                        fetch_images=True,
                    )
                    ts = insights.get("title_stats", {})
                    cf = insights.get("color_families", [])
                    summary = (
                        f"  · {kw[:40]}: "
                        f"titres ~{ts.get('avg_len',0):.0f}c, "
                        f"palette: {','.join(f for f,_ in cf[:2]) or '?'}"
                    )
                    status(summary)
                except Exception as e:
                    logger.warning(f"Competitor analysis failed for '{kw}': {e}")
        status(f"✅ Analyse concurrentielle terminée")
    except Exception as e:
        logger.warning(f"Competitor analysis step skipped: {e}")

    return {
        "creme":       creme_results,
        "eliminated":  eliminated,
        "failed":      failed,
        "all_results": all_results,
    }
