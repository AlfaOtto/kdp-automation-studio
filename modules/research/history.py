"""
Scan History — sauvegarde et rechargement automatiques des résultats.
Chaque scan est sauvegardé en JSON dans output/history/.
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_PRODUCTS_PER_NICHE = 8   # Garde les N premiers produits pour alléger le fichier
MAX_HISTORY_FILES      = 50  # Nombre max de fichiers conservés


# ── Encodeur JSON (gère float/int numpy et Path) ─────────────────────────────

class _SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            return float(obj)   # numpy float → float Python
        except (TypeError, ValueError):
            pass
        try:
            return int(obj)     # numpy int → int Python
        except (TypeError, ValueError):
            pass
        if isinstance(obj, Path):
            return str(obj)
        return super().default(obj)


# ── Nettoyage des données avant sauvegarde ────────────────────────────────────

def _trim_niche(niche: dict, keep_products: bool = True) -> dict:
    """Réduit le poids d'un niche dict avant sérialisation JSON."""
    trimmed = {k: v for k, v in niche.items() if k != "products"}
    if keep_products and "products" in niche:
        # Garde seulement les champs essentiels des produits
        trimmed["products"] = [
            {
                "asin":    p.get("asin", ""),
                "title":   p.get("title", ""),
                "author":  p.get("author", ""),
                "rating":  p.get("rating", 0),
                "reviews": p.get("reviews", 0),
                "price":   p.get("price", 0),
                "format":  p.get("format", ""),
            }
            for p in niche["products"][:MAX_PRODUCTS_PER_NICHE]
        ]
    return trimmed


# ── Sauvegarde ────────────────────────────────────────────────────────────────

def save_scan(results: Dict, scan_type: str, history_dir: Path) -> Optional[Path]:
    """
    Sauvegarde les résultats d'un scan en JSON.
    Retourne le chemin du fichier créé, ou None si erreur.
    """
    try:
        history_dir.mkdir(parents=True, exist_ok=True)

        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{scan_type}_{ts}.json"
        path  = history_dir / fname

        # Construire le résumé
        if scan_type == "creme":
            niches  = results.get("creme", [])
            elim    = results.get("eliminated", [])
            failed  = results.get("failed", [])
        else:
            niches  = results.get("opportunities", [])
            elim    = results.get("skipped", [])
            failed  = results.get("failed", [])

        best = niches[0] if niches else {}
        # Tag the scan as high- or low-content so the UI can keep two separate
        # histories. Classified by the majority of the FOUND niches.
        try:
            from modules.research.autopilot import is_high_content_niche as _hc
            n_high = sum(1 for x in niches if _hc(x.get("keyword", "")))
        except Exception:
            n_high = 0
        content_mode = "high" if (niches and n_high >= len(niches) / 2) else "low"
        summary = {
            "scan_type":    scan_type,
            "timestamp":    datetime.now().isoformat(),
            "n_found":      len(niches),
            "n_eliminated": len(elim),
            "n_failed":     len(failed),
            "best_keyword": best.get("keyword", "—"),
            "best_score":   best.get("creme_score", best.get("overall", 0)),
            "content_mode": content_mode,
            "n_high":       n_high,
        }

        # Sérialiser — garder les produits pour les niches trouvées, pas les éliminées
        payload = {
            "summary": summary,
            "mode":    results.get("mode", scan_type),
            "creme" if scan_type == "creme" else "opportunities": [
                _trim_niche(n, keep_products=True) for n in niches
            ],
            "eliminated" if scan_type == "creme" else "skipped": [
                _trim_niche(n, keep_products=False) for n in elim
            ],
            "failed":      failed,
            "all_results": [
                _trim_niche(n, keep_products=(n in niches)) for n in results.get("all_results", [])
            ],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, cls=_SafeEncoder)

        logger.info(f"Scan sauvegardé : {path}")
        _prune_old_files(history_dir)
        return path

    except Exception as e:
        logger.error(f"Erreur sauvegarde scan : {e}")
        return None


# ── Chargement ────────────────────────────────────────────────────────────────

def load_history(history_dir: Path) -> List[Dict]:
    """
    Charge la liste des scans sauvegardés, du plus récent au plus ancien.
    Retourne une liste de dicts {path, summary, ...}.
    """
    if not history_dir.exists():
        return []

    files = sorted(history_dir.glob("*.json"), reverse=True)
    history = []
    for f in files[:MAX_HISTORY_FILES]:
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            summary = data.get("summary", {})
            summary["_file"] = str(f)
            summary["_filename"] = f.name
            history.append(summary)
        except Exception as e:
            logger.debug(f"Skip fichier historique {f.name}: {e}")
    return history


def load_scan(file_path: str) -> Optional[Dict]:
    """Charge un scan complet depuis son fichier JSON."""
    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erreur chargement scan {file_path}: {e}")
        return None


# ── Nettoyage auto des vieux fichiers ─────────────────────────────────────────

# ── Lookup : trouve le dernier scan d'une niche pour calculer la tendance ────

def _safe_score(n: dict) -> float:
    return float(n.get("creme_score", n.get("overall", 0)) or 0)


def _safe_bsr(n: dict) -> Optional[float]:
    """Moyenne des bsr_values si dispo, sinon None."""
    bsrs = n.get("bsr_values") or []
    bsrs = [b for b in bsrs if isinstance(b, (int, float)) and b > 0]
    if not bsrs:
        return None
    return sum(bsrs) / len(bsrs)


def lookup_previous_scan(keyword: str, history_dir: Path,
                         max_files: int = 30) -> Optional[Dict]:
    """
    Cherche l'occurrence la plus récente de `keyword` dans les scans passés.
    Retourne {ts, bsr_avg, score} ou None.
    """
    if not history_dir.exists():
        return None
    keyword_l = keyword.lower().strip()
    files = sorted(history_dir.glob("*.json"), reverse=True)[:max_files]

    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue

        # Cherche dans creme / opportunities / all_results
        for key in ("creme", "opportunities", "all_results"):
            for n in data.get(key, []) or []:
                if str(n.get("keyword", "")).lower().strip() == keyword_l:
                    return {
                        "ts":      data.get("summary", {}).get("timestamp", ""),
                        "score":   _safe_score(n),
                        "bsr_avg": _safe_bsr(n),
                        "file":    f.name,
                    }
    return None


def compute_trend(current: Dict, previous: Optional[Dict]) -> Dict:
    """
    Compare BSR + score entre scan actuel et précédent.
    Retourne arrow + label compact.
    BSR : plus bas = mieux. Donc bsr_now < bsr_prev = tendance ↑.
    """
    if not previous:
        return {
            "trend_arrow": "🆕",
            "trend_label": "premier scan",
            "trend_delta_bsr":   None,
            "trend_delta_score": None,
            "prev_bsr":   None,
            "prev_score": None,
            "prev_ts":    None,
        }

    cur_bsr = _safe_bsr(current)
    cur_sc  = _safe_score(current)
    prev_bsr = previous.get("bsr_avg")
    prev_sc  = previous.get("score") or 0.0

    delta_bsr = None
    if cur_bsr is not None and prev_bsr is not None and prev_bsr > 0:
        delta_bsr = (cur_bsr - prev_bsr) / prev_bsr   # ex: -0.20 = BSR a baissé de 20% = mieux

    delta_score = cur_sc - prev_sc

    # Arrow : priorité BSR (signal d'activité réel), fallback score
    if delta_bsr is not None:
        if   delta_bsr <= -0.25: arrow, label = "↑", f"BSR -{abs(delta_bsr)*100:.0f}% (chauffe)"
        elif delta_bsr <= -0.05: arrow, label = "↗", f"BSR -{abs(delta_bsr)*100:.0f}%"
        elif delta_bsr >=  0.25: arrow, label = "↓", f"BSR +{delta_bsr*100:.0f}% (refroidit)"
        elif delta_bsr >=  0.05: arrow, label = "↘", f"BSR +{delta_bsr*100:.0f}%"
        else:                    arrow, label = "→", "stable"
    else:
        if   delta_score >=  10: arrow, label = "↗", f"score +{delta_score:.0f}"
        elif delta_score <= -10: arrow, label = "↘", f"score {delta_score:+.0f}"
        else:                    arrow, label = "→", "score stable"

    return {
        "trend_arrow":       arrow,
        "trend_label":       label,
        "trend_delta_bsr":   round(delta_bsr, 3) if delta_bsr is not None else None,
        "trend_delta_score": round(delta_score, 1),
        "prev_bsr":          round(prev_bsr, 0) if prev_bsr else None,
        "prev_score":        round(prev_sc, 1),
        "prev_ts":           previous.get("ts", ""),
    }


def annotate_trends(niches: List[Dict], history_dir: Path) -> List[Dict]:
    """Ajoute les champs trend_* à chaque niche en cherchant le scan précédent."""
    for n in niches:
        kw = n.get("keyword", "")
        if not kw:
            continue
        prev = lookup_previous_scan(kw, history_dir)
        n.update(compute_trend(n, prev))
    return niches


def _prune_old_files(history_dir: Path):
    """Supprime les fichiers les plus anciens si on dépasse MAX_HISTORY_FILES."""
    files = sorted(history_dir.glob("*.json"))
    excess = len(files) - MAX_HISTORY_FILES
    for f in files[:excess]:
        try:
            f.unlink()
        except Exception:
            pass
