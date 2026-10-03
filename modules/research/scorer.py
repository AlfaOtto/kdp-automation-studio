"""
Niche opportunity scoring — Expert v2
======================================
5 critères experts pour évaluer une niche KDP :

  1. CONCURRENCE     — reviews moyennes des top livres existants
  2. DEMANDE BSR     — les livres existants vendent-ils réellement ? (BSR)
  3. VOLUME SEARCH   — estimation du volume de recherche (autocomplete)
  4. UNIFORMITÉ      — est-ce que TOUS les top livres sont peu compétitifs ?
  5. PRIX VIABLE     — la fourchette de prix permet-elle de bonnes royalties ?

Signaux additionnels (post v2.1) :
  • estimated_monthly_sales / revenue — power-law BSR→ventes (paperback)
  • competition_density               — demande autocomplete / reviews moy.
  • indie_penetration                 — % top 10 avec ≤ 100 reviews (signal indé)
"""
import logging
import math
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  BSR → VENTES (power-law calibrée paperback)
# ══════════════════════════════════════════════════════════════════════════════
#
# Données de consensus (Kindlepreneur, BookBloom, BookBeam — recalibré nov 2025) :
#   BSR     1     → ~500 sales/day
#   BSR   100     → ~100 sales/day
#   BSR  1 000    → ~30  sales/day
#   BSR 10 000    → ~6   sales/day (paperback)
#   BSR 50 000    → ~2   sales/day
#   BSR 100 000   → ~1   sales/day
#   BSR 300 000   → ~0.3 sales/day
#   BSR 1 000 000 → ~0.05 sales/day
#
# Pour le paperback (cible KDP), on applique ~30% du rythme ebook (consensus).
# Interpolation log-log entre les tiers : robuste, pas de surajustement.

_BSR_ANCHORS: List[Tuple[float, float]] = [
    (1,         500.0),
    (100,       100.0),
    (1_000,      30.0),
    (10_000,      6.0),
    (50_000,      2.0),
    (100_000,     1.0),
    (300_000,     0.3),
    (1_000_000,   0.05),
    (5_000_000,   0.005),
]


def estimate_daily_sales_from_bsr(bsr: float) -> float:
    """Estime les ventes/jour paperback depuis un BSR Amazon (US, books)."""
    if bsr is None or bsr <= 0:
        return 0.0
    if bsr <= _BSR_ANCHORS[0][0]:
        return _BSR_ANCHORS[0][1]
    if bsr >= _BSR_ANCHORS[-1][0]:
        return _BSR_ANCHORS[-1][1]
    for (b1, s1), (b2, s2) in zip(_BSR_ANCHORS, _BSR_ANCHORS[1:]):
        if b1 <= bsr <= b2:
            # log-log interp
            t = (math.log(bsr) - math.log(b1)) / (math.log(b2) - math.log(b1))
            log_s = math.log(s1) + t * (math.log(s2) - math.log(s1))
            return math.exp(log_s)
    return 0.0


def estimate_monthly_revenue(bsr: float, price: float) -> Dict:
    """
    Convertit (BSR, prix) en estimation mensuelle.
    Royalty paperback KDP ≈ 60% × (prix - coût impression).
    Coût impression approximé : $2.15 fixed + $0.012/page (paperback white ~80 pages).
    Pour rester conservateur on prend une royalty effective ~35% du prix de vente.
    """
    daily   = estimate_daily_sales_from_bsr(bsr)
    monthly = daily * 30.0
    if price and price > 0:
        royalty_per_sale = max(price * 0.35, 0.50)
        revenue_month    = monthly * royalty_per_sale
    else:
        revenue_month    = 0.0
    return {
        "est_daily_sales":          round(daily, 2),
        "est_monthly_sales":        int(round(monthly)),
        "est_monthly_revenue_usd":  int(round(revenue_month)),
    }


def estimate_niche_potential(bsr_values: List[int], avg_price: float) -> Dict:
    """
    Agrège l'estimation sur les top livres connus de la niche.
    Renvoie la médiane (résistante aux outliers) + le top performer.
    """
    if not bsr_values:
        return {
            "est_daily_sales":          0.0,
            "est_monthly_sales":        0,
            "est_monthly_revenue_usd":  0,
            "top_monthly_revenue_usd":  0,
            "potential_available":      False,
        }

    estimates = [estimate_monthly_revenue(b, avg_price) for b in bsr_values]
    estimates_sorted = sorted(estimates, key=lambda e: e["est_monthly_sales"])
    median = estimates_sorted[len(estimates_sorted) // 2]
    top    = max(estimates, key=lambda e: e["est_monthly_revenue_usd"])

    return {
        "est_daily_sales":          median["est_daily_sales"],
        "est_monthly_sales":        median["est_monthly_sales"],
        "est_monthly_revenue_usd":  median["est_monthly_revenue_usd"],
        "top_monthly_revenue_usd":  top["est_monthly_revenue_usd"],
        "potential_available":      True,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  DENSITY + INDIE PENETRATION (signaux pros)
# ══════════════════════════════════════════════════════════════════════════════

def compute_competition_density(autocomplete_demand: float, avg_reviews: float) -> Dict:
    """
    Ratio "demande / concurrence prouvée".
    Plus haut = plus de recherche pour peu de reviews existantes = whitespace.

    Score 0-100. Benchmark pros : ratio > 2.0 = excellente densité.
    """
    denom = max(avg_reviews, 1.0)
    raw   = autocomplete_demand / denom   # ex : 60 / 25 = 2.4

    if   raw >= 4.0:  score, label = 95.0, "🟢 Excellente (whitespace)"
    elif raw >= 2.0:  score, label = 80.0, "🟢 Très bonne"
    elif raw >= 1.0:  score, label = 60.0, "🟡 Correcte"
    elif raw >= 0.5:  score, label = 40.0, "🟠 Saturée"
    else:             score, label = 20.0, "🔴 Sur-saturée"

    return {
        "density_ratio": round(raw, 2),
        "density_score": score,
        "density_label": label,
    }


def compute_indie_penetration(products: List[Dict]) -> Dict:
    """
    % du top 10 qui sont indés-pénétrables : reviews ≤ 100 ET ranking effectif.
    Signal direct que la niche est pénétrable par un nouvel entrant.

    On considère "indé-pénétrable" : reviews entre 1 et 100 (exclu 0 = pas de signal).
    """
    top = [p for p in products if not p.get("sponsored")][:10]
    if not top:
        return {"indie_pct": 0.0, "indie_score": 0.0, "indie_label": "—"}

    indie = [p for p in top if 1 <= p.get("reviews", 0) <= 100]
    pct   = (len(indie) / len(top)) * 100

    if   pct >= 70: score, label = 95.0, f"🟢 {len(indie)}/{len(top)} indés rankent"
    elif pct >= 50: score, label = 80.0, f"🟢 {len(indie)}/{len(top)} indés rankent"
    elif pct >= 30: score, label = 60.0, f"🟡 {len(indie)}/{len(top)} indés rankent"
    elif pct >= 10: score, label = 40.0, f"🟠 seulement {len(indie)}/{len(top)} indé(s)"
    else:           score, label = 15.0, f"🔴 verrouillé par les gros (0 indés)"

    return {
        "indie_pct":   round(pct, 1),
        "indie_score": score,
        "indie_label": label,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  CRITÈRE 1 — CONCURRENCE (reviews moyennes)
# ══════════════════════════════════════════════════════════════════════════════

def score_competition(products: List[Dict]) -> float:
    """
    Score 0-100 (plus haut = MOINS de concurrence = meilleure opportunité).
    Basé sur le nombre moyen de reviews des 10 premiers résultats.

    POURQUOI : Plus les livres existants ont peu de reviews, plus ils sont
    faciles à dépasser. C'est LE signal #1 en KDP.
    """
    top = [p for p in products if not p.get("sponsored")][:10]
    if not top:
        return 50.0

    reviews = [p.get("reviews", 0) for p in top]
    avg = sum(reviews) / len(reviews)

    if avg == 0:    return 100.0   # Aucune review visible (possible blocage)
    elif avg <= 5:  return 95.0    # Quasi-vierge — opportunité rare
    elif avg <= 10: return 90.0    # Très peu de concurrence
    elif avg <= 25: return 80.0    # Faible concurrence — bon signal
    elif avg <= 50: return 68.0    # Concurrence modérée
    elif avg <= 100: return 52.0   # Commençait à se remplir
    elif avg <= 200: return 35.0   # Compétitif
    elif avg <= 500: return 18.0   # Très compétitif
    else:           return 8.0     # Saturé


# ══════════════════════════════════════════════════════════════════════════════
#  CRITÈRE 2 — DEMANDE BSR (les livres vendent-ils ?)
# ══════════════════════════════════════════════════════════════════════════════

def score_demand_bsr(bsr_values: List[int]) -> float:
    """
    Score 0-100 basé sur les BSR (Best Seller Rank) réels.
    Nécessite d'avoir fait la Phase 2 (fetch des pages produit).

    BSR < 100,000 = le livre vend au moins quelques copies/mois
    BSR < 50,000  = vend bien
    BSR < 20,000  = bestseller de sa catégorie

    POURQUOI : Un BSR prouve que des gens achètent dans cette niche.
    Sans BSR, on ne sait pas si c'est une niche active ou morte.
    """
    if not bsr_values:
        return 0.0  # Pas de données BSR = inconnu

    avg = sum(bsr_values) / len(bsr_values)

    if avg <= 10_000:  return 95.0
    elif avg <= 30_000:  return 85.0
    elif avg <= 75_000:  return 72.0
    elif avg <= 150_000: return 58.0
    elif avg <= 300_000: return 40.0
    elif avg <= 600_000: return 22.0
    else:                return 8.0


def score_demand_proxy(products: List[Dict]) -> float:
    """
    Estimation de la demande quand le BSR n'est pas disponible.
    Utilise le nombre de reviews comme proxy (plus de reviews = plus de ventes historiques).
    MOINS fiable que le BSR réel, mais utilisable en Phase 1 rapide.
    """
    top = [p for p in products if not p.get("sponsored")][:10]
    if not top:
        return 30.0

    avg_reviews = sum(p.get("reviews", 0) for p in top) / len(top)

    # Plus il y a de reviews, plus la niche a été active historiquement
    if avg_reviews >= 500:  return 85.0
    elif avg_reviews >= 200: return 75.0
    elif avg_reviews >= 100: return 62.0
    elif avg_reviews >= 50:  return 52.0
    elif avg_reviews >= 10:  return 40.0
    elif avg_reviews >= 1:   return 30.0
    else:                    return 22.0  # 0 reviews = demand inconnue


# ══════════════════════════════════════════════════════════════════════════════
#  CRITÈRE 3 — UNIFORMITÉ de la concurrence
# ══════════════════════════════════════════════════════════════════════════════

def score_uniformity(products: List[Dict], threshold: int = 50) -> float:
    """
    Score 0-100 basé sur le % de top livres avec peu de reviews.

    POURQUOI : La moyenne peut être trompeuse. Si 1 livre a 500 reviews
    et 9 livres ont 5 reviews, la moyenne est ~55 — mais en réalité 90%
    de la niche est exploitable. L'uniformité mesure ça.

    Ex : 8/10 livres ont ≤ 50 reviews = 80% = score 80 = bonne uniformité
    """
    top = [p for p in products if not p.get("sponsored")][:10]
    if not top:
        return 50.0

    low = sum(1 for p in top if p.get("reviews", 0) <= threshold)
    pct = (low / len(top)) * 100

    return round(pct, 1)


def score_uniformity_strict(products: List[Dict]) -> float:
    """Version stricte : % de livres avec ≤ 25 reviews (critère crème)."""
    return score_uniformity(products, threshold=25)


# ══════════════════════════════════════════════════════════════════════════════
#  CRITÈRE 4 — VIABILITÉ DU PRIX
# ══════════════════════════════════════════════════════════════════════════════

def score_price_viability(avg_price: float) -> Dict:
    """
    Score 0-100 + verdict sur la viabilité des royalties KDP.

    Zones de royalties Amazon KDP :
    - Kindle : 70% si $2.99-$9.99, sinon 35%
    - Paperback : ~60% si > $5.99
    - Hardcover : ~60% si > $8.99

    POURQUOI : Publier dans une niche où le prix moyen est $1.99 ne vaut
    pas la peine — les royalties ne couvrent pas le temps de création.
    """
    if avg_price == 0:
        return {
            "score": 40.0,
            "verdict": "❓ Inconnu",
            "detail": "Prix non disponible — données Amazon incomplètes",
            "viable": None,
        }

    if avg_price < 2.99:
        return {
            "score": 10.0,
            "verdict": "🔴 Non viable",
            "detail": f"${avg_price:.2f} — sous le seuil de royalties 70% (< $2.99)",
            "viable": False,
        }
    elif avg_price < 5.99:
        return {
            "score": 35.0,
            "verdict": "🟠 Faibles royalties",
            "detail": f"${avg_price:.2f} — royalties modestes. Possible mais sous-optimal.",
            "viable": False,
        }
    elif avg_price <= 9.99:
        return {
            "score": 88.0,
            "verdict": "🟢 Excellent",
            "detail": f"${avg_price:.2f} — zone royalties 70% Kindle. Idéal.",
            "viable": True,
        }
    elif avg_price <= 14.99:
        return {
            "score": 80.0,
            "verdict": "🟢 Très bon",
            "detail": f"${avg_price:.2f} — bonne zone pour print on demand.",
            "viable": True,
        }
    elif avg_price <= 24.99:
        return {
            "score": 65.0,
            "verdict": "🟡 Acceptable",
            "detail": f"${avg_price:.2f} — prix élevé, marché plus restreint.",
            "viable": True,
        }
    else:
        return {
            "score": 45.0,
            "verdict": "🟠 Prix élevé",
            "detail": f"${avg_price:.2f} — très haut de gamme, difficile à pénétrer.",
            "viable": True,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  SCORE GLOBAL STANDARD
# ══════════════════════════════════════════════════════════════════════════════

def calculate_opportunity_score(
    products: List[Dict],
    weights: Optional[Dict] = None,
) -> Dict:
    """Score rapide utilisé dans l'Autopilot standard."""
    if weights is None:
        weights = {"competition": 0.45, "demand": 0.40, "pricing": 0.15}

    comp    = score_competition(products)
    demand  = score_demand_proxy(products)
    pricing_data = score_price_viability(
        sum(p["price"] for p in products if p.get("price", 0) > 0) /
        max(len([p for p in products if p.get("price", 0) > 0]), 1)
    )
    pricing = pricing_data["score"]

    overall = (
        comp    * weights["competition"]
        + demand  * weights["demand"]
        + pricing * weights["pricing"]
    )

    if overall >= 78:
        tier, emoji = "EXCELLENT", "🟢"
        rec = "Très peu de concurrence et demande solide. À exploiter immédiatement."
    elif overall >= 62:
        tier, emoji = "GOOD", "🟡"
        rec = "Bonne opportunité. Focus sur une couverture de qualité pour se démarquer."
    elif overall >= 48:
        tier, emoji = "MODERATE", "🟠"
        rec = "Marché accessible mais compétitif. Cherche un angle encore plus spécifique."
    else:
        tier, emoji = "DIFFICULT", "🔴"
        rec = "Trop de concurrence. Évite ou trouve une micro-niche à l'intérieur."

    ns  = [p for p in products if not p.get("sponsored")]
    pri = [p for p in ns if p.get("price", 0) > 0]

    return {
        "overall":           round(overall, 1),
        "competition_score": round(comp, 1),
        "demand_score":      round(demand, 1),
        "pricing_score":     round(pricing, 1),
        "tier":              tier,
        "tier_emoji":        emoji,
        "tier_label":        f"{emoji} {tier}",
        "recommendation":    rec,
        "avg_reviews":       round(sum(p.get("reviews",0) for p in ns[:10]) / max(len(ns[:10]),1), 0),
        "avg_price":         round(sum(p["price"] for p in pri) / max(len(pri),1), 2) if pri else 0,
        "avg_rating":        round(sum(p.get("rating",0) for p in ns[:10]) / max(len(ns[:10]),1), 2),
        "total_products_analyzed": len(ns),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  SCORE EXPERT — "La Crème" (5 critères combinés)
# ══════════════════════════════════════════════════════════════════════════════

def calculate_expert_creme_score(
    products:           List[Dict],
    bsr_values:         List[int] = None,
    autocomplete_demand: float = 50.0,
) -> Dict:
    """
    Score expert complet pour le mode "La Crème".
    Combine les 5 critères avec pondération experte.

    Formule :
      Crème = Concurrence × 35%
            + Demande BSR × 25%      (réelle si Phase 2, proxy sinon)
            + Volume recherche × 20% (autocomplete)
            + Uniformité × 10%
            + Prix viable × 10%

    TRANSPARENCE : indique clairement ce qui est RÉEL vs ESTIMÉ.
    """
    bsr_values = bsr_values or []

    ns     = [p for p in products if not p.get("sponsored")]
    priced = [p for p in ns if p.get("price", 0) > 0]
    avg_price = sum(p["price"] for p in priced) / max(len(priced), 1) if priced else 0

    # ── Calcul des 5 signaux ──────────────────────────────────────────────────
    c1_competition   = score_competition(products)
    c2_bsr_demand    = score_demand_bsr(bsr_values) if bsr_values else None
    c2_proxy_demand  = score_demand_proxy(products)
    c3_search_volume = autocomplete_demand          # Estimé via autocomplete
    c4_uniformity    = score_uniformity(products, threshold=25)
    c5_price_data    = score_price_viability(avg_price)
    c5_price         = c5_price_data["score"]

    # Utilise le BSR réel si disponible, sinon le proxy
    bsr_available = bool(bsr_values)
    c2_demand = c2_bsr_demand if bsr_available else c2_proxy_demand

    # ── Formule pondérée ─────────────────────────────────────────────────────
    # Objectif utilisateur : remonter les niches FAIBLE/MOYENNE concurrence AVEC
    # une demande MOYENNE/FORTE. La demande réelle (c2 achat + c3 volume de
    # recherche) pèse désormais 52% (vs 45% avant), la concurrence 28% (vs 35%).
    # ⚠️ c3_search_volume doit être un VRAI signal (position autocomplete), pas
    # une constante — sinon ces 25% ne différencient rien (cf. ancien bug 55.0).
    score = (
        c1_competition  * 0.28
        + c2_demand     * 0.27
        + c3_search_volume * 0.25
        + c4_uniformity * 0.10
        + c5_price      * 0.10
    )

    # ── Pénalités hard (disqualifiants) ──────────────────────────────────────
    penalties  = []
    hard_fail  = []

    # Données de mauvaise qualité → pénalité
    non_zero_reviews = sum(1 for p in ns[:10] if p.get("reviews", 0) > 0)
    quality = round(non_zero_reviews / max(len(ns[:10]), 1) * 100)

    if quality < 40:
        score *= 0.65
        penalties.append(f"données partielles ({quality}%)")

    # Prix non viable → disqualification douce
    if c5_price_data["viable"] is False and avg_price > 0:
        score *= 0.70
        penalties.append(f"prix trop bas (${avg_price:.2f})")

    # Trop peu de produits trouvés → pénalité
    if len(ns) < 3:
        score *= 0.75
        penalties.append(f"seulement {len(ns)} produit(s) trouvé(s)")

    # BSR très mauvais → signal que la niche ne vend pas
    if bsr_available and c2_bsr_demand < 20:
        hard_fail.append(f"BSR trop élevé (niche peu active, score BSR {c2_bsr_demand})")
        score *= 0.60

    # Volume de recherche réel trop faible → "personne ne cherche cette niche".
    # Faible concurrence NE SUFFIT PAS : on veut une demande moyenne/forte.
    # (c3 = position autocomplete Amazon ; <32 = jamais remontée = demande non
    # prouvée. On pénalise fort ; <22 = disqualification douce.)
    if c3_search_volume < 22:
        hard_fail.append(f"volume de recherche quasi nul (score {c3_search_volume})")
        score *= 0.55
    elif c3_search_volume < 35:
        score *= 0.78
        penalties.append(f"faible volume de recherche ({c3_search_volume})")

    score = round(min(score, 100), 1)

    # ── Verdict ──────────────────────────────────────────────────────────────
    if hard_fail:
        verdict, v_color, action = "❌ DISQUALIFIÉE", "#FFB3B3", "Raison : " + " · ".join(hard_fail)
        is_creme = False
    elif score >= 72 and not penalties:
        verdict, v_color, action = "👑 CRÈME DE LA CRÈME", "#FFD700", "Publier immédiatement — opportunité rare"
        is_creme = True
    elif score >= 60:
        verdict, v_color, action = "✅ EXPLOITABLE", "#A8E6A3", "Bonne opportunité — lance 2-3 produits pour tester"
        is_creme = True
    elif score >= 48:
        verdict, v_color, action = "⚠️ POSSIBLE", "#FFF3B0", "Résultats incertains — cherche un angle plus spécifique"
        is_creme = False
    else:
        verdict, v_color, action = "❌ ÉLIMINÉE", "#FFB3B3", "Score trop faible — pas rentable"
        is_creme = False

    if penalties and is_creme:
        action += f" (⚠️ {', '.join(penalties)})"

    # ── Suggested price ──────────────────────────────────────────────────────
    if avg_price >= 5.99:
        suggested_price = round(avg_price * 0.88, 2)   # Légèrement sous la moyenne
        suggested_price = max(suggested_price, 5.99)
    else:
        suggested_price = 7.99  # Prix minimum viable si données manquantes

    # ── Signaux additionnels (sales estimate, density, indie) ───────────────
    potential = estimate_niche_potential(bsr_values, avg_price)
    density   = compute_competition_density(c3_search_volume,
                                            sum(p.get("reviews",0) for p in ns[:10]) / max(len(ns[:10]),1))
    indie     = compute_indie_penetration(products)

    # ── Signal labels (transparent) ──────────────────────────────────────────
    signals = [
        {
            "name":    "Concurrence (reviews)",
            "score":   round(c1_competition, 1),
            "weight":  "35%",
            "value":   f"{int(sum(p.get('reviews',0) for p in ns[:10]) / max(len(ns[:10]),1))} reviews moy.",
            "source":  "RÉEL — données Amazon directes",
            "status":  "✅" if c1_competition >= 70 else "⚠️" if c1_competition >= 50 else "❌",
        },
        {
            "name":    "Demande (BSR)" if bsr_available else "Demande (proxy)",
            "score":   round(c2_demand, 1),
            "weight":  "25%",
            "value":   f"BSR moy. {int(sum(bsr_values)/len(bsr_values))}" if bsr_available else "estimé d'après les reviews",
            "source":  "RÉEL — pages produit Amazon" if bsr_available else "ESTIMÉ — proxy reviews (Phase 2 non effectuée)",
            "status":  "✅" if c2_demand >= 55 else "⚠️" if c2_demand >= 35 else "❌",
        },
        {
            "name":    "Volume de recherche",
            "score":   round(c3_search_volume, 1),
            "weight":  "20%",
            "value":   f"Position autocomplete estimée",
            "source":  "ESTIMÉ — position dans l'autocomplete Amazon",
            "status":  "✅" if c3_search_volume >= 60 else "⚠️" if c3_search_volume >= 40 else "❌",
        },
        {
            "name":    "Uniformité concurrence",
            "score":   round(c4_uniformity, 1),
            "weight":  "10%",
            "value":   f"{int(c4_uniformity)}% des top livres ont ≤ 25 reviews",
            "source":  "RÉEL — calculé depuis les données scraping",
            "status":  "✅" if c4_uniformity >= 70 else "⚠️" if c4_uniformity >= 40 else "❌",
        },
        {
            "name":    "Viabilité du prix",
            "score":   round(c5_price, 1),
            "weight":  "10%",
            "value":   c5_price_data["detail"],
            "source":  "RÉEL — prix extraits d'Amazon" if avg_price > 0 else "INCONNU — prix non disponibles",
            "status":  "✅" if c5_price_data["viable"] else "⚠️" if c5_price_data["viable"] is None else "❌",
        },
    ]

    return {
        # Score principal
        "creme_score":       score,
        "is_creme":          is_creme,
        "verdict":           verdict,
        "verdict_color":     v_color,
        "action":            action,

        # Les 5 critères détaillés
        "signals":           signals,
        "bsr_available":     bsr_available,
        "bsr_values":        bsr_values,

        # Prix
        "avg_price":         round(avg_price, 2),
        "suggested_price":   suggested_price,
        "price_verdict":     c5_price_data["verdict"],

        # Qualité des données
        "data_quality":      quality,
        "penalties":         penalties,
        "hard_fail":         hard_fail,

        # Scores individuels pour affichage
        "c1_competition":    round(c1_competition, 1),
        "c2_demand":         round(c2_demand, 1),
        "c3_search":         round(c3_search_volume, 1),
        "c4_uniformity":     round(c4_uniformity, 1),
        "c5_price":          round(c5_price, 1),

        # Estimation ventes / revenus (basé sur BSR power-law)
        **potential,

        # Density + indie penetration
        **density,
        **indie,
    }


def rank_niches(niche_results: List[Dict]) -> List[Dict]:
    return sorted(niche_results, key=lambda x: x.get("overall", 0), reverse=True)
