"""
KDP Automation System — Main Streamlit Application v2
"""
import sys, logging
from pathlib import Path
from datetime import datetime

# Module-level logger (used by page handlers for debug + reload tracing)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("kdp.app")

import streamlit as st
import pandas as pd

sys.path.append(str(Path(__file__).parent))

from config import Config
from modules.research.keywords import expand_keywords, get_keyword_suggestions
from modules.research.scorer import calculate_opportunity_score
from modules.research.reporter import generate_research_report
from modules.research.autopilot import (
    CATEGORIES, run_autopilot, run_creme,
    CREME_CATEGORY_NAMES, CREME_MAX_REVIEWS, CREME_MIN_SCORE,
)
from modules.research.history  import save_scan, load_history, load_scan
from modules.creation.batch_runner import (
    start_batch_in_background, get_batch_state, is_running as batch_is_running,
    reset_batch_state, cancel_batch, elapsed_seconds,
)
from modules.learning.feedback  import record_feedback, get_feedback_for_product, feedback_counts
from modules.learning.profile   import build_profile, profile_summary_for_prompt, recommend_variant
from modules.learning.competitor import get_insights, insights_summary_for_prompt

logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="KDP Automation", page_icon="📚",
    layout="wide", initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* Hide Streamlit clutter but FORCE sidebar + its toggle to stay visible. */
    #MainMenu, footer {visibility: hidden;}
    header [data-testid="stToolbar"] {visibility: hidden;}
    header {background: transparent !important;}

    /* NUCLEAR : force the sidebar AND its collapse/expand control to always
       be visible, no matter what state the browser cached. */
    [data-testid="stSidebar"] {
        display: block !important;
        visibility: visible !important;
        min-width: 244px !important;
        max-width: 350px !important;
        transform: none !important;
    }
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"],
    button[kind="header"] {
        display: block !important;
        visibility: visible !important;
        opacity: 1 !important;
    }
    /* Older Streamlit collapse button fallback */
    [aria-label="Close sidebar"],
    [aria-label="Open sidebar"] {
        visibility: visible !important;
        display: inline-flex !important;
    }
    .kdp-header {
        background: linear-gradient(135deg, #1A252F 0%, #2980B9 100%);
        padding: 20px 28px; border-radius: 12px; color: white;
        text-align: center; margin-bottom: 18px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    .kdp-header h1 { margin:0; font-size:22px; font-weight:700; }
    .kdp-header p  { margin:5px 0 0; font-size:12px; opacity:.85; }
    .mode-card {
        border-radius:10px; padding:14px 16px; margin:4px 0;
        cursor:pointer; border: 2px solid transparent;
        transition: all 0.2s;
    }
    .golden-badge {
        display:inline-block; background:#FFD700; color:#333;
        border-radius:12px; padding:2px 10px;
        font-weight:700; font-size:12px;
    }
    .stButton>button { width:100%; font-weight:600; }
    .stTabs [data-baseweb="tab"] { font-size:13px; font-weight:600; }
</style>
""", unsafe_allow_html=True)

for k, v in {
    "ap_results": None, "ap_running": False,
    "manual_products": None, "manual_scores": None,
    "manual_keywords": None, "last_keyword": "",
    # Module 2 — Creation
    "cr_results": None, "cr_running": False, "cr_log": [],
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─── Color helpers ──────────────────────────────────────────────────────────

def score_bg(s):
    if s >= 75: return "#A8E6A3"
    if s >= 62: return "#D4F0A0"
    if s >= 50: return "#FFF3B0"
    if s >= 38: return "#FFD580"
    return "#FFB3B3"

def reviews_bg(n):
    if n <= 10:  return "#7FDB7F"
    if n <= 25:  return "#A8E6A3"
    if n <= 50:  return "#C8F5C0"
    if n <= 100: return "#FFF3B0"
    if n <= 300: return "#FFD580"
    return "#FFB3B3"

def reviews_label(n):
    if n <= 10:  return "🟢 Quasi-vierge"
    if n <= 25:  return "🟢 Très faible"
    if n <= 50:  return "🟢 Faible"
    if n <= 100: return "🟡 Modérée"
    if n <= 300: return "🟠 Élevée"
    return "🔴 Saturée"

def golden_bg(s):
    if s >= 75: return "#FFD700"
    if s >= 62: return "#FFE566"
    if s >= 50: return "#FFF3B0"
    return "#F0F0F0"


def _show_global_batch_banner():
    """If a batch is running in the background, show a status banner at top
    of any page so the user knows the bot is still working."""
    try:
        bstate = get_batch_state()
        if bstate.get("running"):
            elapsed = elapsed_seconds()
            mm, ss = divmod(int(elapsed), 60)
            progress = bstate.get("progress", 0)
            n_niches = len(bstate.get("niches") or [])
            st.markdown(
                f"<div style='background:#3498DB;padding:8px 14px;border-radius:6px;"
                f"color:white;margin-bottom:10px;font-size:13px;'>"
                f"⚡ <b>Batch en cours</b> ({progress}% · {mm:02d}:{ss:02d} · "
                f"{n_niches} produit{'s' if n_niches > 1 else ''}) — "
                f"reviens à <b>✏️ Creation</b> pour voir le détail.</div>",
                unsafe_allow_html=True,
            )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE RESEARCH
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
#  CONTENT MODE — separate High-content vs Low-content everywhere
# ══════════════════════════════════════════════════════════════════════════════

def _niche_is_high(kw: str) -> bool:
    """Single source of truth for high- vs low-content classification."""
    try:
        from modules.research.autopilot import is_high_content_niche
        return is_high_content_niche(kw or "")
    except Exception:
        return False


def content_mode_selector(where: str) -> str:
    """Render the 📖 High-content / 📋 Low-content switch and return the active
    mode ('high'|'low'). Stored globally in session_state so Research and
    Creation stay in sync — two histories, two creation flows."""
    labels = {
        "📖 High-content — recettes · guides · faits": "high",
        "📋 Low-content — journaux · coloring · puzzles": "low",
    }
    keys = list(labels.keys())
    cur = st.session_state.get("content_mode", "high")
    idx = 0 if cur == "high" else 1
    choice = st.radio(
        "Type de livre", keys, index=idx, horizontal=True,
        key=f"content_mode_radio_{where}", label_visibility="collapsed",
    )
    mode = labels[choice]
    st.session_state["content_mode"] = mode
    tag = ("#e8f4ff", "#2b7bce", "📖 Mode HIGH-CONTENT — contenu rédigé (recettes, guides, faits)") \
        if mode == "high" else \
        ("#fff4e8", "#ce7b2b", "📋 Mode LOW-CONTENT — templates (journaux, coloring, puzzles)")
    st.markdown(
        f"<div style='background:{tag[0]};border-left:4px solid {tag[1]};"
        f"padding:6px 12px;border-radius:4px;margin:4px 0 10px;font-size:13px;'>"
        f"{tag[2]}</div>", unsafe_allow_html=True)
    return mode


def _entry_content_mode(entry: dict) -> str:
    """Classify a saved history entry as 'high'|'low'. Uses the stored tag when
    present, else loads the scan once and classifies by its found niches."""
    m = entry.get("content_mode")
    if m in ("high", "low"):
        return m
    try:
        data = load_scan(entry.get("_file", "")) or {}
        niches = data.get("creme") or data.get("opportunities") or []
        if not niches:
            return "low"
        n_high = sum(1 for x in niches if _niche_is_high(x.get("keyword", "")))
        return "high" if n_high >= len(niches) / 2 else "low"
    except Exception:
        return "low"


def page_research():
    # Show batch banner if a generation is running in background
    try:
        _show_global_batch_banner()
    except NameError:
        pass   # function defined later
    st.markdown("""
    <div class="kdp-header">
        <h1>🔍 Module 1 — Research de Niches KDP</h1>
        <p>La Crème · Golden Keywords · Quiz Books · Niches Bizarres · Recherche manuelle</p>
    </div>
    """, unsafe_allow_html=True)

    content_mode_selector("research")

    t1, t2, t3, t4 = st.tabs([
        "👑 La Crème — One Click",
        "🤖 Autopilot — 4 Modes",
        "🔍 Recherche manuelle",
        "📚 Historique",
    ])
    with t1: tab_creme()
    with t2: tab_autopilot()
    with t3: tab_manual()
    with t4: tab_history()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB LA CRÈME — One-Click Best Opportunities
# ══════════════════════════════════════════════════════════════════════════════

def tab_creme():
    # Hero section
    st.markdown("""
    <div style="background:linear-gradient(135deg,#1A252F,#B8860B);
                border-radius:14px;padding:24px;text-align:center;margin-bottom:20px;">
        <div style="font-size:48px;">👑</div>
        <h2 style="color:#FFD700;margin:8px 0;font-size:26px;">LA CRÈME DE LA CRÈME</h2>
        <p style="color:#eee;margin:4px 0;font-size:14px;">
            Un clic → le bot scanne 35+ niches ultra-sélectionnées → te retourne
            uniquement les opportunités qui passent les critères les plus stricts
        </p>
        <p style="color:#FFD700;font-size:12px;margin-top:8px;">
            ✅ ≤ 25 reviews moy. &nbsp;|&nbsp; ✅ Marché existant &nbsp;|&nbsp;
            ✅ Données validées &nbsp;|&nbsp; ✅ Score Crème ≥ 60/100
        </p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([3,1])
    with col1:
        focus = st.text_input(
            "🎯 Focus optionnel (laisse vide pour un scan général) :",
            placeholder="Ex: 'nurses', 'quiz TV shows', 'paranormal', 'ADHD adults'...",
        )
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        use_ai = st.checkbox("🤖 Claude AI", value=Config.has_anthropic(),
                             disabled=not Config.has_anthropic())

    if not Config.has_anthropic():
        st.caption("Clé Anthropic non configurée — enrichissement IA désactivé (⚙️ Settings)")

    # ── ⚙️ Paramètres tunables de La Crème ────────────────────────────────
    with st.expander("⚙️ Paramètres avancés (filtres & catégories)", expanded=False):
        # Default = all categories checked
        chosen_categories = st.multiselect(
            "📚 Catégories à scanner (décoche pour exclure)",
            options = CREME_CATEGORY_NAMES,
            default = CREME_CATEGORY_NAMES,
            help    = "Le scan ne testera que les seeds des catégories cochées. "
                      "Inclut maintenant Coloring books (adultes/enfants) et beaucoup plus de Quiz.",
        )
        c1, c2 = st.columns(2)
        with c1:
            # High-content books naturally carry more reviews (reviews ≠ market
            # saturation once the BSR/demand filter is doing the real work), so
            # default the Phase-1 cap higher in high-content mode.
            _mode_now = st.session_state.get("content_mode", "high")
            _default_max = 90 if _mode_now == "high" else CREME_MAX_REVIEWS
            max_reviews = st.slider(
                "🛡️ Max reviews moyennes (Phase 1 filter)",
                min_value=10, max_value=100,
                value=_default_max, step=5,
                help="Niches avec plus que ce nombre de reviews moy. sont éliminées. "
                     "Plus haut = plus permissif. En High-content, 90 par défaut "
                     "(le vrai filtre de saturation, c'est le BSR/demande).",
            )
        with c2:
            min_score = st.slider(
                "💯 Score Crème minimum",
                min_value=30, max_value=80,
                value=CREME_MIN_SCORE, step=5,
                help="Score expert minimum pour être considéré 'Crème'. "
                     "Plus bas = plus permissif.",
            )

        c3, c4 = st.columns(2)
        with c3:
            hyper_niche = st.checkbox(
                "🔬 Mode hyper-niche (×5 audiences par seed)",
                value=False,
                help="Décline chaque seed en variantes 'for teens / seniors / beginners / "
                     "women / professionals'. Multiplie le temps de scan mais trouve les "
                     "vraies micro-niches non-saturées."
            )
        with c4:
            hyper_variants = st.slider(
                "Nb d'audiences", min_value=2, max_value=6, value=4, step=1,
                disabled=not hyper_niche,
                help="Combien de variantes audience par seed",
            )

        discover_hc = st.checkbox(
            "🔍 Découverte HIGH-CONTENT (champ vaste : recettes, guides, faits)",
            value=False,
            help="Explore ~75 domaines via autocomplete Amazon + Claude pour "
                 "découvrir des centaines de niches high-content réelles (recettes, "
                 "guides how-to, livres de faits) — bien au-delà des seeds fixes. "
                 "Ajoute du temps de scan mais trouve les vraies winning niches.",
        )

        if not chosen_categories and not discover_hc:
            st.warning("⚠️ Aucune catégorie sélectionnée — sélectionne au moins une "
                       "(ou active la découverte high-content).")

    # ── Mode-driven behavior (High vs Low content) ───────────────────────────
    mode = st.session_state.get("content_mode", "high")
    if mode == "high":
        # High-content scans always discover the vast field and keep only
        # written-content niches. Auto-exclude niches already scanned before.
        discover_hc = True
        high_only, low_only = True, False
        st.caption("📖 Mode High-content : découverte activée + filtre contenu rédigé, "
                   "exclusion automatique des niches déjà scannées.")
    else:
        high_only, low_only = False, True
        st.caption("📋 Mode Low-content : scan des templates (journaux, coloring, puzzles).")

    # Bouton principal
    go = st.button("👑 Trouver La Crème Maintenant", type="primary",
                   disabled=(
                       st.session_state.get("creme_running", False)
                       or (not chosen_categories and not discover_hc)
                   ))

    if go:
        st.session_state["creme_running"] = True
        st.session_state["creme_results"] = None
        # In high mode, skip niches already covered by earlier scans (rotation).
        exclude = None
        if mode == "high":
            exclude = set()
            for e in load_history(Config.HISTORY_DIR):
                try:
                    data = load_scan(e.get("_file", "")) or {}
                    for bucket in ("creme", "eliminated", "all_results"):
                        for n in data.get(bucket, []):
                            kw = (n.get("keyword") or "").lower().strip()
                            if kw:
                                exclude.add(kw)
                except Exception:
                    pass
        _execute_creme(focus, use_ai, max_reviews, min_score, chosen_categories,
                       hyper_niche=hyper_niche, hyper_variants=hyper_variants,
                       discover_high_content=discover_hc,
                       high_content_only=high_only, low_content_only=low_only,
                       exclude_keywords=exclude)
        st.session_state["creme_running"] = False

    if st.session_state.get("creme_results"):
        _display_creme_results()


def _execute_creme(focus: str, use_ai: bool,
                   max_reviews: int = CREME_MAX_REVIEWS,
                   min_score:   int = CREME_MIN_SCORE,
                   categories:  list = None,
                   hyper_niche: bool = False,
                   hyper_variants: int = 4,
                   discover_high_content: bool = False,
                   high_content_only: bool = False,
                   low_content_only: bool = False,
                   exclude_keywords: set = None):
    bar     = st.progress(0)
    status  = st.empty()
    counter = st.empty()
    live    = []

    def on_result(n):
        live.append(n)
        v = n.get("verdict","")
        counter.markdown(
            f"💎 **{len(live)} niche(s) crème trouvée(s)** — "
            f"Dernière : **\"{n['keyword']}\"** | "
            f"Score Crème **{n['creme_score']}/100** | {v}"
        )

    results = run_creme(
        api_key=Config.ANTHROPIC_API_KEY,
        use_ai=use_ai,
        extra_theme=focus,
        progress_callback=lambda v: bar.progress(int(min(v,100))),
        status_callback=lambda m: status.info(m),
        result_callback=on_result,
        max_reviews=max_reviews,
        min_score=min_score,
        categories=categories,
        hyper_niche=hyper_niche,
        hyper_variants=hyper_variants,
        discover_high_content=discover_high_content,
        high_content_only=high_content_only,
        low_content_only=low_content_only,
        exclude_keywords=exclude_keywords,
    )

    st.session_state["creme_results"] = results
    bar.progress(100)
    counter.empty()

    # ── Sauvegarde automatique ────────────────────────────────────────────
    saved = save_scan(results, scan_type="creme", history_dir=Config.HISTORY_DIR)
    if saved:
        status.caption(f"💾 Sauvegardé automatiquement → `{saved.name}`")

    n_creme = len(results.get("creme",[]))
    n_elim  = len(results.get("eliminated",[]))
    n_fail  = len(results.get("failed",[]))

    if n_creme:
        status.success(
            f"👑 **Scan terminé !** "
            f"{n_creme} niche(s) crème trouvée(s) · "
            f"{n_elim} éliminées · "
            f"{n_fail} sans données"
        )
    elif n_elim:
        status.warning(
            f"😔 Aucune niche ne passe les critères ultra-stricts. "
            f"{n_elim} niches analysées mais trop compétitives ou données insuffisantes. "
            "Essaie le mode Autopilot standard avec un seuil plus élevé."
        )
    else:
        status.error("❌ Amazon a bloqué la majorité des requêtes. Attends 10 min et réessaie.")


def _display_creme_results():
    res   = st.session_state["creme_results"]
    creme = res.get("creme", [])
    elim  = res.get("eliminated", [])
    fail  = res.get("failed", [])
    all_  = res.get("all_results", [])

    st.markdown("---")

    # Stats
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("👑 Niches Crème",   len(creme), delta="exploitables immédiatement")
    c2.metric("⏭️ Éliminées",      len(elim),  delta="critères non atteints")
    c3.metric("📊 Total scannées", len(all_))
    c4.metric("❌ Sans données",   len(fail))

    if not creme:
        st.warning("Aucune niche crème trouvée ce scan. Voir l'onglet **Tout voir** pour les résultats complets.")
    else:
        # Podium
        st.markdown("### 🏆 Top Opportunités")
        medals = ["👑","🥇","🥈","🥉","⭐","⭐","⭐"]
        cols_count = min(len(creme), 4)
        cols = st.columns(cols_count)
        for col, medal, n in zip(cols, medals[:cols_count], creme[:cols_count]):
            cs  = n["creme_score"]
            avg_r = int(n["avg_reviews"])
            vc  = n.get("verdict_color","#eee")
            with col:
                st.markdown(f"""
                <div style="background:{vc};border-radius:12px;padding:16px;
                            text-align:center;border:2px solid #FFD700;">
                    <div style="font-size:28px;">{medal}</div>
                    <div style="font-weight:800;font-size:13px;margin:6px 0;color:#1a1a1a;">
                        {n['keyword']}
                    </div>
                    <div style="font-size:22px;font-weight:900;color:#1a252f;">
                        {cs}/100
                    </div>
                    <div style="background:#1A252F;color:white;border-radius:8px;
                                padding:3px 8px;font-size:11px;margin:5px auto;
                                display:inline-block;">
                        {avg_r} reviews · ${n.get('avg_price',0):.2f}
                    </div>
                    <div style="font-size:11px;margin-top:6px;font-weight:600;">
                        {n.get('verdict','—')}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Table complète des niches crème
        st.markdown("### 📋 Toutes les niches crème")
        from modules.research.autopilot import is_high_content_niche as _ishc
        rows = []
        for n in creme:
            avg_r = int(n["avg_reviews"])
            rows.append({
                "Rang 👑":      n["rank"],
                "Niche":        n["keyword"],
                "Type":         "📖 High" if _ishc(n.get("keyword","")) else "📋 Low",
                "Score Crème":  f"{n['creme_score']}/100",
                "💰 Rev/mois":  f"${n.get('est_monthly_revenue_usd', 0)}",
                "🔥 Densité":   f"{int(n.get('density_score', 0))}",
                "🪪 Indé":      f"{int(n.get('indie_pct', 0))}%",
                "📈 Trend":     n.get("trend_arrow", "🆕"),
                "Reviews moy.": avg_r,
                "Prix moy.":    f"${n.get('avg_price',0):.2f}",
                "Verdict":      n.get("verdict","—"),
            })
        df = pd.DataFrame(rows)
        def cc(v):
            try:
                s = float(str(v).replace("/100",""))
                return f"background-color:{golden_bg(s)};font-weight:bold"
            except: return ""
        def csc(v):
            try:
                s = float(str(v).replace("/100",""))
                return f"background-color:{score_bg(s)};font-weight:bold"
            except: return ""
        def cr(v):
            try: return f"background-color:{reviews_bg(int(v))}"
            except: return ""
        styled = (
            df.style
            .applymap(cc, subset=["Score Crème"])
            .applymap(cr, subset=["Reviews moy."])
        )
        st.dataframe(styled, use_container_width=True, hide_index=True, height=400)

        # Cards détaillées
        st.markdown("### 🔎 Fiches détaillées — prêtes à exploiter")
        for i, n in enumerate(creme):
            try:
                _creme_card(n, auto_expand=(i == 0))
            except Exception as e:
                st.error(f"❌ Erreur affichage '{n.get('keyword','?')}' : {e}")

    # Tout voir (avec et sans crème)
    with st.expander(f"📊 Voir toutes les niches analysées ({len(all_)})"):
        if all_:
            rows2 = [{
                "Niche":       r["keyword"],
                "Score Crème": f"{r['creme_score']}/100",
                "Reviews":     int(r["avg_reviews"]),
                "Verdict":     r.get("verdict","—"),
            } for r in all_]
            st.dataframe(pd.DataFrame(rows2), use_container_width=True, hide_index=True)

    # Export
    st.markdown("---")
    if creme and st.button("📥 Exporter rapport Excel — La Crème", type="secondary"):
        _export_autopilot(res)


def _creme_card(n: dict, auto_expand: bool = False):
    cs      = n.get("creme_score", 0)
    avg_r   = int(n.get("avg_reviews", 0))
    vc      = n.get("verdict_color", "#f8f9fa")
    verdict = n.get("verdict", "—")
    action  = n.get("action", "—")
    bsr_ok  = n.get("bsr_available", False)
    phase   = n.get("phase", 1)
    rank    = n.get("rank", "?")

    # High-content flag (recipes / guides / facts → real written content book)
    try:
        from modules.research.autopilot import is_high_content_niche
        _hc = is_high_content_niche(n.get("keyword", ""))
    except Exception:
        _hc = False
    _hc_tag = " · 📖 HIGH-CONTENT" if _hc else ""

    with st.expander(
        f"{'👑' if cs >= 75 else '✅'} #{rank} — {n['keyword'].upper()}"
        f"  |  Score {cs}/100  |  {avg_r} reviews{_hc_tag}",
        expanded=auto_expand,
    ):
        if _hc:
            st.markdown(
                "<div style='background:#e8f4ff;border-left:4px solid #2b7bce;"
                "padding:6px 10px;border-radius:4px;margin-bottom:8px;font-size:13px;'>"
                "📖 <b>Niche HIGH-CONTENT</b> — vrai contenu rédigé (recettes / guide / faits). "
                "Plus de valeur, meilleures reviews, marges Kindle. À créer avec le pipeline "
                "high-content (Phase 2).</div>",
                unsafe_allow_html=True,
            )
        # ── Top métriques ──────────────────────────────────────────────────
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Score Creme",   f"{cs}/100")
        c2.metric("BSR analyse",   "REEL" if bsr_ok else "estimé",
                  help="Phase 2 = BSR réel depuis les pages produit Amazon")
        c3.metric("Reviews moy.",  avg_r)
        c4.metric("Prix moy.",     f"${n.get('avg_price', 0):.2f}")
        c5.metric("Prix suggere",  f"${n.get('suggested_price', 7.99):.2f}")

        # ── Estimation revenus + tendance + signaux pros ───────────────────
        if n.get("potential_available") or n.get("trend_arrow"):
            r1, r2, r3, r4 = st.columns(4)
            mo_sales = n.get("est_monthly_sales", 0)
            mo_rev   = n.get("est_monthly_revenue_usd", 0)
            top_rev  = n.get("top_monthly_revenue_usd", 0)
            r1.metric(
                "💰 Revenu/mois estimé",
                f"${mo_rev}",
                delta=f"top performer ${top_rev}" if top_rev else None,
                help="Power-law BSR→ventes (paperback, royalty ~35%). "
                     "Médiane sur les top livres BSR connus.",
            )
            r2.metric(
                "📦 Ventes/mois (médiane)",
                f"{mo_sales}",
                help="Estimation pour un livre déjà classé au BSR médian de la niche",
            )
            density_score = n.get("density_score", 0)
            r3.metric(
                "🔥 Densité opportunité",
                f"{density_score:.0f}/100",
                delta=n.get("density_label", "—"),
                help=f"Demande recherche / reviews moy. = ratio {n.get('density_ratio', 0)}. "
                     "Plus haut = plus de whitespace.",
            )
            indie_pct = n.get("indie_pct", 0)
            r4.metric(
                "🪪 Pénétration indé",
                f"{indie_pct:.0f}%",
                delta=n.get("indie_label", "—"),
                help="% du top 10 avec ≤ 100 reviews — preuve que les indés peuvent ranker ici",
            )

        # Trend arrow (vs scan précédent)
        trend_arrow = n.get("trend_arrow")
        if trend_arrow:
            prev_ts = (n.get("prev_ts") or "")[:10] or "—"
            trend_color = {
                "↑": "#A8E6A3", "↗": "#D6F5C7",
                "→": "#E8E8E8",
                "↘": "#FFE3B0", "↓": "#FFB3B3",
                "🆕": "#D6E4FF",
            }.get(trend_arrow, "#E8E8E8")
            st.markdown(f"""
            <div style="background:{trend_color};border-radius:6px;padding:6px 12px;
                        margin:6px 0;font-size:12px;display:inline-block;">
                Tendance vs précédent : <b>{trend_arrow} {n.get('trend_label','—')}</b>
                {' · prev: ' + prev_ts if prev_ts != '—' else ''}
            </div>
            """, unsafe_allow_html=True)

        # ── Verdict coloré ─────────────────────────────────────────────────
        st.markdown(f"""
        <div style="background:{vc};border-radius:8px;padding:10px 16px;
                    margin:8px 0;font-weight:700;font-size:14px;">
            {verdict} — {action}
        </div>
        """, unsafe_allow_html=True)

        # ── Les 5 critères experts ─────────────────────────────────────────
        signals = n.get("signals", [])
        if signals:
            st.markdown("**📊 Les 5 critères experts :**")
            for sig in signals:
                s_score  = sig["score"]
                s_status = sig["status"]
                bar_color = (
                    "#A8E6A3" if s_status == "✅" else
                    "#FFF3B0" if s_status == "⚠️" else
                    "#FFB3B3"
                )
                st.markdown(f"""
                <div style="background:#f8f9fa;border-radius:8px;padding:10px 14px;
                            margin:4px 0;border-left:4px solid {bar_color};">
                    <div style="display:flex;justify-content:space-between;align-items:center;
                                flex-wrap:wrap;gap:4px;">
                        <span style="font-weight:700;font-size:13px;">
                            {s_status}&nbsp;{sig['name']}
                        </span>
                        <span style="font-weight:800;font-size:16px;color:#1A252F;">
                            {s_score}/100
                        </span>
                        <span style="font-size:11px;color:#666;background:#e8e8e8;
                                     padding:2px 8px;border-radius:10px;white-space:nowrap;">
                            Poids {sig['weight']}
                        </span>
                    </div>
                    <div style="margin-top:6px;background:#e0e0e0;border-radius:4px;height:6px;">
                        <div style="width:{int(s_score)}%;background:{bar_color};
                                    height:6px;border-radius:4px;"></div>
                    </div>
                    <div style="margin-top:4px;font-size:11px;color:#555;">
                        📌 {sig['value']}
                        &nbsp;&nbsp;<span style="color:#888;">({sig['source']})</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Alertes qualité / pénalités ────────────────────────────────────
        q = n.get("data_quality", 0)
        if q < 60:
            st.warning(f"⚠️ Qualité données : {q}% — certains chiffres peuvent être approximatifs.")
        if n.get("penalties"):
            st.warning(f"⚠️ Pénalités appliquées : {' · '.join(n['penalties'])}")
        if n.get("hard_fail"):
            st.error(f"❌ Critère disqualifiant : {' · '.join(n['hard_fail'])}")

        # ── Keywords connexes ──────────────────────────────────────────────
        if n.get("related_keywords"):
            st.markdown(
                "**Keywords à tester aussi :** " +
                " · ".join(f"`{k}`" for k in n["related_keywords"])
            )

        # ── Plan d'action ──────────────────────────────────────────────────
        st.markdown("**📌 Plan d'action :**")
        suggested_price = n.get("suggested_price", 7.99)
        price_verdict   = n.get("price_verdict", "")
        st.markdown(f"""
        1. **Créer le produit** → type recommandé basé sur le keyword : `{n['keyword']}`
        2. **Prix suggéré** → `${suggested_price:.2f}` ({price_verdict})
        3. **Keywords KDP** → utilise les {len(n.get('related_keywords', []))} suggestions connexes
        4. **Objectif** → dépasser les {avg_r} reviews existantes avec une bonne couverture
        """)

        # ── Tableau des produits concurrents ───────────────────────────────
        prods = n.get("products", [])
        if prods:
            st.markdown(f"**Concurrents actuels ({len(prods)} trouvés) :**")
            df  = pd.DataFrame(prods[:8])
            cls = [c for c in ["title","author","rating","reviews","price","format"] if c in df.columns]
            ren = {"title":"Titre","author":"Auteur","rating":"⭐","reviews":"Reviews","price":"Prix $","format":"Format"}
            def cr(v):
                try: return f"background-color:{reviews_bg(int(v))}"
                except: return ""
            st.dataframe(
                df[cls].rename(columns=ren).style.applymap(cr, subset=["Reviews"]),
                use_container_width=True, hide_index=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
#  TAB HISTORIQUE — Scans sauvegardés
# ══════════════════════════════════════════════════════════════════════════════

def tab_history():
    mode = st.session_state.get("content_mode", "high")
    mode_lbl = "📖 High-content" if mode == "high" else "📋 Low-content"
    st.markdown(f"### 📚 Historique des scans — {mode_lbl}")
    st.caption("Chaque scan est sauvegardé automatiquement. Recharge un ancien scan en 1 clic. "
               "Bascule le mode en haut de page pour voir l'autre historique.")

    all_history = load_history(Config.HISTORY_DIR)
    # Two separate histories : keep only scans matching the active mode.
    history = [e for e in all_history if _entry_content_mode(e) == mode]

    if not history:
        other = "Low-content" if mode == "high" else "High-content"
        st.info(
            f"Aucun scan **{mode_lbl}** sauvegardé pour l'instant. "
            f"Lance un scan dans l'onglet **La Crème** (mode {mode_lbl}), "
            f"ou bascule sur **{other}** en haut de page."
        )
        return

    st.success(f"✅ **{len(history)} scan(s) {mode_lbl}** sauvegardé(s) — du plus récent au plus ancien")

    for entry in history:
        ts       = entry.get("timestamp", "")[:16].replace("T", " à ")
        stype    = entry.get("scan_type", "scan")
        n_found  = entry.get("n_found", 0)
        n_elim   = entry.get("n_eliminated", 0)
        best_kw  = entry.get("best_keyword", "—")
        best_sc  = entry.get("best_score", 0)
        fname    = entry.get("_filename", "")
        fpath    = entry.get("_file", "")

        icon  = "👑" if "creme" in stype else "🤖"
        label = (
            f"{icon} {ts}  |  **{n_found} niche(s) trouvée(s)**  |  "
            f"Meilleure : *{best_kw}* ({best_sc}/100)  |  {n_elim} éliminées"
        )

        with st.expander(label):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Type de scan",   stype.replace("_", " ").title())
            c2.metric("Niches trouvées", n_found)
            c3.metric("Éliminées",       n_elim)
            c4.metric("Meilleur score",  f"{best_sc}/100")

            st.caption(f"📁 Fichier : `{fname}`")

            col_reload, col_dl = st.columns([2, 1])

            with col_reload:
                if st.button(f"🔄 Recharger ce scan", key=f"reload_{fname}"):
                    data = load_scan(fpath)
                    if data:
                        # Remettre dans session_state selon le type
                        if "creme" in stype:
                            st.session_state["creme_results"] = data
                            st.success("✅ Scan rechargé → va dans l'onglet **La Crème** pour voir les résultats")
                        else:
                            st.session_state["ap_results"] = data
                            st.success("✅ Scan rechargé → va dans l'onglet **Autopilot** pour voir les résultats")
                        st.rerun()
                    else:
                        st.error("❌ Impossible de lire le fichier.")

            with col_dl:
                try:
                    with open(fpath, "rb") as f:
                        st.download_button(
                            "⬇️ JSON",
                            data=f.read(),
                            file_name=fname,
                            mime="application/json",
                            key=f"dl_{fname}",
                        )
                except Exception:
                    pass

    st.markdown("---")
    st.caption(
        f"📁 Les fichiers sont stockés dans : "
        f"`Desktop/Claude KDP Automation/output/history/`  "
        f"(max {50} fichiers conservés)"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  AUTOPILOT
# ══════════════════════════════════════════════════════════════════════════════

MODES = {
    "micro": {
        "label":  "🎯 Micro-Niches",
        "desc":   "Niches hyper-spécifiques depuis la base de données experte (250+ seeds)",
        "color":  "#3498DB",
    },
    "golden": {
        "label":  "🏆 Golden Keywords",
        "desc":   "Fort volume de recherche Amazon + faible concurrence (via autocomplete)",
        "color":  "#F39C12",
    },
    "quiz": {
        "label":  "🧩 Quiz & Trivia Books",
        "desc":   "Catégorie sous-exploitée très rentable — 33 niches quiz pré-chargées",
        "color":  "#9B59B6",
    },
    "bizarre": {
        "label":  "😈 Niches Bizarres",
        "desc":   "Dark humor, paranormal, insolite, tendances internet — 40+ niches",
        "color":  "#E74C3C",
    },
}

def tab_autopilot():
    st.markdown("### 🤖 Sélectionne un mode — le bot fait le reste")

    # ── Sélecteur de mode ──────────────────────────────────────────────────
    cols = st.columns(4)
    mode_labels = list(MODES.keys())
    if "selected_mode" not in st.session_state:
        st.session_state.selected_mode = "micro"

    for i, (mode_key, meta) in enumerate(MODES.items()):
        with cols[i]:
            selected = st.session_state.selected_mode == mode_key
            border   = f"3px solid {meta['color']}" if selected else "2px solid #ddd"
            bg       = f"{meta['color']}22" if selected else "#fafafa"
            st.markdown(f"""
            <div style="border:{border};background:{bg};border-radius:10px;
                        padding:14px;text-align:center;min-height:90px;">
                <div style="font-size:20px;">{meta['label'].split()[0]}</div>
                <div style="font-weight:700;font-size:13px;margin:4px 0;">
                    {' '.join(meta['label'].split()[1:])}
                </div>
                <div style="font-size:11px;color:#555;">{meta['desc']}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(
                "✓ Sélectionné" if selected else "Choisir",
                key=f"mode_{mode_key}",
                type="primary" if selected else "secondary",
            ):
                st.session_state.selected_mode = mode_key
                st.rerun()

    mode = st.session_state.selected_mode
    st.markdown("---")

    # ── Paramètres ────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        if mode in ["micro"]:
            category = st.selectbox(
                "📂 Catégorie :",
                [k for k in CATEGORIES if "Tout" not in k and "Quiz" not in k and "bizarre" not in k.lower()],
            )
        else:
            category = "auto"
            st.info(f"**Mode {MODES[mode]['label']}** — pas besoin de catégorie, le système sélectionne automatiquement.")

    with col2:
        num_niches  = st.select_slider("Niches à analyser :", [8, 12, 15, 20, 25], value=12)

    with col3:
        max_reviews = st.select_slider(
            "Seuil reviews max :",
            [10, 25, 50, 75, 100],
            value=50,
            help="Seules les niches avec MOINS de X reviews en moyenne seront gardées.",
        )

    use_ai = Config.has_anthropic()
    with st.expander("🎯 Focus spécifique (optionnel — pour Claude AI)"):
        custom_theme = st.text_input(
            "",
            placeholder="Ex: 'femmes 50+', 'gaming', 'nurses', 'ADHD adults', 'true crime fans'...",
        )

    if not Config.has_anthropic():
        st.warning("⚠️ Clé Anthropic non configurée — enrichissement IA désactivé. Voir ⚙️ Settings.")

    # Explication du mode golden
    if mode == "golden":
        st.info(
            "🏆 **Mode Golden Keywords** — Comment ça marche :\n\n"
            "Amazon trie ses suggestions autocomplete par fréquence de recherche. "
            "Position 1 = le plus cherché. On utilise ça comme signal de volume GRATUIT. "
            "Puis on vérifie la concurrence réelle. "
            "**Un Golden Keyword = beaucoup de gens cherchent + peu de livres compétitifs.**"
        )

    st.markdown(f"**Filtre actif :** niches avec ≤ **{max_reviews} reviews** moy. uniquement")

    run_btn = st.button(
        f"🚀 Lancer le scan — Mode {MODES[mode]['label']}",
        type="primary",
        disabled=st.session_state.ap_running,
    )

    if run_btn:
        st.session_state.ap_results  = None
        st.session_state.ap_running  = True
        _execute_autopilot(
            category    = category,
            num_niches  = num_niches,
            mode        = mode,
            use_ai      = use_ai,
            theme       = custom_theme,
            max_reviews = max_reviews,
        )
        st.session_state.ap_running = False

    if st.session_state.ap_results:
        _display_autopilot_results(max_reviews, mode)


def _execute_autopilot(category, num_niches, mode, use_ai, theme, max_reviews):
    bar     = st.progress(0)
    status  = st.empty()
    counter = st.empty()
    found   = []

    def on_result(n):
        found.append(n)
        counter.success(
            f"✅ **{len(found)} opportunité(s)** trouvée(s) — "
            f"Dernière : \"{n['keyword']}\" "
            f"| Score {n['overall']}/100 "
            f"| Golden {n['golden_score']}/100 {n['tier_golden']}"
        )

    results = run_autopilot(
        category          = category,
        num_niches        = num_niches,
        mode              = mode,
        use_ai_expansion  = use_ai,
        custom_theme      = theme,
        api_key           = Config.ANTHROPIC_API_KEY,
        max_avg_reviews   = max_reviews,
        progress_callback = lambda v: bar.progress(int(min(v, 100))),
        status_callback   = lambda m: status.info(m),
        result_callback   = on_result,
    )

    st.session_state.ap_results = results
    bar.progress(100)
    counter.empty()

    # ── Sauvegarde automatique ────────────────────────────────────────────
    saved = save_scan(results, scan_type=f"autopilot_{mode}", history_dir=Config.HISTORY_DIR)
    if saved:
        status.caption(f"💾 Sauvegardé automatiquement → `{saved.name}`")

    opp   = results.get("opportunities", [])
    skip  = results.get("skipped", [])
    fail  = results.get("failed", [])

    if opp:
        status.success(
            f"✅ **Scan terminé !** "
            f"{len(opp)} opportunités exploitables · "
            f"{len(skip)} éliminées · "
            f"{len(fail)} échecs"
        )
    elif skip:
        status.warning(
            f"😔 Toutes les niches ({len(skip)}) dépassent {max_reviews} reviews. "
            "Augmente le seuil ou change de mode."
        )
    else:
        status.error("❌ Aucun résultat — Amazon a peut-être bloqué. Réessaie dans 5-10 min.")


def _display_autopilot_results(max_reviews: int, mode: str):
    res  = st.session_state.ap_results
    opps = res.get("opportunities", [])
    skip = res.get("skipped", [])
    fail = res.get("failed", [])
    all_ = res.get("all_results", [])

    st.markdown("---")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("🎯 Opportunités",   len(opps), delta="exploitables")
    c2.metric("⏭️ Éliminées",      len(skip), delta="trop compétitives")
    c3.metric("❌ Échecs scraping", len(fail))
    c4.metric("📊 Total analysées", len(all_))

    t1, t2, t3, t4 = st.tabs([
        f"🎯 Opportunités ({len(opps)})",
        f"📊 Tout voir ({len(all_)})",
        f"⏭️ Éliminées ({len(skip)})",
        "📥 Export",
    ])

    # ── TAB 1 : Opportunités ─────────────────────────────────────────────
    with t1:
        if not opps:
            st.warning(
                f"Aucune niche avec ≤{max_reviews} reviews. "
                "Essaie d'augmenter le seuil ou change de mode."
            )
        else:
            st.success(f"✅ **{len(opps)} niches exploitables** — reviews ≤ {max_reviews} · triées par score")

            # Podium Top 3
            medals = ["🥇","🥈","🥉"]
            for col, (m, n) in zip(st.columns(min(3,len(opps))), zip(medals, opps[:3])):
                with col:
                    gs  = n["golden_score"]
                    ov  = n["overall"]
                    col.markdown(f"""
                    <div style="background:{score_bg(ov)};border-radius:10px;
                                padding:14px;text-align:center;">
                        <div style="font-size:24px;">{m}</div>
                        <div style="font-weight:700;font-size:13px;margin:5px 0;">
                            {n['keyword']}
                        </div>
                        <div style="font-size:18px;font-weight:800;">{ov}/100</div>
                        <div style="background:{golden_bg(gs)};border-radius:8px;
                                    padding:2px 8px;display:inline-block;
                                    font-size:11px;font-weight:700;margin-top:4px;">
                            🏆 Golden {gs}/100
                        </div>
                        <div style="font-size:11px;color:#444;margin-top:4px;">
                            {int(n['avg_reviews'])} reviews · ${n['avg_price']:.2f}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            _render_table(opps, show_golden=(mode == "golden"))

            st.markdown("#### 🔎 Détail de chaque opportunité")
            for n in opps:
                _niche_expander(n, show_golden=(mode == "golden"))

    # ── TAB 2 : Tout voir ────────────────────────────────────────────────
    with t2:
        if all_:
            st.caption("Toutes les niches analysées, triées par score (y compris les trop compétitives).")
            _render_table(all_, show_golden=(mode == "golden"), show_competition_col=True)
        else:
            st.info("Aucun résultat.")

    # ── TAB 3 : Éliminées ────────────────────────────────────────────────
    with t3:
        if skip:
            st.caption(f"Éliminées car > {max_reviews} reviews en moyenne.")
            rows = [{
                "Niche":        n["keyword"],
                "Reviews moy.": int(n["avg_reviews"]),
                "Concurrence":  reviews_label(int(n["avg_reviews"])),
                "Golden":       f"{n['golden_score']}/100",
                "Score":        f"{n['overall']}/100",
                "Raison":       n.get("skip_reason","—"),
            } for n in skip]
            df = pd.DataFrame(rows)
            def cr(v):
                try: return f"background-color:{reviews_bg(int(v))}"
                except: return ""
            st.dataframe(
                df.style.applymap(cr, subset=["Reviews moy."]),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("Aucune niche éliminée.")

    # ── TAB 4 : Export ───────────────────────────────────────────────────
    with t4:
        st.markdown("### 📥 Exporter le rapport Excel")
        st.markdown("- **Opportunités** avec scores complets\n- **Produits** trouvés par niche\n- **Keywords** associés")
        if st.button("📊 Générer le rapport", type="primary"):
            _export_autopilot(res)


def _render_table(results, show_golden=False, show_competition_col=False):
    rows = []
    for n in results:
        r   = int(n.get("avg_reviews", 0))
        row = {
            "#":             n.get("rank", n.get("all_rank","—")),
            "Niche":         n["keyword"],
            "Score":         f"{n['overall']}/100",
            "Golden 🏆":     f"{n['golden_score']}/100",
            "Reviews moy.":  r,
            "Concurrence":   reviews_label(r),
            "Prix moy.":     f"${n.get('avg_price',0):.2f}",
            "Produits":      n.get("products_found",0),
        }
        if not show_golden:
            del row["Golden 🏆"]
        rows.append(row)

    df = pd.DataFrame(rows)

    def cs(v):
        try:
            s = float(str(v).replace("/100",""))
            return f"background-color:{score_bg(s)};font-weight:bold"
        except: return ""
    def cg(v):
        try:
            s = float(str(v).replace("/100",""))
            return f"background-color:{golden_bg(s)};font-weight:bold"
        except: return ""
    def cr(v):
        try: return f"background-color:{reviews_bg(int(v))}"
        except: return ""

    subset_s = ["Score"]
    subset_g = ["Golden 🏆"] if show_golden else []
    styled   = df.style.applymap(cs, subset=subset_s).applymap(cr, subset=["Reviews moy."])
    if subset_g:
        styled = styled.applymap(cg, subset=subset_g)

    st.dataframe(styled, use_container_width=True, hide_index=True, height=380)
    st.caption("🟢 Quasi-vierge (≤10) · 🟢 Très faible (≤25) · 🟢 Faible (≤50) · 🟡 Modérée (≤100) · 🔴 Saturée (>300)")


def _niche_expander(niche, show_golden=False):
    gs    = niche["golden_score"]
    ov    = niche["overall"]
    avg_r = int(niche["avg_reviews"])
    label = (
        f"{niche.get('tier_emoji','⚪')} #{niche.get('rank','?')} — "
        f"{niche['keyword'].upper()}  |  "
        f"Score {ov}/100  |  "
        f"🏆 Golden {gs}/100  |  "
        f"{avg_r} reviews moy. {reviews_label(avg_r)}"
    )
    with st.expander(label):
        if show_golden:
            c1,c2,c3,c4,c5,c6 = st.columns(6)
            c1.metric("🎯 Score",         f"{ov}/100")
            c2.metric("🏆 Golden",        f"{gs}/100")
            c3.metric("🔎 Demande Search", f"{niche['autocomplete_demand']}/100",
                      help="Estimé d'après la position dans l'autocomplete Amazon")
            c4.metric("⚔️ Compétition",   f"{niche['competition_score']}/100")
            c5.metric("📈 Demande achat", f"{niche['demand_score']}/100")
            c6.metric("Reviews moy.",     avg_r)
        else:
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("🎯 Score",        f"{ov}/100")
            c2.metric("⚔️ Compétition",  f"{niche['competition_score']}/100")
            c3.metric("📈 Demande",      f"{niche['demand_score']}/100")
            c4.metric("Reviews moy.",    avg_r)
            c5.metric("Prix moy.",       f"${niche.get('avg_price',0):.2f}")

        # Tier golden badge
        tier_g = niche.get("tier_golden","")
        if "GOLDEN" in tier_g or "EXCELLENT" in tier_g:
            st.markdown(f"""
            <div style="background:#FFD700;border-radius:8px;padding:8px 14px;
                        display:inline-block;font-weight:700;font-size:13px;">
                {tier_g} — Forte demande de recherche + faible concurrence
            </div>
            """, unsafe_allow_html=True)

        if niche.get("data_quality",100) < 50:
            st.warning(f"⚠️ Qualité données : {niche['data_quality']}% — Amazon a peut-être limité le scan.")

        st.info(f"💡 **Recommandation :** {niche['recommendation']}")

        if niche.get("related_keywords"):
            st.markdown("**Keywords connexes :** " + " · ".join(niche["related_keywords"]))

        prods = niche.get("products",[])
        if prods:
            df = pd.DataFrame(prods[:10])
            cols = [c for c in ["title","author","rating","reviews","price","format"] if c in df.columns]
            ren  = {"title":"Titre","author":"Auteur","rating":"⭐","reviews":"Reviews","price":"Prix $","format":"Format"}
            def cr(v):
                try: return f"background-color:{reviews_bg(int(v))}"
                except: return ""
            st.dataframe(
                df[cols].rename(columns=ren).style.applymap(cr,subset=["Reviews"]),
                use_container_width=True, hide_index=True,
            )


def _export_autopilot(results):
    with st.spinner("Génération..."):
        try:
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            all_ = results.get("all_results", [])
            if not all_:
                st.error("Rien à exporter.")
                return
            products_flat = [p for r in all_ for p in r.get("products", [])[:5]]
            kw_list       = [{"keyword": r["keyword"], "source": r.get("source","auto"), "level": 1} for r in all_]

            # scores : utilise le premier dispo, ou construit un fallback depuis le niche dict
            first = all_[0]
            scores_export = first.get("scores") or {
                "overall":           first.get("overall", 0),
                "competition_score": first.get("competition_score", 0),
                "demand_score":      first.get("demand_score", 0),
                "pricing_score":     first.get("c5_price", 0),
                "tier":              "CREME",
                "tier_emoji":        "👑",
                "tier_label":        "👑 CREME",
                "recommendation":    first.get("action", ""),
                "avg_reviews":       first.get("avg_reviews", 0),
                "avg_price":         first.get("avg_price", 0),
                "avg_rating":        0,
                "total_products_analyzed": first.get("products_found", 0),
            }

            out  = str(Config.RESEARCH_DIR / f"autopilot_{ts}.xlsx")
            path = generate_research_report(
                keyword=f"Autopilot — {len(all_)} niches",
                products=products_flat,
                scores=scores_export,
                keyword_suggestions=kw_list,
                output_path=out,
            )
            with open(path, "rb") as f:
                st.download_button(
                    "⬇️ Télécharger Excel", data=f.read(),
                    file_name=f"KDP_Autopilot_{ts}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            # Fonctionne pour autopilot (clé "opportunities") et creme (clé "creme")
            n_ok = len(results.get("opportunities", results.get("creme", [])))
            st.success(f"✅ Rapport prêt — {n_ok} opportunité(s) incluse(s) !")
        except Exception as e:
            st.error(f"Erreur export : {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  RECHERCHE MANUELLE
# ══════════════════════════════════════════════════════════════════════════════

def tab_manual():
    st.markdown("### 🔍 Analyser un keyword précis")
    col_kw, col_n = st.columns([3,1])
    with col_kw:
        keyword = st.text_input("Keyword :", placeholder="ex: nurse self care journal, axolotl coloring book...")
    with col_n:
        max_r = st.select_slider("Produits :", [10,20,30,40], value=20)

    c1,c2 = st.columns(2)
    expand_kw = c1.checkbox("Auto-expand keywords",value=True)
    get_bsr   = c2.checkbox("Fetch BSR (plus lent)",value=False)

    if st.button("🔍 Analyser", type="primary", disabled=not keyword):
        _run_manual(keyword, max_r, expand_kw, get_bsr)

    if st.session_state.manual_products is not None:
        _display_manual()


def _run_manual(keyword, max_r, expand_kw, get_bsr):
    bar = st.progress(0); status = st.empty()
    try:
        status.info("📡 Récupération keywords...")
        bar.progress(10)
        if expand_kw:
            kw_data = expand_keywords(keyword, depth=2)
        else:
            kws = get_keyword_suggestions(keyword)
            kw_data = [{"keyword":k,"source":keyword,"level":1} for k in kws]
        st.session_state.manual_keywords = kw_data
        bar.progress(25)

        status.info(f"🕷️ Scan Amazon \"{keyword}\"...")
        products = []
        try:
            from modules.research.scraper import AmazonScraper
            with AmazonScraper() as s:
                products = s.search_books(keyword=keyword, max_results=max_r,
                    progress_callback=lambda m: status.info(f"🕷️ {m}"))
                bar.progress(65)
                if get_bsr and products:
                    products = s.enrich_with_bsr(products, 5,
                        progress_callback=lambda m: status.info(f"📊 {m}"))
        except Exception as e:
            st.warning(f"⚠️ Scraping partiel : {e}")

        bar.progress(85)
        scores = calculate_opportunity_score(products)
        st.session_state.manual_products = products
        st.session_state.manual_scores   = scores
        st.session_state.last_keyword    = keyword
        bar.progress(100)
        avg_r = int(scores["avg_reviews"])
        status.success(
            f"✅ {len(products)} produits · Score {scores['overall']}/100 · "
            f"{avg_r} reviews moy. → {reviews_label(avg_r)}"
        )
    except Exception as e:
        status.error(f"❌ {e}")


def _display_manual():
    sc = st.session_state.manual_scores
    pr = st.session_state.manual_products
    kw = st.session_state.last_keyword
    st.markdown("---")
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("🎯 Score",     f"{sc['overall']}/100", delta=sc["tier_label"])
    c2.metric("⚔️ Compét.",  f"{sc['competition_score']}/100")
    c3.metric("📈 Demande",  f"{sc['demand_score']}/100")
    c4.metric("💰 Prix moy.",f"${sc['avg_price']:.2f}" if sc["avg_price"] else "N/A")
    c5.metric("📦 Produits", sc["total_products_analyzed"])
    avg_r = int(sc["avg_reviews"])
    st.markdown(f"**Concurrence : {reviews_label(avg_r)}** — {avg_r} reviews moy.")
    cmap={"EXCELLENT":"success","GOOD":"info","MODERATE":"warning","DIFFICULT":"error"}
    getattr(st, cmap.get(sc["tier"],"info"))(f"**{sc['tier_emoji']} {sc['tier']}** — {sc['recommendation']}")

    tp,tk,te = st.tabs(["📦 Produits","🔑 Keywords","📥 Export"])
    with tp:
        if pr:
            df  = pd.DataFrame(pr)
            cls = [c for c in ["position","title","author","rating","reviews","price","format"] if c in df.columns]
            ren = {"position":"#","title":"Titre","author":"Auteur","rating":"⭐","reviews":"Reviews","price":"Prix $","format":"Format"}
            def cr(v):
                try: return f"background-color:{reviews_bg(int(v))}"
                except: return ""
            st.dataframe(df[cls].rename(columns=ren).style.applymap(cr,subset=["Reviews"]),
                use_container_width=True, hide_index=True, height=400)
            nz = sum(1 for p in pr if p.get("reviews",0)>0)
            q  = round(nz/len(pr)*100)
            if q < 50:
                st.warning(f"⚠️ Qualité données : {q}% — Amazon peut avoir limité le scan.")
        else:
            st.info("Aucun produit trouvé.")
    with tk:
        kd = st.session_state.manual_keywords or []
        if kd:
            c1,c2,c3 = st.columns(3)
            for i,item in enumerate(kd[:60]):
                kk  = item["keyword"] if isinstance(item,dict) else item
                lvl = item.get("level",1) if isinstance(item,dict) else 1
                [c1,c2,c3][i%3].markdown(f"{'🔹' if lvl==1 else '◽'} {kk}")
        else:
            st.info("Aucun keyword.")
    with te:
        if st.button("📊 Rapport Excel", type="primary"):
            with st.spinner("Génération..."):
                try:
                    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe = kw.replace(" ","_")
                    out  = str(Config.RESEARCH_DIR / f"research_{safe}_{ts}.xlsx")
                    path = generate_research_report(kw,pr,sc,
                        st.session_state.manual_keywords or [], out)
                    with open(path,"rb") as f:
                        st.download_button("⬇️ Télécharger",data=f.read(),
                            file_name=f"KDP_{safe}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    st.success("✅ Prêt !")
                except Exception as e:
                    st.error(f"Erreur : {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  AUTRES PAGES
# ══════════════════════════════════════════════════════════════════════════════

def page_intelligence():
    """🧠 Intelligence — 7 onglets : Overview · Performance · Recommender · Market ·
    Graph · Competitive · Keywords."""
    try:
        _show_global_batch_banner()
    except NameError:
        pass
    st.markdown(
        '<div class="kdp-header">'
        '<h1>🧠 Intelligence — phase critique</h1>'
        '<p>Performance · Recommendations · Market · Graph · Competitive · Keywords</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # Late imports to keep module load lazy
    from modules.intelligence.performance  import (
        overall_kpis, weekly_performance, best_book, loss_patterns,
    )
    from modules.intelligence.recommender  import daily_action_list
    from modules.intelligence.market       import market_brief, is_fresh, load_cached
    from modules.intelligence.graph        import build_graph, render_graph_markdown, find_strong_paths
    from modules.intelligence.competitive  import competitive_brief, brief_for_prompt
    from modules.intelligence.keywords_pro import expand_keywords_pro, select_top_7

    # ── Cache the heavy intelligence reads (5-10 min TTL) ────────────────
    # These iterate over all feedback + run multi_signal computations.
    # Without cache, every tab click rebuilds the whole thing.
    _LD_STR = str(Config.LEARNING_DIR)
    _HD_STR = str(Config.HISTORY_DIR)

    @st.cache_data(ttl=120, show_spinner=False)
    def _kpis(_ld):
        return overall_kpis(Path(_ld))

    @st.cache_data(ttl=300, show_spinner=False)
    def _weekly(_ld, n=8):
        return weekly_performance(Path(_ld), n_weeks=n)

    @st.cache_data(ttl=300, show_spinner=False)
    def _best(_ld):
        return best_book(Path(_ld))

    @st.cache_data(ttl=300, show_spinner=False)
    def _losses(_ld):
        return loss_patterns(Path(_ld))

    @st.cache_data(ttl=300, show_spinner=False)
    def _daily(_ld, _hd, n=8):
        return daily_action_list(Path(_ld), Path(_hd), n_to_generate=n)

    @st.cache_data(ttl=600, show_spinner=False)
    def _graph(_ld):
        g = build_graph(Path(_ld))
        return g, render_graph_markdown(g, max_edges=20), find_strong_paths(g)

    tabs = st.tabs([
        "📊 Overview",
        "📈 Performance",
        "🎯 Recommender",
        "🌐 Market intel",
        "🔗 Combo Graph",
        "🔍 Competitive Brief",
        "🔑 Keywords Pro",
    ])

    # ── TAB 1 : Overview ─────────────────────────────────────────────
    with tabs[0]:
        kpis = _kpis(_LD_STR)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Livres notés",  kpis["n_books"])
        m2.metric("✅ Publiés",     kpis["n_published"])
        m3.metric("Win rate",      f"{kpis['win_rate']}%")
        m4.metric("True quality",  f"{kpis['avg_quality']}/100")
        m5, m6, m7, m8 = st.columns(4)
        m5.metric("👍 J'aime",     kpis["n_up"])
        m6.metric("👎 Rejets",     kpis["n_down"])
        m7.metric("🎨 Cover regens",kpis["n_regens"])
        m8.metric("✏️ Edits",       kpis["n_edits"])

        bb = _best(_LD_STR)
        if bb:
            st.success(
                f"🏆 **Meilleur livre** : `{bb['title'][:60]}` — "
                f"true quality **{bb['score']}/100** (variant: {bb.get('variant', '?')}, "
                f"theme: {bb.get('theme', '?')})"
            )

        lp = _losses(_LD_STR)
        if lp and lp.get("losing_variants"):
            with st.expander("🔴 Patterns d'échec à éviter"):
                st.write("**Variants gagnant le plus de 👎 :**")
                for v, n in lp["losing_variants"]:
                    st.write(f"  · `{v}` — {n} échec(s)")
                st.write("**Thèmes qui ratent :**")
                for t, n in lp["losing_themes"]:
                    st.write(f"  · `{t}` — {n} échec(s)")

        # ── Learned cover-design preferences (from your fine-tunes) ───────
        try:
            from modules.learning.events import cover_preferences
            _cp = cover_preferences(Config.LEARNING_DIR)
            if _cp.get("ready"):
                st.info(
                    "🎨 **Préférences cover apprises** (appliquées auto sur chaque "
                    f"nouvelle génération) — basé sur {_cp['n_signals']} fine-tune(s) :\n\n"
                    + "  ·  ".join(_cp.get("notes", []))
                )
            elif _cp.get("n_signals", 0) > 0:
                st.caption(
                    f"🎨 Apprentissage cover en cours : {_cp['n_signals']}/3 fine-tune(s). "
                    "Continue à ajuster tes covers — le bot apprendra ton style à partir de 3."
                )
        except Exception:
            pass

    # ── TAB 2 : Performance time-series ───────────────────────────────
    with tabs[1]:
        st.markdown("### 📈 Performance hebdomadaire (8 dernières semaines)")
        pts = _weekly(_LD_STR, n=8)
        if pts:
            import pandas as _pd
            df = _pd.DataFrame([{
                "Semaine":     p.date,
                "Générés":     p.n_generated,
                "Publiés":     p.n_published,
                "Win rate %":  p.win_rate,
                "True quality":p.avg_quality,
            } for p in pts])
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.line_chart(df.set_index("Semaine")[["Win rate %", "True quality"]])
        else:
            st.info("Pas encore de données hebdomadaires — note tes livres.")

    # ── TAB 3 : Recommender ──────────────────────────────────────────
    with tabs[2]:
        st.markdown("### 🎯 Niches à générer aujourd'hui")
        st.caption("Combine predictor + historique Crème + transfer cross-niche")
        rec = _daily(_LD_STR, _HD_STR, n=8)
        if rec["to_generate"]:
            for r in rec["to_generate"]:
                tier_color = "#27AE60" if r.predicted_score >= 75 else (
                    "#F39C12" if r.predicted_score >= 60 else "#E74C3C")
                st.markdown(
                    f"<div style='border-left:4px solid {tier_color};padding:8px 12px;"
                    f"margin:5px 0;background:#FAFAFA;border-radius:4px;'>"
                    f"🎯 <b>{r.niche}</b> · pred <b>{r.predicted_score}/100</b> · "
                    f"comp {r.competition} · conf {int(r.confidence*100)}%"
                    f"<br><small>{r.rationale}</small></div>",
                    unsafe_allow_html=True,
                )
            if st.button("📋 Copier ces niches dans Création", key="recopy"):
                st.session_state["cr_seed_niches"] = "\n".join(
                    r.niche for r in rec["to_generate"]
                )
                st.toast("Niches préparées — va sur Création", icon="✅")
        else:
            st.info(rec["summary"])

    # ── TAB 4 : Market Intelligence ──────────────────────────────────
    with tabs[3]:
        st.markdown("### 🌐 Best-sellers Amazon par catégorie")
        st.caption("Scrape les 20 top résultats pour une catégorie KDP, cache 7 jours.")
        col_q, col_btn = st.columns([3, 1])
        with col_q:
            mkt_query = st.text_input(
                "Catégorie ou recherche KDP",
                placeholder="ex: 'adult coloring book mandala' ou 'travel journal'",
                key="mkt_query",
            )
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            mkt_go = st.button("🔍 Scraper / charger", key="mkt_go")
        if mkt_go and mkt_query:
            log_box = st.empty()
            log_lines = []
            def push_mkt(m):
                log_lines.append(m)
                log_box.code("\n".join(log_lines[-10:]))
            with st.spinner(f"Analyse de '{mkt_query}'…"):
                data = market_brief(Config.LEARNING_DIR, mkt_query, status_cb=push_mkt)
            st.session_state["mkt_last"] = data
        data = st.session_state.get("mkt_last")
        if data:
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Produits", data.get("n_products", 0))
            mc2.metric("Prix avg",  f"${data.get('avg_price', 0)}")
            mc3.metric("Reviews avg",int(data.get('avg_reviews', 0)))
            mc4.metric("Saturation",f"{data.get('saturation_pct', 0)}%")
            words = data.get("top_title_words", [])
            if words:
                st.write("**Mots récurrents dans les titres bestsellers :**")
                st.write(" · ".join(f"`{w}` ({n})" for w, n in words[:12]))

    # ── TAB 5 : Combo Knowledge Graph ────────────────────────────────
    with tabs[4]:
        st.markdown("### 🔗 Knowledge Graph — combos qui marchent")
        g, graph_md, paths = _graph(_LD_STR)
        st.markdown(graph_md)
        if paths:
            st.markdown("**Chemins forts (combos répétables) :**")
            for p in paths:
                st.markdown(f"  · {p}")

    # ── TAB 6 : Competitive Deep Brief ───────────────────────────────
    with tabs[5]:
        st.markdown("### 🔍 Brief compétitif par niche")
        st.caption("Scrape les 10 best-sellers d'une niche + analyse profonde.")
        col_cb_q, col_cb_btn = st.columns([3, 1])
        with col_cb_q:
            cb_niche = st.text_input(
                "Niche cible", key="cb_niche",
                placeholder="ex: '90s hip hop trivia book'",
            )
        with col_cb_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            cb_go = st.button("🔬 Analyser", key="cb_go")
        if cb_go and cb_niche:
            cb_log = st.empty()
            cb_lines = []
            def push_cb(m):
                cb_lines.append(m); cb_log.code("\n".join(cb_lines[-8:]))
            with st.spinner("Analyse en cours…"):
                brief = competitive_brief(cb_niche, status_cb=push_cb)
            st.session_state["cb_last"] = brief
        brief = st.session_state.get("cb_last")
        if brief and not brief.get("error"):
            bb1, bb2, bb3 = st.columns(3)
            bb1.metric("Compétiteurs", brief.get("n_competitors", 0))
            bb2.metric("Prix avg",
                       f"${brief.get('price_stats', {}).get('avg', 0)}")
            bb3.metric("Reviews max",
                       int(brief.get('reviews_stats', {}).get('max', 0)))
            tt = brief.get("title_stats", {})
            st.write(f"**Title length avg** : {tt.get('avg_length', 0)} chars · "
                     f"**Format 'Title:Subtitle'** : {tt.get('uses_colon_pct', 0)}%")
            words = brief.get("common_words", [])
            if words:
                st.write("**Mots gagnants** : " +
                         " · ".join(f"`{w}`" for w, _ in words[:12]))
            st.markdown("**Top 5 compétiteurs :**")
            for c in brief.get("top_competitors", []):
                st.markdown(f"  · `{c['title']}` · ${c['price']} · "
                            f"{c['reviews']} reviews · BSR {c.get('bsr', '—')}")
            st.markdown("---")
            st.code(brief_for_prompt(brief), language=None)

    # ── TAB 7 : Keywords Pro ─────────────────────────────────────────
    with tabs[6]:
        st.markdown("### 🔑 Keywords research pro")
        st.caption("Expand autocomplete + score ROI + select top 7 mix d'intentions.")
        kw_seed = st.text_input("Niche / seed keyword", key="kwp_seed",
                                placeholder="ex: 'aquarium fish keeper log'")

        # ── 🌐 WEB keyword research — ce qui marche VRAIMENT ─────────────
        with st.container():
            st.markdown("#### 🌐 Recherche web — ce qui marche vraiment")
            st.caption("Claude étudie sur le web les best-sellers de la niche + le langage réel "
                       "des acheteurs + les tendances, puis propose des keywords optimisés. "
                       "1 seul appel web ≈ 0,20 $.")
            kwb_title = st.text_input(
                "Titre du livre (optionnel — évite de répéter les mots déjà dans le titre)",
                key="kwb_title", placeholder="ex: 'High-Protein Air Fryer Cookbook for Beginners'")
            if kw_seed and st.button("🌐 Trouver les meilleurs keywords (recherche web)", key="kwb_go"):
                from modules.intelligence.keyword_web import research_keywords
                _box = st.empty(); _logs = []
                def _pushk(m): _logs.append(m); _box.code("\n".join(_logs[-6:]))
                with st.spinner("Recherche web en cours… ~20-40s"):
                    st.session_state["kwb_result"] = research_keywords(
                        kw_seed, Config.ANTHROPIC_API_KEY,
                        book_title=kwb_title, status_cb=_pushk)
            web = st.session_state.get("kwb_result") or {}
            if web.get("optimized_keywords"):
                if web.get("best_angle"):
                    st.info(f"🎯 **Meilleur angle** : {web['best_angle']}")
                st.markdown("**✅ Keywords optimisés (basés sur la recherche web) :**")
                _rows = [{"Keyword": k.get("keyword"), "Intention": k.get("intent"),
                          "Pourquoi ça marche": k.get("why")}
                         for k in web["optimized_keywords"]]
                st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)
                kwb_list = [k.get("keyword") for k in web["optimized_keywords"] if k.get("keyword")]
                if web.get("trending"):
                    st.markdown("**📈 En hausse (tendance) :** "
                                + " · ".join(f"`{t}`" for t in web["trending"][:8]))
                if web.get("avoid"):
                    st.markdown("**🚫 À éviter (saturés) :** "
                                + " · ".join(f"`{t}`" for t in web["avoid"][:8]))
                cwv1, cwv2 = st.columns([1, 2])
                with cwv1:
                    if st.button("🔎 Valider volume Amazon", key="kwb_validate"):
                        try:
                            from modules.intelligence.keyword_tower import validate_keywords_amazon
                            with st.spinner("Probe autocomplete Amazon…"):
                                st.session_state["kwb_val"] = validate_keywords_amazon(
                                    kwb_list[:7], delay_s=0.4)
                        except Exception as e:
                            st.error(f"Validation impossible : {e}")
                with cwv2:
                    _v = st.session_state.get("kwb_val")
                    if _v:
                        st.metric("Validés sur Amazon",
                                  f"{_v.get('validated', 0)}/{min(len(kwb_list), 7)}")
                st.download_button("⬇️ Copier les 7-10 keywords", data="\n".join(kwb_list),
                                   file_name="keywords_web.txt", key="kwb_dl")
        st.markdown("---")

        st.caption("Ou méthode autocomplete Amazon (gratuit, sans IA) :")
        if kw_seed and st.button("🚀 Expand + scorer", key="kwp_go"):
            with st.spinner("Recherche…"):
                scored = expand_keywords_pro(kw_seed, depth=2, n_max=40)
            st.session_state["kwp_scored"] = scored
        scored = st.session_state.get("kwp_scored", [])
        if scored:
            top7 = select_top_7(scored)
            st.success(f"✅ Top 7 sélectionnés (mix d'intentions) :")
            for kw in top7:
                st.markdown(f"  · `{kw}`")

            # ── NEW : live Amazon volume validation on top 7 ────────────
            col_a, col_b = st.columns([1, 3])
            with col_a:
                if st.button("🔎 Valider volume Amazon (top 7)", key="kwp_validate"):
                    try:
                        from modules.intelligence.keyword_tower import (
                            validate_keywords_amazon,
                        )
                        with st.spinner("Probe Amazon autocomplete… ~3s"):
                            res = validate_keywords_amazon(top7, delay_s=0.4)
                        st.session_state["kwp_validation"] = res
                    except Exception as e:
                        st.error(f"Validation impossible : {e}")
            with col_b:
                v = st.session_state.get("kwp_validation")
                if v:
                    st.metric("Keywords validés sur Amazon",
                              f"{v.get('validated', 0)}/7")

            # ── NEW : volume + demand bar in main table ────────────────
            st.markdown("**Tous les keywords scorés (40 max) :**")
            import pandas as _pd

            def _demand_bars(volume: int, n_max: int = 40) -> str:
                """Visual indicator : ★★★★★ based on autocomplete rank."""
                pct = (volume / max(n_max, 1))
                if pct >= 0.85:  return "★★★★★"
                if pct >= 0.65:  return "★★★★☆"
                if pct >= 0.45:  return "★★★☆☆"
                if pct >= 0.25:  return "★★☆☆☆"
                return "★☆☆☆☆"

            def _source_from_notes(notes: str) -> str:
                # notes is "level=1" etc — we infer source from level
                if "level=1" in notes: return "📡 autocomplete"
                if "level=2" in notes: return "🔤 alphabet a-z"
                return "🧩 expansion"

            df_kw = _pd.DataFrame([{
                "Score":   k.score,
                "Volume":  k.volume,             # rank 1-40
                "Demand":  _demand_bars(k.volume),
                "Keyword": k.keyword,
                "Intent":  k.intent,
                "Words":   k.n_words,
                "Source":  _source_from_notes(k.notes),
            } for k in scored])

            # If we ran live validation, merge confidence dots into table
            valid = st.session_state.get("kwp_validation")
            if valid and isinstance(valid, dict):
                results = valid.get("results", {})
                def _dot(kw: str) -> str:
                    info = results.get(kw, {})
                    conf = float(info.get("confidence", 0) or 0)
                    if not info: return "—"
                    if conf >= 0.75: return "🟢 exact"
                    if conf >= 0.4:  return "🟡 partial"
                    return "🔴 0 volume"
                df_kw["Amazon"] = df_kw["Keyword"].apply(_dot)

            # ── NEW : interactive table with SELECT column ──────────────
            # Add a "✔" column (default False) so user can pick which keywords
            # to apply directly to a book without copy-paste.
            df_kw.insert(0, "✔", False)
            edited = st.data_editor(
                df_kw,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "✔": st.column_config.CheckboxColumn(
                        "Pick", help="Cocher pour appliquer ce keyword au livre",
                        default=False,
                    ),
                    "Score":   st.column_config.NumberColumn(format="%.1f"),
                    "Volume":  st.column_config.NumberColumn(help="40 = top demande, 1 = queue"),
                    "Keyword": st.column_config.TextColumn(width="large"),
                },
                disabled=[c for c in df_kw.columns if c != "✔"],
                key="kwp_editor",
            )
            picked = edited[edited["✔"] == True]["Keyword"].tolist()

            # ── NEW : apply selected to a book ──────────────────────────
            st.markdown("---")
            st.markdown(f"### 🎯 Appliquer à un livre ({len(picked)}/7 sélectionnés)")
            if len(picked) == 0:
                st.info("Cochez 1 à 7 keywords dans le tableau ci-dessus.")
            else:
                # Discover all draft books in ~/Desktop/KDP/
                from pathlib import Path as _P
                kdp_root = _P.home() / "Desktop" / "KDP"
                books = []
                if kdp_root.exists():
                    for d in kdp_root.iterdir():
                        if d.is_dir() and d.name not in ("published", "Tuto"):
                            listing_path = d / "listing.json"
                            if listing_path.exists():
                                books.append(d.name)
                books.sort()

                if not books:
                    st.warning("Aucun brouillon trouvé dans ~/Desktop/KDP/")
                else:
                    col_b1, col_b2 = st.columns([3, 1])
                    with col_b1:
                        target_slug = st.selectbox(
                            "Livre cible", books, key="kwp_target_slug",
                            help="Le listing.json sera mis à jour, ancien keywords sauvegardés dans _keywords_history",
                        )
                    with col_b2:
                        st.write("")  # spacer
                        st.write("")
                        apply_btn = st.button(
                            f"💾 Appliquer ({len(picked)})", key="kwp_apply",
                            disabled=(len(picked) > 7),
                            type="primary",
                        )
                    if len(picked) > 7:
                        st.error(f"⚠️ Vous avez coché {len(picked)} keywords — Amazon n'autorise que **7 max**. Décochez-en {len(picked) - 7}.")
                    if apply_btn and target_slug and 1 <= len(picked) <= 7:
                        try:
                            import json, datetime
                            listing_path = kdp_root / target_slug / "listing.json"
                            with open(listing_path) as f:
                                L = json.load(f)
                            old_kws = list(L.get("keywords", []))
                            # Backup old keywords inside listing itself (history)
                            history = L.get("_keywords_history", [])
                            history.append({
                                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                "old": old_kws,
                                "new": picked,
                                "seed": kw_seed,
                            })
                            L["_keywords_history"] = history[-10:]  # keep last 10
                            L["keywords"] = picked
                            with open(listing_path, "w") as f:
                                json.dump(L, f, indent=2, ensure_ascii=False)
                            # Also log to global history file for cross-book audit
                            try:
                                hist_path = _P.home() / "Desktop" / "Claude KDP Automation" / "output" / "learning" / "keywords_history.jsonl"
                                hist_path.parent.mkdir(parents=True, exist_ok=True)
                                with open(hist_path, "a") as hf:
                                    hf.write(json.dumps({
                                        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                        "slug": target_slug, "seed": kw_seed,
                                        "old": old_kws, "new": picked,
                                    }) + "\n")
                            except Exception:
                                pass
                            st.success(
                                f"✅ {len(picked)} keywords appliqués à **{target_slug}**. "
                                f"Anciens keywords sauvegardés dans `_keywords_history`."
                            )
                            st.code("\n".join([f"• {k}" for k in picked]))
                        except Exception as e:
                            st.error(f"Erreur lors de la sauvegarde : {e}")

            # ── NEW : history viewer ────────────────────────────────────
            with st.expander("📜 Historique des keywords appliqués", expanded=False):
                try:
                    from pathlib import Path as _P
                    hist_path = _P.home() / "Desktop" / "Claude KDP Automation" / "output" / "learning" / "keywords_history.jsonl"
                    if hist_path.exists():
                        import json
                        rows = []
                        with open(hist_path) as hf:
                            for line in hf:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    rows.append(json.loads(line))
                                except Exception:
                                    continue
                        if rows:
                            rows = rows[-20:][::-1]  # 20 last, newest first
                            for r in rows:
                                st.markdown(
                                    f"**{r.get('ts','?')[:16]}** · `{r.get('slug','?')}` · seed `{r.get('seed','?')}`"
                                )
                                st.caption("Anciens : " + ", ".join([f"`{k}`" for k in r.get("old", [])]) or "—")
                                st.caption("Nouveaux : " + ", ".join([f"`{k}`" for k in r.get("new", [])]))
                                st.markdown("---")
                        else:
                            st.caption("Aucun changement enregistré pour l'instant.")
                    else:
                        st.caption("Aucun historique — appliquez votre première sélection ci-dessus.")
                except Exception as e:
                    st.caption(f"Lecture historique impossible : {e}")

            st.caption(
                "📖 **Volume** = position dans autocomplete Amazon (40 = top, 1 = queue). "
                "**Demand ★** = indicateur visuel rapide. **Source** = comment ce keyword a été trouvé. "
                "Cliquez 🔎 plus haut pour ajouter la colonne **Amazon** (validation live conf 0-1)."
            )

    # ── Legacy profile + niche insights ───────────────────────────────────
    with st.expander("📚 Profil legacy (variants/themes/titre/publishers + niche insights)",
                     expanded=False):
        _render_legacy_intelligence()


def _render_legacy_intelligence():
    """Old intelligence content — kept available inside an expander."""
    counts  = feedback_counts(Config.LEARNING_DIR)
    profile = build_profile(Config.LEARNING_DIR)

    # ── Top stats row ──────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Produits notés",    counts.get("total", 0))
    c2.metric("👍 J'aime",          counts.get("up", 0))
    c3.metric("✅ Publiés",          counts.get("published", 0))
    c4.metric("👎 Rejetés",         counts.get("down", 0))

    if not profile.get("ready"):
        st.info(
            f"💡 Le bot a besoin d'au moins **3 produits notés** pour commencer à apprendre. "
            f"Actuellement : {counts.get('total', 0)} notation(s). "
            "Génère des produits et clique 👍/👎/✅ dans l'onglet Creation."
        )
    else:
        st.success(
            f"✅ Profil actif — le bot personnalise tes prochains batches automatiquement "
            f"({profile['n_positive']} positifs · {profile['n_negative']} négatifs)"
        )

    st.markdown("---")

    # ── Ton profil ──────────────────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("### 🎨 Top variants visuels")
        vs = profile.get("variant_scores", {})
        if vs:
            ranked = sorted(vs.items(), key=lambda kv: kv[1], reverse=True)
            for name, score in ranked[:5]:
                emoji = "✅" if score > 0 else ("➖" if score == 0 else "❌")
                st.markdown(f"{emoji} **{name}** — score `{score:+.1f}`")
        else:
            st.caption("Pas encore de données — note quelques produits.")

        st.markdown("### 📚 Top thèmes")
        ts = profile.get("theme_scores", {})
        if ts:
            ranked = sorted(ts.items(), key=lambda kv: kv[1], reverse=True)
            for name, score in ranked[:5]:
                emoji = "✅" if score > 0 else ("➖" if score == 0 else "❌")
                st.markdown(f"{emoji} **{name}** — score `{score:+.1f}`")
        else:
            st.caption("Pas encore de données.")

    with col_right:
        st.markdown("### 📝 Tes patterns de titre")
        avg_len = profile.get("title_avg_len", 0)
        if avg_len:
            st.metric("Longueur moyenne (titres validés)", f"{avg_len:.0f} chars")
        kws = profile.get("title_keywords", [])
        if kws:
            st.markdown("**Mots-clés récurrents dans tes wins :**")
            for word, count in kws[:8]:
                st.markdown(f"&nbsp;&nbsp;`{word}`  ·  *{count}×*", unsafe_allow_html=True)
        else:
            st.caption("Pas assez de titres validés pour extraire les patterns.")

        st.markdown("### 🏷️ Publishers préférés")
        pubs = profile.get("preferred_publishers", [])
        if pubs:
            for pub, count in pubs[:5]:
                st.markdown(f"&nbsp;&nbsp;**{pub}**  ·  *{count}× validé*", unsafe_allow_html=True)
        else:
            st.caption("Aucun publisher validé encore.")

    # ── Niche insights ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🔍 Insights par niche analysée")
    st.caption("Données extraites automatiquement après chaque scan La Crème")

    insights_path = Config.LEARNING_DIR / "niche_insights.json"
    if insights_path.exists():
        import json as _json
        with open(insights_path, "r") as f:
            all_insights = _json.load(f)
        if all_insights:
            n_niches = len(all_insights)
            st.caption(f"📊 **{n_niches} niche(s)** analysée(s) au total")

            # Top niches by analyzed_at desc
            ranked = sorted(all_insights.items(),
                            key=lambda kv: kv[1].get("analyzed_at", ""), reverse=True)
            for nkey, ins in ranked[:8]:
                ts   = ins.get("title_stats", {})
                ps   = ins.get("price_stats", {})
                cf   = ins.get("color_families", [])
                hexs = ins.get("color_hexes", [])

                label = f"🎯 **{ins.get('niche', nkey)}**  ·  {ins.get('n_competitors',0)} concurrents"
                with st.expander(label):
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        st.markdown(f"**Titre moyen :** {ts.get('avg_len', 0):.0f} chars")
                        st.markdown(f"**Avec 'colon:' :** {ts.get('with_colon_pct', 0):.0f}%")
                        if ts.get("top_words"):
                            words = [w for w, _ in ts["top_words"][:5]]
                            st.markdown(f"**Mots-clés concurrents :** {', '.join(words)}")
                    with cc2:
                        if ps.get("avg"):
                            st.markdown(f"**Prix moyen :** ${ps['avg']:.2f}")
                            st.markdown(f"**Range :** ${ps.get('min', 0):.2f} – ${ps.get('max', 0):.2f}")
                        st.markdown(f"**Reviews moy :** {ins.get('avg_reviews', 0):,}")

                    if hexs:
                        st.markdown("**Palette dominante (covers concurrents) :**")
                        # Render color swatches with CSS
                        swatch_html = "".join(
                            f'<span style="display:inline-block;width:28px;height:28px;'
                            f'background:{c};border:1px solid #DDD;margin-right:3px;'
                            f'border-radius:4px;" title="{c}"></span>' for c in hexs[:8]
                        )
                        st.markdown(swatch_html, unsafe_allow_html=True)
                        if cf:
                            fam_names = [f for f, _ in cf[:3]]
                            st.caption(f"Familles : {', '.join(fam_names)}")
        else:
            st.info("Aucun insight encore. Lance un scan **La Crème** — les concurrents seront analysés automatiquement.")
    else:
        st.info("Aucun insight encore. Lance un scan **La Crème** — les concurrents seront analysés automatiquement.")

    # ── 🔬 Deep competitor sample analysis ────────────────────────────────
    st.markdown("---")
    st.markdown("### 🔬 Analyse approfondie des concurrents")
    st.caption(
        "**Stratégie en 2 niveaux** : 1️⃣ Tente d'abord la preview Look Inside (Kindle "
        "Cloud Reader → URL sample → click product page). 2️⃣ Si bloqué par Amazon, "
        "fallback automatique : scraping de la page produit complète (description, "
        "editorial reviews, features) + analyse Claude texte. "
        "Le bot saura comment BATTRE les concurrents dans tous les cas."
    )

    # Pick a niche to deep-analyze (from existing scan history)
    available_niches_for_deep: list = []
    try:
        history = load_history(Config.HISTORY_DIR)
        for entry in history[:5]:
            fpath = entry.get("_file")
            if not fpath: continue
            scan = load_scan(fpath)
            if not isinstance(scan, dict): continue
            for n in scan.get("creme", []):
                kw = (n.get("keyword") or "").strip()
                if kw and kw not in available_niches_for_deep:
                    available_niches_for_deep.append(kw)
    except Exception:
        pass

    sample_insights_path = Config.LEARNING_DIR / "sample_insights.json"
    already_analyzed: set = set()
    if sample_insights_path.exists():
        import json as _json
        try:
            data = _json.loads(sample_insights_path.read_text())
            already_analyzed = set(data.keys())
        except Exception:
            pass

    if not available_niches_for_deep:
        st.info("Lance d'abord un scan **La Crème** — les niches gagnantes apparaîtront ici pour analyse approfondie.")
    else:
        st.caption(f"{len(available_niches_for_deep)} niche(s) disponibles dans tes scans  ·  "
                   f"{len(already_analyzed)} déjà analysée(s) en profondeur")

        chosen_niche = st.selectbox(
            "Niche à analyser en profondeur",
            options=available_niches_for_deep,
            format_func=lambda n: f"✅ {n}" if n.lower().strip() in already_analyzed else f"○ {n}",
            key="deep_niche_choice",
        )

        n_competitors = st.slider("Nombre de concurrents à analyser", 1, 5, 3, key="deep_n_comp")

        col_cost, col_btn = st.columns([2, 1])
        with col_cost:
            st.caption(
                f"💰 Coût estimé : ~${n_competitors * 0.04:.2f} (Vision) "
                f"ou ~${n_competitors * 0.005:.3f} (fallback texte)  ·  "
                f"⏱️ Durée : ~{n_competitors * 30}s"
            )
        with col_btn:
            is_already = chosen_niche and (chosen_niche.lower().strip() in already_analyzed)
            run_deep = st.button(
                "🔄 Re-analyser" if is_already else "🔬 Lancer l'analyse",
                key="run_deep_analysis",
                disabled=(not chosen_niche),
                type="primary",
                help=("Cette niche a déjà été analysée — relancer écrasera "
                      "les patterns existants avec une nouvelle analyse." if is_already
                      else "Première analyse de cette niche."),
            )

        if run_deep and chosen_niche:
            # If re-analyzing, wipe the cached entries for this niche's competitors
            if is_already:
                import json as _json
                cache_path = Config.LEARNING_DIR / "competitor_samples.json"
                niche_path = Config.LEARNING_DIR / "sample_insights.json"
                try:
                    if niche_path.exists():
                        nd = _json.loads(niche_path.read_text())
                        nd.pop(chosen_niche.lower().strip(), None)
                        niche_path.write_text(_json.dumps(nd, indent=2, ensure_ascii=False))
                    # Wipe specific ASINs (we don't track which were for this niche,
                    # so safest is to keep cache but the orchestrator will skip them
                    # if their analysis is None — easier: drop the whole cache)
                    if cache_path.exists():
                        cache_path.unlink()
                except Exception:
                    pass
            # Find the products for this niche in history
            products_for_niche = []
            try:
                for entry in history[:5]:
                    fpath = entry.get("_file")
                    if not fpath: continue
                    scan = load_scan(fpath)
                    if not isinstance(scan, dict): continue
                    for n in scan.get("creme", []):
                        if (n.get("keyword") or "").strip().lower() == chosen_niche.lower().strip():
                            products_for_niche = n.get("products", [])
                            break
                    if products_for_niche: break
            except Exception:
                pass

            if not products_for_niche:
                st.error("Impossible de retrouver les produits pour cette niche.")
            else:
                from modules.learning.sample_reader import analyze_competitor_samples
                progress_log = st.empty()
                logs = []

                def _on_status(m: str):
                    logs.append(m)
                    progress_log.code("\n".join(logs[-12:]), language=None)

                try:
                    with st.spinner(f"Analyse approfondie de '{chosen_niche}' en cours..."):
                        patterns = analyze_competitor_samples(
                            niche           = chosen_niche,
                            products        = products_for_niche,
                            anthropic_key   = Config.ANTHROPIC_API_KEY,
                            learning_dir    = Config.LEARNING_DIR,
                            max_competitors = n_competitors,
                            status_cb       = _on_status,
                        )
                    if patterns:
                        st.success(f"✅ Analyse terminée — {patterns.get('n_analyses', 0)} concurrent(s) décodés")
                        st.rerun()
                    else:
                        st.warning("Aucun pattern extrait. Look Inside indisponible ou bloqué pour ces produits.")
                except Exception as e:
                    st.error(f"Erreur : {e}")

    # ── Display deep sample insights if any ──────────────────────────────
    if sample_insights_path.exists():
        import json as _json
        try:
            sample_data = _json.loads(sample_insights_path.read_text())
        except Exception:
            sample_data = {}

        if sample_data:
            st.markdown("---")
            st.markdown("### 📚 Patterns décodés des concurrents")
            st.caption(
                "Source : Look Inside (Vision) si disponible, sinon scraping description (Texte). "
                "Le score qualité reflète la richesse de la description sale-page du concurrent."
            )
            for nkey, sinfo in sample_data.items():
                niche_name = sinfo.get("niche", nkey)
                pat = sinfo.get("patterns", {})
                with st.expander(f"🔬 **{niche_name}**  ·  {sinfo.get('n_competitors', 0)} concurrent(s) analysés"):
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        if pat.get("avg_lines_per_page"):
                            st.metric("Lignes/page (moy.)", pat["avg_lines_per_page"])
                        if pat.get("avg_quality_score") is not None:
                            st.metric("Qualité concurrents", f"{pat['avg_quality_score']}/10")
                        layouts = pat.get("common_layouts", [])
                        if layouts:
                            st.markdown(f"**Layout dominant :** `{layouts[0][0]}`")
                        intros = pat.get("common_intros", [])
                        if intros:
                            st.markdown(f"**Style intro :** `{intros[0][0]}`")
                    with cc2:
                        headers = pat.get("common_headers", [])
                        if headers:
                            st.markdown(f"**Header elements :** {', '.join(h for h,_ in headers[:4])}")
                        feats = pat.get("common_features", [])
                        if feats:
                            st.markdown(f"**Features récurrents :** {', '.join(f for f,_ in feats[:3])}")

                    topics = pat.get("common_topics", [])
                    if topics:
                        st.markdown(f"**🎯 Topics couverts :** {', '.join(t for t,_ in topics[:6])}")

                    gaps = pat.get("common_gaps", [])
                    if gaps:
                        st.markdown("**⚠️ Faiblesses détectées (à exploiter) :**")
                        for g, _ in gaps[:6]:
                            st.markdown(f"&nbsp;&nbsp;• {g}", unsafe_allow_html=True)
                        st.caption(
                            "_Ces faiblesses sont automatiquement injectées dans Claude (listing+content) "
                            "et gpt-image-2 (cover) lors de la prochaine génération sur cette niche._"
                        )
                    else:
                        st.info(
                            "✨ **Aucune faiblesse claire détectée** chez les concurrents — leurs descriptions "
                            "couvrent les features standards. Ta différenciation devra venir de l'**exécution** : "
                            "design intérieur plus riche, typo premium, palette unique, et plus de features "
                            "par page que les concurrents."
                        )

                    st.caption(f"Analysé le {sinfo.get('analyzed_at', '?')[:16]}")

    with st.expander("⚙️ Gestion des données d'apprentissage"):
        st.caption(f"Stockage : `{Config.LEARNING_DIR}`")
        if st.button("🗑️ Reset toutes les données d'apprentissage", type="secondary"):
            for fname in ["feedback.jsonl", "niche_insights.json",
                          "competitor_samples.json", "sample_insights.json"]:
                fpath = Config.LEARNING_DIR / fname
                if fpath.exists():
                    fpath.unlink()
            st.success("✅ Données effacées. Le bot recommencera à apprendre de zéro.")
            st.rerun()


def page_coming_soon(title, desc, features):
    st.markdown(f'<div class="kdp-header"><h1>{title}</h1><p>{desc}</p></div>',unsafe_allow_html=True)
    st.info("🔧 En développement — disponible prochainement.")
    for f in features: st.markdown(f"- {f}")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE CREATION — MODULE 2
# ══════════════════════════════════════════════════════════════════════════════

def _show_creation_results(results: list):
    """Displays batch creation results with download buttons."""
    st.markdown("---")
    st.markdown("### 3. Résultats")

    success_list = [r for r in results if r["status"] == "success"]
    failed_list  = [r for r in results if r["status"] == "error"]

    if success_list:
        st.success(f"✅ {len(success_list)} produit(s) généré(s) et sauvegardés dans `~/Desktop/KDP/`")
        # Finder shortcut
        import subprocess
        if st.button("📂 Ouvrir le dossier dans le Finder", key="open_finder_main"):
            subprocess.Popen(["open", str(Config.PRODUCTS_DIR)])
    if failed_list:
        st.error(f"❌ {len(failed_list)} échec(s)")

    for res in results:
        icon  = "✅" if res["status"] == "success" else "❌"
        label = f"{icon}  {res.get('title', res['niche'])}"

        with st.expander(label, expanded=(res["status"] == "success")):
            if res["status"] == "success":
                c1, c2, c3 = st.columns(3)
                c1.metric("Type",      res.get("product_type", "—").title())
                c2.metric("Pages",     str(res.get("page_count", "—")))
                c3.metric("Statut",    "KDP Ready")

                st.markdown(f"**Titre :** {res.get('title', '—')}")
                st.markdown(f"**Sous-titre :** {res.get('subtitle', '—')}")
                st.markdown(f"**Publisher :** {res.get('publisher', '—')}")
                # KDP browse categories (used by Module 3 Publishing)
                cats = res.get("categories", [])
                if cats:
                    st.markdown("**📁 Catégories KDP :**")
                    for c in cats:
                        path = c.get("path", "")
                        if c.get("primary"):
                            st.markdown(f"&nbsp;&nbsp;⭐ `{path}` _(primaire)_",
                                        unsafe_allow_html=True)
                        else:
                            st.markdown(f"&nbsp;&nbsp;· `{path}`",
                                        unsafe_allow_html=True)
                if res.get("style_variant"):
                    st.markdown(f"**Style variant :** `{res['style_variant']}`  (anti-duplicate)")

                kws = res.get("keywords", [])
                if kws:
                    st.markdown("**Keywords :** " + "  ·  ".join(f"`{k}`" for k in kws))

                # ── KDP AI-content disclosure (REQUIRED at publish time) ──────
                aid = res.get("ai_disclosure") or {}
                if aid:
                    st.warning(
                        "🤖 **Déclaration IA à faire sur KDP (obligatoire)** — "
                        "à l'étape « Did you use AI tools? » lors de la publication :\n\n"
                        f"- **Texte** : {aid.get('text', 'AI-generated')}\n"
                        f"- **Images** : {aid.get('images', 'AI-generated')}\n"
                        f"- **Traduction** : {aid.get('translation', 'None')}"
                    )

                # ── Estimated API cost for this book ──────────────────────────
                ec = res.get("est_cost") or {}
                if ec:
                    st.info(
                        f"💵 **Coût estimé : ~${ec.get('total_usd', '?')}** "
                        f"(Claude ~${ec.get('claude_usd', 0)} · "
                        f"{ec.get('n_images', 0)} images ~${ec.get('images_usd', 0)} · "
                        f"briefs ~${ec.get('briefs_usd', 0)}) — _estimation_"
                    )

                st.markdown("---")
                col_int, col_cov = st.columns(2)

                interior = res.get("interior_pdf")
                cover    = res.get("cover_pdf")
                niche_id = res["niche"][:25].replace(" ", "_")

                with col_int:
                    st.markdown("**📄 Intérieur PDF**")
                    if interior and Path(interior).exists():
                        size = Path(interior).stat().st_size / 1024
                        with open(interior, "rb") as f:
                            st.download_button(
                                "⬇️ interior.pdf",
                                data=f.read(),
                                file_name=f"{niche_id}_interior.pdf",
                                mime="application/pdf",
                                key=f"dl_int_{niche_id}",
                            )
                        st.caption(f"{size:.0f} KB  |  `{Path(interior).name}`")
                    else:
                        st.warning("Fichier non trouvé")

                with col_cov:
                    st.markdown("**🎨 Couverture PDF**")
                    if cover and Path(cover).exists():
                        size = Path(cover).stat().st_size / 1024
                        with open(cover, "rb") as f:
                            st.download_button(
                                "⬇️ cover.pdf",
                                data=f.read(),
                                file_name=f"{niche_id}_cover.pdf",
                                mime="application/pdf",
                                key=f"dl_cov_{niche_id}",
                            )
                        st.caption(f"{size:.0f} KB  |  `{Path(cover).name}`")
                    elif not Config.has_openai():
                        st.info("Clé OpenAI manquante — couverture ignorée")
                    else:
                        st.warning("Fichier non trouvé")

                # EPUB / Kindle (high-content only)
                epub_path = res.get("epub")
                if epub_path and Path(epub_path).exists():
                    size = Path(epub_path).stat().st_size / 1024
                    with open(epub_path, "rb") as f:
                        st.download_button(
                            "⬇️ book.epub (Kindle, images couleur)",
                            data=f.read(),
                            file_name=f"{niche_id}.epub",
                            mime="application/epub+zip",
                            key=f"dl_epub_{niche_id}",
                        )
                    st.caption(f"📱 EPUB {size:.0f} KB — prêt pour Kindle Direct Publishing")

                listing_path = res.get("listing_json")
                if listing_path and Path(listing_path).exists():
                    with open(listing_path, "rb") as f:
                        st.download_button(
                            "⬇️ listing.json",
                            data=f.read(),
                            file_name=f"{niche_id}_listing.json",
                            mime="application/json",
                            key=f"dl_lst_{niche_id}",
                        )

                product_dir = res.get("product_dir", "")
                st.caption(f"📁 `{product_dir}`")
                if product_dir and Path(product_dir).exists():
                    import subprocess
                    if st.button("📂 Ouvrir dans le Finder", key=f"finder_{niche_id}"):
                        subprocess.Popen(["open", product_dir])

                # ── 🧠 Feedback buttons + confidence + regenerate ─────────
                st.markdown("---")
                product_id = f"{res['niche']}__{res.get('completed_at','')[:19]}"
                current_rating = get_feedback_for_product(Config.LEARNING_DIR, product_id)

                # Detect theme of this product (used for cross-niche scoping)
                try:
                    from modules.creation.niche_themes import detect_theme
                    res_theme = detect_theme(res.get("niche", "")).get("name", "default")
                except Exception:
                    res_theme = None

                # Show confidence badge
                try:
                    from modules.learning.strategy import estimate_approval_probability
                    prob, n_obs = estimate_approval_probability(
                        Config.LEARNING_DIR,
                        variant_id   = res.get("style_variant", ""),
                        product_type = res.get("product_type"),
                        theme_name   = res_theme,
                    )
                    if n_obs > 0:
                        prob_pct = int(prob * 100)
                        bar_color = "#27AE60" if prob_pct >= 65 else ("#F39C12" if prob_pct >= 45 else "#E74C3C")
                        st.markdown(
                            f"<div style='display:inline-block;padding:4px 10px;border-radius:12px;"
                            f"background:{bar_color};color:white;font-size:12px;font-weight:600;'>"
                            f"🤖 Le bot prédit {prob_pct}% d'approbation  "
                            f"<span style='opacity:.8;'>(basé sur {n_obs} produit{'s' if n_obs > 1 else ''} similaire{'s' if n_obs > 1 else ''})</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                except Exception:
                    pass

                # ── 🎨 Regenerate cover-only / interior-only ──────────────
                product_dir_p = Path(res.get("product_dir") or "")
                regen_cols = st.columns([1.4, 1.4, 2])
                with regen_cols[0]:
                    if st.button("🎨 Régénérer cover", key=f"regen_cover_{niche_id}",
                                 help="Régénère uniquement la couverture (style libre, écrase l'ancienne)"):
                        st.session_state["regen_single"] = {
                            "kind": "cover",
                            "product_dir": str(product_dir_p),
                            "niche": res.get("niche", ""),
                        }
                        st.rerun()
                with regen_cols[1]:
                    if st.button("📄 Régénérer intérieur", key=f"regen_int_{niche_id}",
                                 help="Régénère uniquement l'intérieur (écrase l'ancien)"):
                        st.session_state["regen_single"] = {
                            "kind": "interior",
                            "product_dir": str(product_dir_p),
                            "niche": res.get("niche", ""),
                        }
                        st.rerun()
                with regen_cols[2]:
                    st.caption("_Écrase le fichier — pas de limite, varie à chaque clic_")

                st.markdown("---")
                fb_cols = st.columns([1, 1, 1, 1.2, 1.5])
                with fb_cols[0]:
                    label = "👍" + (" ✓" if current_rating == "up" else "")
                    if st.button(label, key=f"fb_up_{niche_id}",
                                 type="primary" if current_rating == "up" else "secondary"):
                        record_feedback(
                            Config.LEARNING_DIR,
                            product_id    = product_id,
                            niche         = res["niche"],
                            product_type  = res.get("product_type", ""),
                            rating        = "up",
                            variant_id    = res.get("style_variant"),
                            theme_name    = res_theme,
                            title         = res.get("title", ""),
                            keywords      = res.get("keywords", []),
                            publisher     = res.get("publisher", ""),
                            page_count    = res.get("page_count"),
                        )
                        st.toast("👍 Feedback enregistré — le bot l'utilisera au prochain batch", icon="🧠")
                        st.rerun()
                with fb_cols[1]:
                    label = "👎" + (" ✓" if current_rating == "down" else "")
                    if st.button(label, key=f"fb_down_{niche_id}",
                                 type="primary" if current_rating == "down" else "secondary"):
                        record_feedback(
                            Config.LEARNING_DIR,
                            product_id    = product_id,
                            niche         = res["niche"],
                            product_type  = res.get("product_type", ""),
                            rating        = "down",
                            variant_id    = res.get("style_variant"),
                            theme_name    = res_theme,
                            title         = res.get("title", ""),
                            keywords      = res.get("keywords", []),
                            publisher     = res.get("publisher", ""),
                            page_count    = res.get("page_count"),
                        )
                        st.toast("👎 Noté — le bot évitera ce style à l'avenir", icon="🧠")
                        st.rerun()
                with fb_cols[2]:
                    label = "✅" + (" ✓" if current_rating == "published" else "")
                    if st.button(label, key=f"fb_pub_{niche_id}",
                                 type="primary" if current_rating == "published" else "secondary"):
                        record_feedback(
                            Config.LEARNING_DIR,
                            product_id    = product_id,
                            niche         = res["niche"],
                            product_type  = res.get("product_type", ""),
                            rating        = "published",
                            variant_id    = res.get("style_variant"),
                            theme_name    = res_theme,
                            title         = res.get("title", ""),
                            keywords      = res.get("keywords", []),
                            publisher     = res.get("publisher", ""),
                            page_count    = res.get("page_count"),
                        )
                        st.toast("✅ Publié — signal le plus fort, le bot favorisera fortement ce style", icon="🚀")
                        st.rerun()
                with fb_cols[3]:
                    # 🔄 Regenerate with different variant (excludes the current one)
                    if current_rating == "down" or current_rating == "neutral":
                        if st.button("🔄 Autre style", key=f"regen_{niche_id}",
                                     help="Régénère ce produit avec un variant différent"):
                            st.session_state["regen_requested"] = {
                                "niche":     res["niche"],
                                "exclude":   [res.get("style_variant")],
                                "product_id_old": product_id,
                            }
                            st.session_state["cr_results"] = None
                            st.session_state["cr_log"]     = []
                            st.rerun()
                with fb_cols[4]:
                    if current_rating:
                        emoji = {"up":"👍","down":"👎","published":"✅"}.get(current_rating, "")
                        st.caption(f"{emoji} _Le bot apprend_")
                    else:
                        st.caption("_Note pour aider le bot_")

            else:
                st.error(f"Erreur : {res.get('error', 'Inconnue')}")

    st.markdown("---")
    if st.button("🔄 Nouvelle génération", type="secondary", key="cr_reset"):
        st.session_state["cr_results"] = None
        st.session_state["cr_log"]     = []
        st.rerun()


def _handle_single_regen():
    """Handle a session-state-flagged single-asset regeneration request."""
    req = st.session_state.get("regen_single")
    if not req:
        return
    st.session_state["regen_single"] = None   # clear so it runs once

    from modules.creation.batch import (
        regenerate_cover_only, regenerate_interior_only,
    )
    product_dir = Path(req["product_dir"])
    niche       = req.get("niche", "?")
    kind        = req["kind"]

    log_box  = st.empty()
    log_msgs = []
    def push(msg):
        log_msgs.append(msg)
        log_box.code("\n".join(log_msgs[-30:]), language=None)

    spin_label = (
        f"🎨 Régénération de la couverture pour « {niche} »…"
        if kind == "cover"
        else f"📄 Régénération de l'intérieur pour « {niche} »…"
    )
    with st.spinner(spin_label):
        try:
            if kind == "cover":
                out = regenerate_cover_only(
                    product_dir   = product_dir,
                    anthropic_key = Config.ANTHROPIC_API_KEY,
                    openai_key    = Config.OPENAI_API_KEY,
                    status_cb     = push,
                    learning_dir  = Config.LEARNING_DIR,
                    free_style    = True,
                )
            else:
                out = regenerate_interior_only(
                    product_dir   = product_dir,
                    anthropic_key = Config.ANTHROPIC_API_KEY,
                    openai_key    = Config.OPENAI_API_KEY,
                    status_cb     = push,
                    learning_dir  = Config.LEARNING_DIR,
                )
            st.success(f"✅ Fichier écrasé : `{Path(out).name}` (dans `{product_dir}`)")
        except Exception as e:
            st.error(f"❌ Échec régénération : {e}")


def _render_learning_insights_banner():
    """Show proactive bot insights at top of Creation tab."""
    try:
        from modules.learning.insights import generate_insights
        insights = generate_insights(Config.LEARNING_DIR)
    except Exception as e:
        logger.debug(f"Insights skipped: {e}")
        return
    if not insights:
        return
    with st.expander("🧠 Insights du bot — basés sur ton feedback", expanded=False):
        for i in insights:
            color = {"strong": "#27AE60", "medium": "#F39C12", "weak": "#888"}.get(i.severity, "#888")
            conf_pct = int(i.confidence * 100)
            st.markdown(
                f"<div style='border-left:4px solid {color}; padding:6px 10px; margin:4px 0; "
                f"background:#FAFAFA; border-radius:4px;'>"
                f"{i.icon} {i.message}"
                + (f"<br/><small style='color:#666'>→ {i.action}</small>" if i.action else "")
                + (f"<br/><small style='color:#999'>Confiance : {conf_pct}%</small>"
                   if i.confidence > 0 else "")
                + "</div>",
                unsafe_allow_html=True,
            )


def _render_predictor_banner(niches):
    """Show predictive quality for the niches the user is about to generate."""
    if not niches:
        return
    try:
        from modules.learning.predictor import predict, best_combo_for_niche
        from modules.creation.niche_themes import detect_theme
        rows = []
        for n in niches[:5]:
            theme = detect_theme(n).get("name") if detect_theme else None
            pred_score, conf, n_obs = predict(Config.LEARNING_DIR, theme=theme)
            color = "#27AE60" if pred_score >= 70 else ("#F39C12" if pred_score >= 55 else "#E74C3C")
            best = best_combo_for_niche(Config.LEARNING_DIR, theme=theme)
            best_str = f"→ try variant `{best[0]}` (predicted {best[1]:.0f})" if best else ""
            rows.append(
                f"<div style='border-left:4px solid {color};padding:6px 10px;margin:3px 0;"
                f"background:#FAFAFA;border-radius:4px;font-size:13px;'>"
                f"🎯 <b>{n[:50]}</b> · prédiction qualité : <b>{pred_score:.0f}/100</b> "
                f"(confiance {int(conf*100)}%, n={n_obs}) {best_str}</div>"
            )
        if rows:
            with st.expander("🔮 Prédictions qualité avant génération", expanded=False):
                st.markdown("".join(rows), unsafe_allow_html=True)
                st.caption(
                    "Basé sur tes feedback passés + true_quality multi-signaux. "
                    "Confiance <30% = bot peu sûr, à ajuster avec plus de feedback."
                )
    except Exception as e:
        logger.debug(f"Predictor banner skipped: {e}")


def page_creation():
    _render_learning_insights_banner()
    _handle_single_regen()
    st.markdown(
        '<div class="kdp-header">'
        '<h1>✏️ Module 2 — Création KDP</h1>'
        '<p>Génération automatique : listing SEO · intérieur PDF · couverture DALL-E 3 HD</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    content_mode_selector("creation")

    # ── API guard ────────────────────────────────────────────────────────────
    if not Config.has_anthropic():
        st.error("❌ Clé **Anthropic** manquante — requis pour générer les listings. Configure-la dans ⚙️ Settings.")
        return
    if not Config.has_openai():
        st.warning(
            "⚠️ Clé **OpenAI** manquante — la génération de couverture DALL-E sera ignorée. "
            "Configure-la dans ⚙️ Settings pour obtenir des couvertures professionnelles."
        )

    # ── Auto-cleanup of stale session-state from previous (legacy) runs ──
    if st.session_state.get("cr_running") and not batch_is_running():
        # The old inline flag is set but no thread is actually running
        st.session_state["cr_running"] = False

    # ── 🔄 If a batch is running in background → show live progress ──────
    bstate = get_batch_state()
    if bstate.get("running") or (bstate.get("results") is not None and not st.session_state.get("cr_results")):
        # If finished, pull results into session state for the result UI
        if not bstate.get("running") and bstate.get("results") is not None:
            st.session_state["cr_results"] = bstate["results"]
            st.session_state["cr_log"]     = list(bstate.get("log") or [])
            reset_batch_state()    # clear thread state — results are now in session
            st.rerun()

        # Still running → render live progress
        elapsed = elapsed_seconds()
        mm, ss  = divmod(int(elapsed), 60)
        n_niches = len(bstate.get("niches") or [])
        progress = bstate.get("progress", 0)

        st.markdown(
            f"<div style='background:linear-gradient(135deg,#3498DB 0%,#2980B9 100%);"
            f"padding:14px 18px;border-radius:8px;color:white;margin-bottom:14px;'>"
            f"<b>⚡ Génération en cours</b> · {n_niches} produit(s) · "
            f"<b>{progress}%</b> · ⏱️ {mm:02d}:{ss:02d}<br>"
            f"<span style='font-size:12px;opacity:.9;'>"
            f"✅ Tu peux naviguer librement vers Settings / Intelligence / Research — "
            f"le bot continue en arrière-plan. Reviens ici pour voir le résultat.</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        prog_bar = st.progress(min(progress, 100))
        st.code("\n".join((bstate.get("log") or [])[-18:]), language=None)

        if bstate.get("error"):
            st.error(f"⚠️ Erreur batch : {bstate['error']}")

        col_cancel, col_info = st.columns([1, 3])
        with col_cancel:
            if st.button("✕ Annuler le batch", type="secondary"):
                cancel_batch()
                reset_batch_state()
                st.warning("Batch annulé — l'état a été nettoyé.")
                st.rerun()
        with col_info:
            st.caption(
                "Le batch tourne dans un thread séparé. Cette page se rafraîchit "
                "automatiquement toutes les 3 secondes."
            )

        # Auto-refresh every 3 seconds
        import time as _time
        _time.sleep(3)
        st.rerun()
        return

    # ── 🧠 Learning state banner — shows what the bot knows about you ────
    try:
        _profile = build_profile(Config.LEARNING_DIR)
        _counts  = feedback_counts(Config.LEARNING_DIR)
        if _counts.get("total", 0) > 0:
            top_v = _profile.get("top_variant") or "—"
            top_t = _profile.get("top_theme")   or "—"
            n_pos = _profile.get("n_positive", 0)
            n_neg = _profile.get("n_negative", 0)
            ready_emoji = "✅" if _profile.get("ready") else "🧠"
            st.markdown(
                f"<div style='background:linear-gradient(135deg,#27AE60 0%,#229954 100%);"
                f"padding:10px 16px;border-radius:8px;color:white;margin-bottom:12px;font-size:13px;'>"
                f"{ready_emoji} <b>Apprentissage actif</b> — "
                f"{_counts['total']} produit(s) noté(s) ({n_pos} 👍 / {n_neg} 👎) · "
                f"variant favori : <b>{top_v}</b> · thème favori : <b>{top_t}</b> · "
                f"le bot l'appliquera automatiquement"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info(
                "🧠 **Le bot va apprendre de tes choix.** "
                "Génère quelques produits, clique 👍/👎/✅ sur chacun, "
                "et le bot adaptera automatiquement les futurs batches à tes préférences."
            )
    except Exception:
        pass

    # ── If already showing results ────────────────────────────────────────────
    if st.session_state.get("cr_results"):
        _show_creation_results(st.session_state["cr_results"])
        return

    # ── 🔄 Handle "Regenerate with another style" request ────────────────────
    regen = st.session_state.get("regen_requested")
    if regen:
        st.info(
            f"🔄 **Régénération demandée** pour `{regen['niche']}` "
            f"— variant `{regen['exclude'][0]}` exclu. Le bot va choisir un autre style."
        )
        if st.button("✅ Confirmer et relancer", type="primary", key="confirm_regen"):
            # Pre-populate the niche and trigger batch immediately
            st.session_state["_regen_active"] = regen
            st.session_state["regen_requested"] = None
            # Continue down to normal generation flow with this niche pre-selected
            st.session_state["_force_niche"] = regen["niche"]
            st.rerun()
        if st.button("❌ Annuler", key="cancel_regen"):
            st.session_state["regen_requested"] = None
            st.rerun()
        return

    # ── Step 1 — Niche selection ──────────────────────────────────────────────
    st.markdown("### 1. Sélectionne tes niches (1 à 5 max)")

    # ── Collect niches from all sources ──────────────────────────────────────
    # Source 1: live session state (creme + autopilot)
    available_niches: list = []   # list of (keyword, score, source_label)
    seen_keywords = set()

    def _add_niche(kw, score, source):
        kw = (kw or "").strip()
        if kw and kw not in seen_keywords:
            seen_keywords.add(kw)
            available_niches.append((kw, score, source))

    creme_data = st.session_state.get("creme_results") or {}
    if isinstance(creme_data, dict):
        for n in creme_data.get("creme", []):
            _add_niche(n.get("keyword"), n.get("overall", n.get("creme_score", 0)),
                       "👑 La Crème (session)")

    ap_data = st.session_state.get("ap_results") or {}
    if isinstance(ap_data, dict):
        # Autopilot results have a different structure: {"results": [...]} or direct list
        ap_list = ap_data.get("results", []) if isinstance(ap_data, dict) else ap_data
        if not ap_list and isinstance(ap_data, list):
            ap_list = ap_data
        for n in ap_list or []:
            scores = n.get("scores") or {}
            sc = scores.get("overall", n.get("overall", 0))
            _add_niche(n.get("keyword"), sc, "🤖 Autopilot (session)")

    # Source 2: fallback to history files on disk (if session is empty)
    if not available_niches:
        try:
            history = load_history(Config.HISTORY_DIR)
            # Take the most recent scan
            if history:
                latest_path = history[0].get("_file")
                if latest_path:
                    latest_scan = load_scan(latest_path)
                    if isinstance(latest_scan, dict):
                        stype = history[0].get("scan_type", "scan")
                        src   = f"💾 Dernier scan ({stype})"
                        # try both creme and autopilot shapes
                        for n in latest_scan.get("creme", []):
                            _add_niche(n.get("keyword"),
                                       n.get("overall", n.get("creme_score", 0)), src)
                        for n in latest_scan.get("results", []):
                            sc = (n.get("scores") or {}).get("overall", n.get("overall", 0))
                            _add_niche(n.get("keyword"), sc, src)
        except Exception as e:
            st.caption(f"(historique : {e})")

    # Keep only niches matching the active content mode (two separate flows).
    _cmode = st.session_state.get("content_mode", "high")
    available_niches = [
        t for t in available_niches if _niche_is_high(t[0]) == (_cmode == "high")
    ]
    # Sort by score descending, cap at 15 entries
    available_niches.sort(key=lambda t: t[1] or 0, reverse=True)
    available_niches = available_niches[:15]

    col_scan, col_manual = st.columns([1, 1])

    with col_scan:
        _cm_lbl = "📖 High-content" if _cmode == "high" else "📋 Low-content"
        st.markdown(f"##### Depuis tes scans — {_cm_lbl}")
        selected_from_scan = []
        if available_niches:
            st.caption(f"**{len(available_niches)} niche(s) disponibles** — triées par score, coche celles à créer")
            for kw, score, source in available_niches:
                label = f"{kw}  ·  *{score}/100*  ·  {source}"
                if st.checkbox(label, key=f"cr_cb_{kw}"):
                    selected_from_scan.append(kw)
        else:
            st.info(
                "Aucune niche trouvée. Lance d'abord un scan dans **🔍 Research** "
                "(La Crème ou Autopilot) — il sera automatiquement disponible ici."
            )

    with col_manual:
        st.markdown("##### Ou entre des niches manuellement")
        st.caption("1 niche par ligne — exemples ci-dessous")
        manual_text = st.text_area(
            "Niches",
            placeholder="villain era journal\ngratitude log book\nbirdwatching field notes\ncat mom planner",
            height=160,
            label_visibility="collapsed",
        )
        manual_niches = [l.strip() for l in manual_text.strip().splitlines() if l.strip()]

    # Merge, deduplicate, cap at 5
    all_niches = list(dict.fromkeys(selected_from_scan + manual_niches))[:5]

    # ── Auto-fill from regenerate request ─────────────────────────────────
    forced_niche = st.session_state.get("_force_niche")
    if forced_niche and forced_niche not in all_niches:
        all_niches = [forced_niche] + all_niches
        all_niches = all_niches[:5]
        st.info(f"🔄 Niche pré-sélectionnée pour régénération : **{forced_niche}**")

    if len(selected_from_scan) + len(manual_niches) > 5:
        st.warning("Maximum 5 niches à la fois — les 5 premières ont été conservées.")

    if all_niches:
        st.markdown("**Niches sélectionnées :**")
        for i, n in enumerate(all_niches, 1):
            st.markdown(f"&nbsp;&nbsp;{i}. `{n}`", unsafe_allow_html=True)

    # ── Step 2 — Launch ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 2. Lance la génération")

    # ── 💡 Pre-batch recommendations (from learning profile + niche insights) ─
    if all_niches:
        try:
            profile = build_profile(Config.LEARNING_DIR)
            reco_bits = []
            if profile.get("ready"):
                top_v = profile.get("top_variant")
                if top_v:
                    reco_bits.append(
                        f"🎨 Ton variant favori (basé sur {profile['n_positive']} approbations) : **`{top_v}`**"
                    )
                if profile.get("title_avg_len"):
                    reco_bits.append(
                        f"📝 Tes titres validés font ~**{profile['title_avg_len']:.0f} chars** en moyenne"
                    )

            # Niche-specific insights
            niche_bits = []
            for niche in all_niches[:3]:   # show recos for first 3 niches
                insights = get_insights(Config.LEARNING_DIR, niche)
                if insights:
                    ts = insights.get("title_stats", {})
                    cf = insights.get("color_families", [])
                    info = []
                    if ts.get("avg_len"):
                        info.append(f"titres ~{ts['avg_len']:.0f}c")
                    if cf:
                        info.append(f"palette {','.join(f for f,_ in cf[:2])}")
                    if info:
                        niche_bits.append(f"  · **{niche[:35]}** → {' · '.join(info)}")

            if reco_bits or niche_bits:
                with st.expander("💡 Recommandations basées sur ton apprentissage", expanded=False):
                    for b in reco_bits:
                        st.markdown(b)
                    if niche_bits:
                        st.markdown("**Insights pour les niches sélectionnées :**")
                        for b in niche_bits:
                            st.markdown(b)
                    st.caption("Ces signaux sont automatiquement injectés dans les prompts Claude + gpt-image-2.")
        except Exception as e:
            pass  # silently skip if learning data is incomplete

    col_btn, col_info = st.columns([1, 2])
    with col_btn:
        go = st.button(
            f"🚀 Générer {len(all_niches)} produit(s)" if all_niches else "🚀 Générer",
            disabled=(not all_niches or st.session_state.get("cr_running", False)),
            type="primary",
        )
    with col_info:
        if not all_niches:
            st.warning("Sélectionne ou entre au moins 1 niche.")
        else:
            est = len(all_niches) * 3
            st.info(
                f"Durée estimée : **~{est} min** pour {len(all_niches)} produit(s)  |  "
                f"Listing Claude → Contenu Claude → PDF interior → Couverture gpt-image-2"
            )
            st.caption(
                f"📁 Output → `~/Desktop/KDP/`  ·  "
                f"🎨 Rotation auto de **8 variants stylistiques** (anti-duplicate KDP)"
            )

    # ── 📏 Format KDP (trim size + paper type + page count) ─────────────
    st.markdown("---")
    from modules.creation.kdp_specs import TRIM_SIZES, SPINE_PER_PAGE
    with st.expander("📏 Format & papier KDP (taille, papier, pages)", expanded=False):
        sorted_trims = sorted(TRIM_SIZES, key=lambda t: -t.popularity)
        trim_labels = [f"{t.label} — {t.use_case}" for t in sorted_trims]
        # Widget keys must be DIFFERENT from session_state storage keys
        # otherwise Streamlit raises StreamlitAPIException.
        trim_idx = st.selectbox(
            "📐 Taille du livre (trim size)",
            options=list(range(len(sorted_trims))),
            format_func=lambda i: trim_labels[i],
            index=0,
            help="Toutes les tailles KDP officielles. 6×9 = standard low-content.",
            key="cr_trim_idx_widget",
        )
        chosen_trim = sorted_trims[trim_idx]
        paper_type = st.radio(
            "📄 Type de papier",
            options=["white", "cream", "groundwood", "color"],
            format_func=lambda p: {
                "white":      "Blanc (B&W) — défaut, spine 0.002252\"/page",
                "cream":      "Crème (B&W) — premium romans, spine 0.0025\"/page",
                "groundwood": "Groundwood éco (B&W) — moins cher, spine 0.002252\"/page",
                "color":      "Couleur — workbooks, spine 0.002347\"/page",
            }[p],
            index=0,
            key="cr_paper_type_widget",
        )
        page_count = st.number_input(
            "📖 Nombre de pages cible (interior + cover s'ajusteront automatiquement)",
            min_value=24, max_value=828, value=120, step=2,
            help="KDP : minimum 24 pages, maximum 828. Le cover (largeur spine) "
                 "se calcule automatiquement. Si le PDF généré dépasse, le bot "
                 "recalibre le cover sur le vrai count avant export.",
            key="cr_page_count_widget",
        )
        spine = page_count * SPINE_PER_PAGE.get(paper_type, 0.002252)
        bleed = 0.125
        cover_w = bleed + chosen_trim.width_in + spine + chosen_trim.width_in + bleed
        cover_h = chosen_trim.height_in + bleed * 2
        st.caption(
            f"📐 Trim **{chosen_trim.width_in}×{chosen_trim.height_in}in** · "
            f"{page_count} pages · papier **{paper_type}** · "
            f"spine **{spine:.4f}in** · cover total **{cover_w:.3f}×{cover_h:.3f}in**"
        )
        # Store on DIFFERENT keys (not widget keys) for batch consumption
        st.session_state["_format_trim_w"]      = chosen_trim.width_in
        st.session_state["_format_trim_h"]      = chosen_trim.height_in
        st.session_state["_format_paper_type"]  = paper_type
        st.session_state["_format_page_count"]  = int(page_count)

    with st.expander("🖼️ Options d'illustrations IA pour l'intérieur", expanded=False):
        use_interior_images = st.checkbox(
            "✅ Inclure des illustrations IA dans l'intérieur (hero image + 6 icônes par niche)",
            value=True,
            help="Génère 7 images B&W via gpt-image-2 : 1 hero pour la welcome page + "
                 "6 icônes thématiques rotatives sur les section banners. Coût : ~$0.08 par niche "
                 "(une seule fois, ensuite cache → $0). Désactive pour économiser.",
        )
        st.caption(
            "Les images sont en **noir & blanc** pour rester compatibles "
            "avec l'impression KDP paperback standard (l'intérieur couleur coûte ~3× plus cher). "
            "Cache permanent dans `output/learning/interior_images/{niche}/`."
        )

    with st.expander("🧩 Options puzzle books (mazes / sudoku / etc.)", expanded=False):
        st.caption(
            "Si la niche détectée est un type **puzzle** (mazes, sudoku, word search, "
            "cryptogram, logic grid, nonogram, kakuro, kenken, dot-to-dot) ou "
            "**activity_book** (combo de plusieurs types), ces options s'appliquent. "
            "Sinon, ignorées."
        )
        pc1, pc2, pc3 = st.columns([2, 2, 2])
        with pc1:
            puzzle_type_override = st.selectbox(
                "Forcer le type de puzzle",
                options=["auto (détection niche)", "mazes", "wordsearch", "sudoku",
                         "cryptogram", "logic_grid", "nonogram", "kakuro", "kenken",
                         "dot_to_dot", "activity_book (combo)"],
                index=0,
                help="'auto' = détection depuis le keyword. Sinon force le type spécifié.",
            )
        with pc2:
            puzzle_difficulty = st.selectbox(
                "Difficulté",
                options=["easy", "medium", "hard", "expert",
                         "gradient (easy→expert)", "warmup (easy puis base)",
                         "mixed (random)"],
                index=4,    # gradient = pro KDP bestseller pattern
                help="Pour les pros : 'gradient' est le pattern bestseller "
                     "(débute facile, finit ultra-difficile). "
                     "'warmup' = ~20% facile en intro, puis base, puis pic. "
                     "Pure 'easy/medium/hard/expert' = toutes les pages au "
                     "même niveau (peut paraître monotone).",
            )
            # Normalise le label en clé interne attendue par normalize_difficulties
            _diff_map = {
                "gradient (easy→expert)": "gradient",
                "warmup (easy puis base)": "warmup",
                "mixed (random)":          "mixed",
            }
            puzzle_difficulty = _diff_map.get(puzzle_difficulty, puzzle_difficulty)
        with pc3:
            puzzle_volume = st.number_input(
                "Volume #",
                min_value=1, max_value=99, value=1, step=1,
                help="Change pour générer un Vol 2, Vol 3, etc. avec des puzzles "
                     "complètement différents (même niche, même difficulté).",
            )

    with st.expander("✨ Options A+ Content", expanded=False):
        generate_aplus = st.checkbox(
            "Générer 5 modules A+ Content par livre (copy-paste vers KDP)",
            value=True,
            help="A+ Content = +~12% de conversion en moyenne (benchmark KDP 2026). "
                 "Coût : ~$0.01 + 3s par livre (Claude Sonnet). "
                 "Décoche pour économiser sur les batchs volumineux.",
        )
        st.caption(
            "Les modules sont sauvegardés dans `listing.json` et affichés dans "
            "**Publishing** → expander ✨ A+ Content (KDP A+ se publie manuellement "
            "via Bookshelf → A+ Content Manager après publication du livre)."
        )

    # ── High-content extras : images par item + EPUB ─────────────────────────
    hc_item_images = False
    make_epub = False
    if st.session_state.get("content_mode", "high") == "high":
        with st.expander("📖 Options High-content (images par item + EPUB)", expanded=True):
            hc_item_images = st.checkbox(
                "🖼️ Une image couleur par item (photo de plat / dessin enfant / illustration guide)",
                value=True,
                help="Génère UNE image adaptée à la niche par recette / section / chapitre "
                     "(gpt-image, couleur). Coût ≈ 0,07 $/image (~2-5 $/livre selon la taille). "
                     "Mise en cache : régénérer le même livre = 0 $. En PDF papier les images "
                     "passent en niveaux de gris (impression économique), en EPUB elles restent "
                     "en couleur. Décoche pour économiser sur un test rapide.",
            )
            make_epub = st.checkbox(
                "📱 Générer aussi l'EPUB / Kindle (images en couleur)",
                value=True,
                help="Crée un fichier book.epub reflowable avec le même contenu + les images "
                     "en COULEUR (gratuit sur Kindle). Idéal pour la version numérique.",
            )

    # ── Batch execution — START a background thread ──────────────────────────
    if go and all_niches:
        # If this is a regen, pull the excluded variants
        regen_active = st.session_state.get("_regen_active") or {}
        excluded_variants = regen_active.get("exclude") or None

        # Persist the chosen trim/paper/pages to a session-level config dict
        # the batch will read and inject into each listing.
        # Resolve puzzle override (only attach when user picked something specific)
        pz_override = None
        pz_label = puzzle_type_override
        if pz_label and not pz_label.startswith("auto"):
            if "activity_book" in pz_label:
                pz_override = {"product_type_force": "activity_book"}
            else:
                pz_override = {"product_type_force": "puzzle", "puzzle_type": pz_label}

        st.session_state["_batch_format_override"] = {
            "trim_size_w": st.session_state.get("_format_trim_w", 6.0),
            "trim_size_h": st.session_state.get("_format_trim_h", 9.0),
            "paper_type":  st.session_state.get("_format_paper_type", "white"),
            "page_count":  st.session_state.get("_format_page_count", 120),
            "difficulty":  puzzle_difficulty,
            "volume":      int(puzzle_volume),
            **(pz_override or {}),
        }
        started = start_batch_in_background(
            niches              = all_niches,
            anthropic_key       = Config.ANTHROPIC_API_KEY,
            openai_key          = Config.OPENAI_API_KEY,
            output_dir          = Config.PRODUCTS_DIR,
            learning_dir        = Config.LEARNING_DIR,
            excluded_variants   = excluded_variants,
            use_interior_images = use_interior_images,
            format_override     = st.session_state["_batch_format_override"],
            generate_aplus      = generate_aplus,
            highcontent_item_images = hc_item_images,
            make_epub           = make_epub,
        )
        if started:
            st.session_state["_regen_active"] = None
            st.session_state["_force_niche"]  = None
            st.rerun()
        else:
            st.error("⚠️ Un batch est déjà en cours.")


def page_publishing():
    """Module 3 — KDP Publishing (Option A: draft mode, human-in-the-loop)."""
    import importlib, sys

    # Step 1: import all modules used by Publishing actions.
    import modules.creation.kdp_specs       as _kdp_specs
    import modules.creation.cover_generator as _cover_gen
    import modules.creation.batch           as _creation_batch
    import modules.publishing.scanner       as _scanner
    import modules.publishing.session       as _session
    import modules.publishing.uploader      as _uploader
    import modules.publishing.publish_runner as _pub_runner
    import modules.publishing.categories_helper as _cats_helper
    import modules.quality.visual           as _visual
    import modules.quality.validator        as _validator
    import modules.quality.auto_fix         as _auto_fix
    import modules.quality.auto_improve     as _auto_improve

    # Step 2: reload modules ONLY if their source file changed since last reload.
    # This is the BIG perf win — previously we reloaded 12 modules on every
    # page render which re-executed all their top-level code each time.
    _MTIME_CACHE = st.session_state.setdefault("_reload_mtime_cache", {})
    for _mod in (
        _kdp_specs, _cover_gen, _creation_batch,
        _visual, _scanner, _session, _uploader,
        _cats_helper, _validator, _auto_fix, _auto_improve,
    ):
        try:
            f = getattr(_mod, "__file__", None)
            if not f:
                continue
            cur_mtime = Path(f).stat().st_mtime
            if _MTIME_CACHE.get(_mod.__name__) == cur_mtime:
                continue   # unchanged, skip reload
            importlib.reload(_mod)
            _MTIME_CACHE[_mod.__name__] = cur_mtime
        except Exception as _e:
            logger.warning(f"Reload {_mod.__name__} failed: {_e}")

    # Step 3: rebind to the freshly-reloaded versions
    scan_products       = _scanner.scan_products
    mark_as_published   = _scanner.mark_as_published
    revert_published    = _scanner.revert_published
    summary             = _scanner.summary
    ensure_firefox_installed = _session.ensure_firefox_installed
    session_exists      = _session.session_exists
    open_login_flow     = _session.open_login_flow
    clear_session       = _session.clear_session
    install_firefox_browser  = _session.install_firefox_browser
    publish_to_kdp_draft = _uploader.publish_to_kdp_draft
    auto_fix_product     = _auto_fix.auto_fix_product

    # ── Cached validator (mtime-keyed, TTL 5 min) ───────────────────────
    # Avoids re-validating every product on every Streamlit rerun.
    @st.cache_data(ttl=300, show_spinner=False)
    def _cached_validate(folder_str: str, listing_mtime: float,
                         interior_mtime: float, cover_mtime: float):
        # mtime args are part of the cache key — when ANY file changes,
        # the cache is automatically invalidated.
        return _validator.validate_product(Path(folder_str))

    def validate_product(folder):
        """Wrapper that auto-keys on file mtimes for cache invalidation."""
        folder = Path(folder)
        def _mt(p):
            try: return p.stat().st_mtime
            except: return 0
        return _cached_validate(
            str(folder),
            _mt(folder / "listing.json"),
            _mt(folder / "interior.pdf"),
            _mt(folder / "cover.pdf"),
        )
    # Bind directly to module functions (NOT names) so the latest version
    # of publish_runner is always called. Since we never reload publish_runner,
    # _STATE persists across reruns.
    pub_start    = _pub_runner.start_publish
    pub_running  = _pub_runner.is_running
    pub_state    = _pub_runner.get_state
    pub_signal   = _pub_runner.signal_continue
    pub_reset    = _pub_runner.reset_state

    # Trace import path so we KNOW whether the new version is loaded
    logger.info(
        f"page_publishing: publish_runner module id={id(_pub_runner)} "
        f"state_keys={list(_pub_runner._STATE.keys())} "
        f"running={_pub_runner._STATE.get('running')}"
    )

    _show_global_batch_banner()
    st.markdown(
        '<div class="kdp-header"><h1>📤 Module 3 — Publication KDP</h1>'
        '<p>Option A : brouillon auto + validation humaine sur KDP</p></div>',
        unsafe_allow_html=True,
    )

    # ── 🚨 ALWAYS-VISIBLE STATUS STRIP (debug + status) ─────────────────
    # This is rendered on EVERY page load so the user knows the bot's state
    # at a glance — fixes the "I don't see what the bot is doing" complaint.
    state_top = pub_state()
    has_active_session = bool(st.session_state.get("pub_active_slug"))
    is_running_now    = pub_running()
    has_result        = bool(state_top.get("result"))
    has_error         = bool(state_top.get("error"))

    # Tiny status badge ALWAYS shown
    if is_running_now:
        status_text, status_color, status_icon = "BOT EN COURS", "#27AE60", "🔄"
    elif has_error:
        status_text, status_color, status_icon = "ERREUR — voir détails", "#E74C3C", "❌"
    elif has_result:
        status_text, status_color, status_icon = "PUBLICATION TERMINÉE", "#3498DB", "✅"
    elif has_active_session:
        status_text, status_color, status_icon = "DÉMARRAGE…", "#F39C12", "⏳"
    else:
        status_text, status_color, status_icon = "PRÊT", "#95A5A6", "💤"
    st.markdown(
        f"<div style='background:{status_color};color:white;padding:8px 14px;"
        f"border-radius:6px;margin:4px 0;font-size:13px;font-weight:600;"
        f"display:inline-block;'>"
        f"{status_icon} Statut bot : {status_text}"
        f"</div>",
        unsafe_allow_html=True,
    )
    with st.expander("🐛 Debug interne (clique pour voir l'état complet du bot)",
                     expanded=False):
        st.json({
            "is_running":           is_running_now,
            "active_slug":          st.session_state.get("pub_active_slug"),
            "current_step":         state_top.get("current_step"),
            "log_lines":            len(state_top.get("log", [])),
            "has_result":           has_result,
            "has_error":            has_error,
            "started_at":           state_top.get("started_at"),
            "finished_at":          state_top.get("finished_at"),
            "result":               state_top.get("result"),
            "error":                state_top.get("error"),
        })
        st.caption(
            "Si tu cliques 'Pousser vers KDP' et que `is_running` reste False + "
            "`log_lines = 0` : redémarre Streamlit complètement (Ctrl+C puis "
            "`streamlit run app.py`)."
        )

    # Full panel rendered when something is happening
    if is_running_now or has_result or has_error or has_active_session:
        active_slug = st.session_state.get("pub_active_slug", "?")
        is_run = pub_running()
        banner_color = "#27AE60" if is_run else ("#E74C3C" if state_top.get("error") else "#3498DB")
        banner_icon  = "🔄" if is_run else ("❌" if state_top.get("error") else "✅")
        banner_text  = (
            f"Publication EN COURS : <code>{active_slug}</code>"
            if is_run else
            ("Erreur — vois ci-dessous" if state_top.get("error") else
             "Publication terminée — clique pour marquer publié")
        )
        st.markdown(
            f"<div style='background:{banner_color};color:white;padding:14px 18px;"
            f"border-radius:10px;margin:8px 0;font-size:15px;font-weight:600;'>"
            f"{banner_icon} {banner_text}</div>",
            unsafe_allow_html=True,
        )

        step = state_top.get("current_step") or "—"
        elapsed = ""
        if state_top.get("started_at"):
            import time as _t
            elapsed = f"  ·  {int(_t.time() - state_top['started_at'])}s écoulées"

        ctrl_cols = st.columns([2, 2, 1])
        with ctrl_cols[0]:
            st.markdown(f"**Étape active :** `{step}`{elapsed}")
        with ctrl_cols[1]:
            # ALWAYS show the "Fait" button when there's an active session,
            # even if pub_running() momentarily returns False during a state read race.
            if is_run or st.session_state.get("pub_active_slug"):
                if st.button(
                    "✅ Fait — continue maintenant",
                    type="primary", key="pub_continue_top",
                    use_container_width=True,
                    help="Quand tu as fini une tâche manuelle (login, catégories, "
                         "Save and Continue...), clique pour débloquer le bot.",
                ):
                    pub_signal(Config.LEARNING_DIR)
                    st.toast("⚡ Signal envoyé — bot reprend dans 2 sec", icon="⚡")
                    st.rerun()
        with ctrl_cols[2]:
            if st.button("🗑️ Effacer état", key="pub_clear_top",
                         use_container_width=True,
                         help="Reset complet : à utiliser si le bot semble figé."):
                pub_reset()
                st.session_state.pop("pub_active_slug", None)
                st.rerun()

        # Live log box — scrollable
        log_lines = state_top.get("log", [])
        st.code(
            "\n".join(log_lines[-30:]) if log_lines else "(en attente du premier message…)",
            language=None,
        )

        # Result panel after completion
        result = state_top.get("result")
        if result and not is_run:
            if result.get("success"):
                st.success(
                    f"✅ Brouillon sauvegardé — étape : `{result['step_reached']}`. "
                    f"URL : {result.get('draft_url', '?')}"
                )
                if st.button("✅ J'ai cliqué Publish sur KDP — marquer comme publié",
                             type="primary", key="pub_mark_pub_top"):
                    products_now = scan_products(Path.home() / "Desktop" / "KDP")
                    target = next((p for p in products_now if p.slug == active_slug), None)
                    if target:
                        mark_as_published(target, Path.home() / "Desktop" / "KDP",
                                          kdp_url=result.get("draft_url", ""))
                        pub_reset()
                        st.session_state.pop("pub_active_slug", None)
                        st.rerun()
            else:
                st.error(f"❌ Bloqué à `{result.get('step_reached','?')}` — {result.get('error_message','')}")
                snap = result.get("screenshot_path")
                if snap and Path(snap).exists():
                    st.image(snap, caption=f"Debug : {Path(snap).name}")

        # Auto-refresh while running. 4 seconds is the sweet spot:
        # fast enough to see progress, slow enough that the page isn't
        # constantly rebuilding (which makes the WHOLE app sluggish).
        if is_run:
            import time as _t
            _t.sleep(4)
            st.rerun()

        st.markdown("---")

    # ── Pre-flight: Firefox + session ─────────────────────────────────────
    fx_ok, fx_msg = ensure_firefox_installed()
    sess_ok = session_exists(Config.LEARNING_DIR)
    c1, c2 = st.columns(2)
    with c1:
        if fx_ok:
            st.success("✅ Firefox prêt")
            st.caption(fx_msg)
        else:
            st.error("❌ Firefox manquant pour Playwright")
            st.caption(fx_msg)
            if st.button("📥 Installer Firefox maintenant (~80 MB, ~1 min)",
                         type="primary", key="kdp_install_fx"):
                install_box = st.empty()
                install_lines = []
                def log_install(msg):
                    install_lines.append(msg)
                    install_box.code("\n".join(install_lines[-30:]), language=None)
                with st.spinner("Installation en cours…"):
                    ok, output = install_firefox_browser(status_cb=log_install)
                if ok:
                    st.success("✅ Firefox installé — recharge la page (Cmd+R)")
                else:
                    st.error(f"Échec installation : {output[-500:]}")
            st.caption(
                "Alternative — lance ceci dans ton terminal puis recharge :\n"
                "`source venv/bin/activate && playwright install firefox`"
            )
    with c2:
        if not fx_ok:
            st.info("Installe Firefox d'abord (colonne de gauche) avant de te logger à KDP.")
        elif sess_ok:
            st.success("✅ Session KDP sauvegardée")
            if st.button("🗑️ Effacer la session (forcer relogin)", key="kdp_clear_sess"):
                if clear_session(Config.LEARNING_DIR):
                    st.success("Session effacée")
                    st.rerun()
        else:
            st.warning("⚠️ Pas de session KDP — login requis avant 1ère publication")
            if st.button("🔐 Login KDP maintenant (ouvre Firefox)",
                         type="primary", key="kdp_login_btn"):
                with st.spinner("Firefox s'ouvre — connecte-toi à KDP (2FA inclus). Tu as 10 min."):
                    try:
                        captured = open_login_flow(Config.LEARNING_DIR, timeout_minutes=10)
                        if captured:
                            st.success("✅ Session capturée — tu peux publier maintenant")
                            st.rerun()
                        else:
                            st.error("❌ Login non détecté (timeout). Réessaie.")
                    except Exception as e:
                        st.error(f"❌ Erreur Firefox : {e}")

    if not fx_ok:
        st.stop()

    st.markdown("---")

    # ── Browser mode toggle ───────────────────────────────────────────────
    headless = st.checkbox(
        "🕶️ Mode invisible (headless) — plus rapide, pas de fenêtre visible",
        value=False,
        help="Décoche pour voir le bot travailler en temps réel (recommandé en début).",
    )

    # ── Scan products ─────────────────────────────────────────────────────
    kdp_root = Path.home() / "Desktop" / "KDP"
    products = scan_products(kdp_root)
    summ = summary(products)

    cols = st.columns(4)
    cols[0].metric("Total",      summ["total"])
    cols[1].metric("Drafts",     summ["draft"],     help="Prêts à pousser vers KDP")
    cols[2].metric("Publiés",    summ["published"], help="Déjà sur KDP")
    cols[3].metric("Incomplets", summ["incomplete"], help="Manquent interior/cover/listing")

    if summ["total"] == 0:
        st.info(f"Aucun produit dans `{kdp_root}`. Génère d'abord des livres dans l'onglet Création.")
        return

    # ── 📊 Daily Report (G) ───────────────────────────────────────────
    with st.expander("📊 Daily report — bilan d'activité", expanded=False):
        c_dr1, c_dr2 = st.columns([2, 1])
        with c_dr1:
            st.caption("Recap de l'activité des dernières 24h : créations, publications, scores qualité, insights bot.")
        with c_dr2:
            if st.button("📈 Générer le rapport maintenant", key="gen_daily_report"):
                from modules.quality.daily_report import generate_daily_report
                with st.spinner("Génération…"):
                    rep = generate_daily_report(kdp_root, Config.LEARNING_DIR)
                st.session_state["daily_report_data"] = rep
                st.rerun()
        if st.session_state.get("daily_report_data"):
            rep = st.session_state["daily_report_data"]
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Actifs 24h", rep["n_recent"])
            r2.metric("Drafts", rep["n_drafts"])
            r3.metric("Publiés", rep["n_published"])
            r4.metric("Score moyen", f"{rep['avg_quality']}/100")
            if rep.get("markdown_path") and Path(rep["markdown_path"]).exists():
                st.caption(f"💾 Sauvegardé : `{rep['markdown_path']}`")
                if st.button("📂 Ouvrir le rapport", key="open_report"):
                    import subprocess
                    subprocess.Popen(["open", rep["markdown_path"]])

    # ── 🎯 Batch quality dashboard ─────────────────────────────────────
    with st.expander("🎯 Tableau de bord qualité — vue d'ensemble", expanded=False):
        scores = []
        for p in products:
            if p.status == "draft":
                try:
                    r = validate_product(p.folder)
                    scores.append((p.slug, r))
                except Exception:
                    continue
        if scores:
            scores.sort(key=lambda x: x[1].score)
            n_ready  = sum(1 for _, r in scores if r.score >= 90)
            n_warn   = sum(1 for _, r in scores if 70 <= r.score < 90)
            n_block  = sum(1 for _, r in scores if r.score < 70)
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("✅ Prêts (≥90)", n_ready)
            sc2.metric("⚠️ À polir (70-89)", n_warn)
            sc3.metric("❌ Bloqueurs (<70)", n_block)

            st.markdown("**Détail par livre :**")
            for slug, r in scores:
                icon = "🟢" if r.score >= 90 else ("🟡" if r.score >= 70 else "🔴")
                fix_tag = " 🔧" if r.auto_fixable else ""
                st.caption(f"{icon} **{r.score:3d}/100**  ·  `{slug}`{fix_tag}  ·  _{r.summary}_")

            # One-click: fix all auto-fixable issues across all drafts
            all_fixable = [(slug, sorted({i.fix_strategy for i in r.auto_fixable}))
                           for slug, r in scores if r.auto_fixable]
            if all_fixable:
                if st.button(
                    f"🔧🔧 Auto-fix EVERY draft ({len(all_fixable)} books)",
                    type="primary",
                    help="Applique toutes les corrections auto-fixables sur tous les livres "
                         "en draft. Peut prendre 1-2 min."
                ):
                    st.session_state["autofix_batch"] = all_fixable
                    st.rerun()

    # ── List drafts (publishable) ─────────────────────────────────────────
    drafts = [p for p in products if p.status == "draft"]
    if drafts:
        st.markdown("### 📋 Livres prêts à publier")
        for prod in drafts:
            with st.expander(f"📕 **{prod.title[:65]}**  ·  `{prod.slug}`",
                             expanded=False):
                # ── 🖼️ Cover thumbnail + meta ──────────────────────────
                from modules.quality.visual import thumbnail_for_cover
                thumb_cache = Config.LEARNING_DIR / "cover_thumbs"
                thumb_path = None
                try:
                    if prod.cover_pdf and prod.cover_pdf.exists():
                        thumb_path = thumbnail_for_cover(
                            prod.cover_pdf, thumb_cache, width_px=180,
                        )
                except Exception:
                    pass

                tc1, tc2, tc3 = st.columns([1, 2, 1])
                with tc1:
                    if thumb_path and Path(thumb_path).exists():
                        st.image(str(thumb_path), caption="Cover preview")
                    else:
                        st.caption("(no preview)")
                with tc2:
                    st.markdown(f"**Niche :** {prod.niche}")
                    st.markdown(f"**Type :** {prod.product_type}")
                    if prod.listing_data:
                        # Read actual PDF page count for source-of-truth
                        try:
                            from modules.quality.validator import _pdf_page_count
                            real_pages = _pdf_page_count(prod.interior_pdf) or 0
                        except Exception:
                            real_pages = 0
                        claimed = prod.listing_data.get('page_count', 0) or 0
                        trim_w  = prod.listing_data.get('trim_size_w', '?')
                        trim_h  = prod.listing_data.get('trim_size_h', '?')
                        paper   = prod.listing_data.get('paper_type', '?')

                        # Page count line — flag mismatch with claimed
                        pc_line = f"**Pages :** {real_pages}"
                        if claimed and abs(real_pages - claimed) > 2:
                            pc_line += (f"  ⚠️ listing dit {claimed} "
                                         f"({'+' if real_pages > claimed else '−'}"
                                         f"{abs(real_pages - claimed)})")
                        st.markdown(pc_line)
                        # KDP-relevant format meta (what you MUST pick in KDP Step 2)
                        st.markdown(
                            f"**📐 Trim KDP :** `{trim_w}×{trim_h}\"`  ·  "
                            f"**📜 Papier :** `{paper}`"
                        )
                        st.caption(
                            "👉 Lors du push KDP, ce trim + ce papier doivent être "
                            "sélectionnés EXACTEMENT dans Step 2 (sinon cover rejetée)."
                        )
                        st.markdown(f"**Publisher :** {prod.listing_data.get('publisher_name', '—')}")
                        # KDP AI-content disclosure — REQUIRED at publish time
                        _aid = prod.listing_data.get("ai_disclosure") or {}
                        if not _aid:
                            _pt = prod.listing_data.get("product_type", "")
                            _hc = _pt in ("recipe_book", "how_to")
                            _algo = _pt in ("puzzle", "activity_book", "coloring")
                            _aid = {
                                "text": "None (algorithmic content)" if _algo else "AI-generated (Claude)",
                                "images": "AI-generated (cover" + (" + interior images)" if _hc else ")"),
                                "translation": "None (original English)",
                            }
                        st.warning(
                            "🤖 **Déclaration IA (obligatoire sur KDP)** — étape "
                            "« Did you use AI tools? » :\n\n"
                            f"- **Texte** : {_aid.get('text', 'AI-generated')}\n"
                            f"- **Images** : {_aid.get('images', 'AI-generated')}\n"
                            f"- **Traduction** : {_aid.get('translation', 'None')}"
                        )
                    st.caption(f"📄 interior.pdf · {prod.interior_pdf.stat().st_size // 1024} KB"
                               f"  ·  🎨 cover.pdf · {prod.cover_pdf.stat().st_size // 1024} KB")
                with tc3:
                    if st.button("📂 Ouvrir le dossier", key=f"open_{prod.slug}"):
                        import subprocess
                        subprocess.Popen(["open", str(prod.folder)])

                # ── 🔍 Contrôle qualité intérieur (#4) ───────────────────
                with st.expander("🔍 Contrôle qualité intérieur"):
                    try:
                        from modules.quality.validator import qa_interior
                        qa = qa_interior(prod.folder)
                        for it in qa:
                            sev = it.get("sev")
                            msg = it.get("msg", "")
                            if sev == "error":
                                st.error(f"❌ {msg}")
                            elif sev == "warning":
                                st.warning(f"⚠️ {msg}")
                            else:
                                st.success(f"✅ {msg}")
                    except Exception as _qe:
                        st.caption(f"QA indisponible : {str(_qe)[:80]}")

                # ── 🎨 Personnaliser le dos (#6) ─────────────────────────
                with st.expander("🎨 Personnaliser le dos (bouton CTA + couleur)"):
                    _ld = prod.listing_data or {}
                    _cur_cta = ((_ld.get("cover_overrides") or {}).get("cta_text") or "")
                    cta_txt = st.text_input(
                        "Texte du bouton (CTA)", value=_cur_cta,
                        placeholder="ex. START COOKING TODAY (vide = auto)",
                        key=f"cta_{prod.slug}")
                    cta_on = st.checkbox("Afficher le bouton CTA", value=True,
                                         key=f"ctaon_{prod.slug}")
                    acc_hex = st.text_input(
                        "Couleur d'accent du dos (hex, vide = auto)", value="",
                        placeholder="#C8892B", key=f"acc_{prod.slug}")
                    st.caption("Régénère le dos en réutilisant l'illustration "
                               "existante (0 $, le devant ne change pas).")
                    if st.button("♻️ Régénérer le dos", key=f"regenback_{prod.slug}"):
                        try:
                            from modules.creation.batch import regenerate_cover_only
                            ov = {"cta_text": cta_txt or None,
                                  "cta_visible": cta_on,
                                  "back_accent_hex": (acc_hex or None)}
                            with st.spinner("Régénération du dos..."):
                                regenerate_cover_only(
                                    product_dir  = prod.folder,
                                    anthropic_key= Config.ANTHROPIC_API_KEY,
                                    openai_key   = Config.OPENAI_API_KEY,
                                    learning_dir = Config.LEARNING_DIR,
                                    free_style   = False,
                                    reuse_art    = True,
                                    cover_overrides = ov,
                                )
                            st.success("✅ Dos régénéré (cover.pdf mis à jour).")
                        except Exception as _re:
                            st.error(f"Échec : {str(_re)[:120]}")

                # ── ✏️ Manual edit of title / subtitle / description ────
                with st.expander("✏️ Éditer titre / sous-titre / description manuellement"):
                    listing = prod.listing_data or {}
                    new_title = st.text_input(
                        "📝 Titre complet (avec ':' pour split cover automatique)",
                        value=listing.get("title", ""),
                        key=f"edit_title_{prod.slug}",
                        help="Sur le cover : tout avant ':' = titre principal grand · "
                             "tout après ':' = sous-titre plus petit. "
                             "Ex: 'Gentle Giants Coloring Book: Soft Whispers of Monster Trucks'",
                    )
                    new_subtitle = st.text_input(
                        "📝 Sous-titre KDP (champ séparé, utilisé si pas de ':' dans le titre)",
                        value=listing.get("subtitle", ""),
                        key=f"edit_sub_{prod.slug}",
                        help="Utilisé sur Amazon KDP. Sur le cover, ce champ n'est utilisé "
                             "QUE si ton titre n'a pas de ':'.",
                    )
                    new_desc = st.text_area(
                        "📄 Description (HTML autorisé : <b>, <i>, <br>, <p> SEULEMENT)",
                        value=listing.get("description", ""),
                        height=180,
                        key=f"edit_desc_{prod.slug}",
                        help="KDP strippe <ul>, <li>, <h1-6>, <div>, <span>, <style>, "
                             "<img>, <a>. Bullets: <br>• item<br>",
                    )

                    # Detect unsaved changes — surface clear warning
                    edited = (
                        new_title.strip()    != listing.get("title", "").strip() or
                        new_subtitle.strip() != listing.get("subtitle", "").strip() or
                        new_desc.strip()     != listing.get("description", "").strip()
                    )
                    if edited:
                        st.warning(
                            "✏️ **Modifications non sauvegardées** — clique 💾 Sauvegarder OU "
                            "🎨 Sauv + régen cover pour qu'elles soient prises en compte par "
                            "le cover et le push KDP.",
                            icon="⚠️",
                        )

                    # ── 🔑 KEYWORDS EDITOR — KDP 7 max, 50 chars each ─────
                    st.markdown("**🔑 Keywords KDP** (7 max, ≤50 chars chacun)")
                    existing_kws = listing.get("keywords", []) or []
                    # Pad to 7 slots so user can fill empty ones
                    while len(existing_kws) < 7:
                        existing_kws.append("")
                    kw_cols = st.columns(2)
                    new_kws: list = []
                    for i in range(7):
                        with kw_cols[i % 2]:
                            new_kws.append(st.text_input(
                                f"Keyword #{i+1}",
                                value=existing_kws[i][:50] if i < len(existing_kws) else "",
                                max_chars=50,
                                key=f"edit_kw_{prod.slug}_{i}",
                                label_visibility="collapsed",
                                placeholder=f"keyword {i+1}",
                            ))

                    # Auto-suggest button using Keywords Pro
                    sug_col1, sug_col2 = st.columns([1, 2])
                    with sug_col1:
                        if st.button("🤖 Auto-suggérer 7 keywords",
                                     key=f"kw_auto_{prod.slug}",
                                     help="Expand l'autocomplete Amazon + score ROI + "
                                          "sélection mix d'intentions"):
                            from modules.intelligence.keywords_pro import (
                                expand_keywords_pro, select_top_7,
                            )
                            with st.spinner("Recherche keywords pro…"):
                                scored = expand_keywords_pro(
                                    prod.niche, depth=2, n_max=40,
                                )
                                if scored:
                                    suggested = select_top_7(scored)
                                    st.session_state[f"kw_suggested_{prod.slug}"] = suggested
                                    st.toast("✅ 7 keywords suggérés — clique 💾 Sauvegarder",
                                             icon="🤖")
                                    st.rerun()
                                else:
                                    st.warning("Aucun keyword trouvé")
                    with sug_col2:
                        # Show suggestions if they exist
                        if f"kw_suggested_{prod.slug}" in st.session_state:
                            sug = st.session_state[f"kw_suggested_{prod.slug}"]
                            st.caption(
                                f"🤖 Suggérés : {' · '.join(f'`{k}`' for k in sug)} "
                                "(applique-les en cliquant Apply ⬇️)"
                            )
                            if st.button("📥 Apply ces 7 suggestions",
                                         key=f"kw_apply_{prod.slug}",
                                         type="primary"):
                                for i, kw in enumerate(sug[:7]):
                                    st.session_state[f"edit_kw_{prod.slug}_{i}"] = kw
                                del st.session_state[f"kw_suggested_{prod.slug}"]
                                st.rerun()
                    btn_cols = st.columns([2, 1, 2])
                    with btn_cols[0]:
                        if st.button("💾 Sauvegarder ces modifications",
                                     key=f"save_edit_{prod.slug}", type="primary"):
                            import json as _json
                            listing_p = prod.listing_json
                            if listing_p and Path(listing_p).exists():
                                d = _json.loads(Path(listing_p).read_text(encoding="utf-8"))
                                # Clean keywords: trim + cap to 50 chars + drop empties + dedupe
                                cleaned_kws = []
                                seen = set()
                                for kw in new_kws:
                                    k = (kw or "").strip()[:50]
                                    if k and k.lower() not in seen:
                                        cleaned_kws.append(k)
                                        seen.add(k.lower())
                                cleaned_kws = cleaned_kws[:7]
                                # Record edits BEFORE saving for learning system
                                try:
                                    from modules.learning.events import record_listing_edit
                                    for fld, new_val in [
                                        ("title", new_title.strip()),
                                        ("subtitle", new_subtitle.strip()),
                                        ("description", new_desc.strip()),
                                        ("keywords", ", ".join(cleaned_kws)),
                                    ]:
                                        old_val = (", ".join(d.get(fld, []))
                                                   if fld == "keywords"
                                                   else d.get(fld, ""))
                                        if old_val != new_val:
                                            record_listing_edit(
                                                Config.LEARNING_DIR, prod.slug,
                                                fld, old_val, new_val,
                                            )
                                except Exception:
                                    pass
                                d["title"]       = new_title.strip()
                                d["subtitle"]    = new_subtitle.strip()
                                d["description"] = new_desc.strip()
                                d["keywords"]    = cleaned_kws
                                Path(listing_p).write_text(
                                    _json.dumps(d, ensure_ascii=False, indent=2),
                                    encoding="utf-8",
                                )
                                st.toast(
                                    f"✅ Sauvegardé ({len(cleaned_kws)} keywords, "
                                    "edits enregistrés pour learning).",
                                    icon="✅",
                                )
                                st.rerun()
                    with btn_cols[1]:
                        if st.button("🎨 Sauv + régen cover",
                                     key=f"save_regen_{prod.slug}",
                                     help="Sauvegarde + régénère le cover dans la foulée"):
                            import json as _json
                            listing_p = prod.listing_json
                            if listing_p and Path(listing_p).exists():
                                d = _json.loads(Path(listing_p).read_text(encoding="utf-8"))
                                # Clean keywords too
                                cleaned_kws = []
                                seen = set()
                                for kw in new_kws:
                                    k = (kw or "").strip()[:50]
                                    if k and k.lower() not in seen:
                                        cleaned_kws.append(k)
                                        seen.add(k.lower())
                                d["title"]       = new_title.strip()
                                d["subtitle"]    = new_subtitle.strip()
                                d["description"] = new_desc.strip()
                                d["keywords"]    = cleaned_kws[:7]
                                Path(listing_p).write_text(
                                    _json.dumps(d, ensure_ascii=False, indent=2),
                                    encoding="utf-8",
                                )
                                st.session_state["improve_cover_request"] = {
                                    "folder": str(prod.folder),
                                    "slug":   prod.slug,
                                }
                                st.rerun()
                    with btn_cols[2]:
                        # Show preview of cover split for the new title
                        if ":" in new_title:
                            main = new_title.split(":", 1)[0].strip()
                            sub  = new_title.split(":", 1)[1].strip()
                            st.caption(
                                f"📐 Cover prévisualisation :\n"
                                f"**TITRE** : `{main}`\n"
                                f"**Sous-titre** : `{sub[:60]}{'…' if len(sub) > 60 else ''}`"
                            )
                        else:
                            st.caption(f"📐 Cover : titre = `{new_title[:40]}` · "
                                       f"sous-titre = listing.subtitle")

                # ── 🎨 Cover A/B test + Auto-improve (E + F) ────────────
                from modules.quality.auto_improve import (
                    get_candidate_paths, use_candidate, _score_cover_quality,
                )
                from modules.quality.visual import thumbnail_for_cover

                candidates = get_candidate_paths(prod.folder)
                if candidates and len(candidates) > 1:
                    st.markdown(f"**🎨 A/B test — {len(candidates)} candidats cover :**")
                    cand_cols = st.columns(min(len(candidates), 4))
                    for idx, cand in enumerate(candidates):
                        with cand_cols[idx % len(cand_cols)]:
                            # Thumbnail per candidate
                            cand_thumb_cache = Config.LEARNING_DIR / "cover_thumbs" / "candidates"
                            try:
                                tpath = thumbnail_for_cover(cand, cand_thumb_cache, width_px=120)
                                if tpath:
                                    st.image(str(tpath), caption=f"#{idx}")
                            except Exception:
                                st.caption(f"#{idx}")
                            # Score it
                            try:
                                temp_folder = cand.parent.parent
                                # Mock: temporarily swap to score
                                from modules.quality.visual import analyze_cover
                                v = analyze_cover(cand)
                                if v.rendered:
                                    st.caption(f"bright {v.brightness:.0f} · sat {v.dominant_sat:.2f}")
                            except Exception:
                                pass
                            if st.button(f"✅ Utiliser #{idx}", key=f"usecand_{prod.slug}_{idx}"):
                                if use_candidate(prod.folder, idx):
                                    # Record the pick — strong positive learning signal
                                    try:
                                        from modules.learning.events import record_cover_pick
                                        record_cover_pick(
                                            learning_dir   = Config.LEARNING_DIR,
                                            slug           = prod.slug,
                                            candidate_idx  = idx,
                                            score_visual   = int(v.brightness)
                                                              if 'v' in dir() and hasattr(v, 'brightness')
                                                              else None,
                                        )
                                    except Exception:
                                        pass
                                    st.toast(f"Cover #{idx} promu en active (learning enregistré)",
                                             icon="✅")
                                    st.rerun()

                regen_cols = st.columns([1, 1, 1])
                with regen_cols[0]:
                    if st.button(
                        "🔄 Auto-améliorer cover",
                        key=f"improve_{prod.slug}",
                        help="Régénère la cover 3 fois, garde la meilleure",
                    ):
                        st.session_state["improve_cover_request"] = {
                            "folder": str(prod.folder),
                            "slug":   prod.slug,
                        }
                        st.rerun()
                with regen_cols[1]:
                    if st.button(
                        "📄 Régénérer l'intérieur",
                        key=f"regen_int_pub_{prod.slug}",
                        help="Re-génère l'intérieur (listing + design brief + illustrations actuels)",
                    ):
                        st.session_state["regen_interior_pub_request"] = {
                            "folder": str(prod.folder),
                            "slug":   prod.slug,
                        }
                        st.rerun()
                with regen_cols[2]:
                    if st.button(
                        "🔧 Fix dimensions cover",
                        key=f"fix_dims_{prod.slug}",
                        help="KDP refuse le cover pour dim mismatch ? Ouvre un sélecteur trim/paper et re-rend la cover aux bonnes dims (spine recalculée sur PDF réel)",
                    ):
                        st.session_state["fix_cover_dims_open"] = prod.slug

                # ── 🎛️ Fine-tune cover (sliders, garde image AI cache) ────
                cache_exists = (prod.folder / ".cover_front.png").exists()
                with st.expander(
                    f"🎛️ Fine-tune cover {'(sans IA)' if cache_exists else '(cache absent)'}",
                    expanded=False,
                ):
                    if not cache_exists:
                        st.warning(
                            "⚠️ Pas d'image AI cachée pour ce livre. "
                            "Lance d'abord une **🎨 Auto-améliorer cover** (1 fois) → "
                            "ça créera le cache + permettra les fine-tunes 0$ ensuite."
                        )
                    else:
                        st.caption(
                            "🟢 Image AI cachée disponible — fine-tune **sans coût** + 2s. "
                            "Ajuste tout sans appeler DALL-E."
                        )

                        # Quick presets
                        pcols = st.columns(4)
                        preset_pick = None
                        with pcols[0]:
                            if st.button("⚙️ Défauts", key=f"ft_pre_def_{prod.slug}"):
                                preset_pick = "default"
                        with pcols[1]:
                            if st.button("📛 Big title", key=f"ft_pre_big_{prod.slug}"):
                                preset_pick = "big_title"
                        with pcols[2]:
                            if st.button("🌫️ Minimal back", key=f"ft_pre_min_{prod.slug}"):
                                preset_pick = "minimal_back"
                        with pcols[3]:
                            if st.button("🦴 KDP-safe spine", key=f"ft_pre_kdp_{prod.slug}"):
                                preset_pick = "kdp_safe_spine"

                        _preset_values = {
                            "default": {
                                "ts": 1.0, "tyo": 0.0, "sm": 1.0, "tc": "white",
                                "bhp": 0.30, "fs": 0.25,
                                "sp": 0.4, "sv": True, "stc": "white",
                                "ps": 1.0,
                                "bfv": True, "bwa": 0.10, "bdv": True, "btv": True,
                            },
                            "big_title": {
                                "ts": 1.30, "tyo": -0.03, "sm": 0.9, "tc": "white",
                                "bhp": 0.35, "fs": 0.25,
                                "sp": 0.4, "sv": True, "stc": "white",
                                "ps": 1.0,
                                "bfv": True, "bwa": 0.10, "bdv": True, "btv": True,
                            },
                            "minimal_back": {
                                "ts": 1.0, "tyo": 0.0, "sm": 1.0, "tc": "white",
                                "bhp": 0.30, "fs": 0.25,
                                "sp": 0.4, "sv": True, "stc": "white",
                                "ps": 1.0,
                                "bfv": False, "bwa": 0.05, "bdv": True, "btv": True,
                            },
                            "kdp_safe_spine": {
                                "ts": 1.0, "tyo": 0.0, "sm": 1.0, "tc": "white",
                                "bhp": 0.30, "fs": 0.25,
                                "sp": 0.55, "sv": True, "stc": "white",
                                "ps": 1.0,
                                "bfv": True, "bwa": 0.10, "bdv": True, "btv": True,
                            },
                        }
                        if preset_pick:
                            v = _preset_values[preset_pick]
                            for k, val in v.items():
                                st.session_state[f"ft_{k}_{prod.slug}"] = val
                            st.toast(f"Preset «{preset_pick}» appliqué — clique Appliquer pour rendre",
                                      icon="🎛️")

                        # ── Front (4) ─────────────────────────────────────
                        st.markdown("**🎨 Front cover**")
                        f1, f2 = st.columns(2)
                        with f1:
                            ts = st.slider("📏 Taille titre", 0.4, 1.5,
                                            st.session_state.get(f"ft_ts_{prod.slug}", 1.0),
                                            0.05, key=f"ft_ts_{prod.slug}")
                            tyo = st.slider("↕ Position titre Y", -0.15, 0.15,
                                             st.session_state.get(f"ft_tyo_{prod.slug}", 0.0),
                                             0.01, key=f"ft_tyo_{prod.slug}")
                            tc = st.selectbox("🎨 Couleur titre",
                                               options=["white", "black", "auto"],
                                               index=["white","black","auto"].index(
                                                   st.session_state.get(f"ft_tc_{prod.slug}","white")),
                                               key=f"ft_tc_{prod.slug}")
                        with f2:
                            sm = st.slider("📐 Taille sous-titre", 0.5, 1.5,
                                            st.session_state.get(f"ft_sm_{prod.slug}", 1.0),
                                            0.05, key=f"ft_sm_{prod.slug}")
                            bhp = st.slider("📏 Hauteur band texte", 0.20, 0.40,
                                             st.session_state.get(f"ft_bhp_{prod.slug}", 0.30),
                                             0.02, key=f"ft_bhp_{prod.slug}",
                                             help="Petit = plus d'image / Grand = plus de texte")
                            fs = st.slider("🌫️ Fade strength", 0.05, 0.45,
                                            st.session_state.get(f"ft_fs_{prod.slug}", 0.25),
                                            0.02, key=f"ft_fs_{prod.slug}",
                                            help="Doux entre image et band")

                        # ── Spine (3) ─────────────────────────────────────
                        st.markdown("**🦴 Spine (dos)**")
                        s1, s2 = st.columns(2)
                        with s1:
                            sp = st.slider("📏 Padding haut/bas (po)",
                                            0.375, 0.8,
                                            st.session_state.get(f"ft_sp_{prod.slug}", 0.4),
                                            0.025, key=f"ft_sp_{prod.slug}",
                                            help="KDP minimum 0.375\". Bumpe si KDP refuse.")
                            stc = st.selectbox("🎨 Couleur texte spine",
                                                options=["white","black","auto"],
                                                index=["white","black","auto"].index(
                                                    st.session_state.get(f"ft_stc_{prod.slug}","white")),
                                                key=f"ft_stc_{prod.slug}")
                        with s2:
                            sv = st.checkbox("🦴 Afficher spine",
                                              value=st.session_state.get(f"ft_sv_{prod.slug}", True),
                                              key=f"ft_sv_{prod.slug}")
                            ps = st.slider("🏷️ Logo publisher", 0.5, 2.0,
                                            st.session_state.get(f"ft_ps_{prod.slug}", 1.0),
                                            0.1, key=f"ft_ps_{prod.slug}")

                        # ── Typography + Colors ───────────────────────────
                        st.markdown("**🔤 Typographie & couleurs**")
                        tc1, tc2 = st.columns(2)
                        with tc1:
                            font_pool = st.selectbox(
                                "🔤 Famille de fonts",
                                options=["auto (selon type)", "serif", "sans",
                                         "display", "script", "hand", "fantasy"],
                                index=["auto (selon type)","serif","sans","display",
                                       "script","hand","fantasy"].index(
                                    st.session_state.get(f"ft_fp_{prod.slug}", "auto (selon type)")),
                                key=f"ft_fp_{prod.slug}",
                                help="serif = Baskerville/Bodoni · sans = Futura/Helvetica · "
                                     "display = Impact/DIN · script = cursif · hand = marker · "
                                     "fantasy = décoratif",
                            )
                            # ── NEW : exact title-font picker ──────────────
                            from modules.creation.cover_generator import TITLE_FONT_CHOICES
                            _tf_labels = list(TITLE_FONT_CHOICES.keys())
                            title_font_label = st.selectbox(
                                "🅰️ Police du titre (précise)",
                                options=_tf_labels,
                                index=_tf_labels.index(
                                    st.session_state.get(f"ft_tf_{prod.slug}", _tf_labels[0])),
                                key=f"ft_tf_{prod.slug}",
                                help="Choisit une police EXACTE pour le titre (prioritaire sur "
                                     "la famille). Les lignes '— … —' sont des séparateurs, "
                                     "ne pas les choisir. Auto = laisse l'app décider selon la niche.",
                            )
                            band_color = st.color_picker(
                                "🎨 Couleur band (bas du front)",
                                value=st.session_state.get(f"ft_bc_{prod.slug}", "#1A252F"),
                                key=f"ft_bc_{prod.slug}",
                            )
                        with tc2:
                            spine_color = st.color_picker(
                                "🦴 Couleur spine",
                                value=st.session_state.get(f"ft_spc_{prod.slug}", "#1A252F"),
                                key=f"ft_spc_{prod.slug}",
                            )
                            back_color_pick = st.color_picker(
                                "📖 Couleur back cover",
                                value=st.session_state.get(f"ft_bgc_{prod.slug}", "#1A252F"),
                                key=f"ft_bgc_{prod.slug}",
                                help="Par défaut = même que band. Change pour casser l'uniformité.",
                            )
                        # Detect if user actually changed the colors (vs defaults)
                        _color_used = {
                            "band":  band_color   if band_color   != "#1A252F" else None,
                            "spine": spine_color  if spine_color  != "#1A252F" else None,
                            "back":  back_color_pick if back_color_pick != "#1A252F" else None,
                        }

                        # ── Back cover (4) ─────────────────────────────────
                        st.markdown("**📖 Back cover (dos arrière)**")
                        b1, b2 = st.columns(2)
                        with b1:
                            bfv = st.checkbox("🖼️ Cadre décoratif",
                                                value=st.session_state.get(f"ft_bfv_{prod.slug}", True),
                                                key=f"ft_bfv_{prod.slug}")
                            btv = st.checkbox("📛 Afficher titre",
                                                value=st.session_state.get(f"ft_btv_{prod.slug}", True),
                                                key=f"ft_btv_{prod.slug}")
                        with b2:
                            bdv = st.checkbox("📄 Afficher description",
                                                value=st.session_state.get(f"ft_bdv_{prod.slug}", True),
                                                key=f"ft_bdv_{prod.slug}")
                            bwa = st.slider("💧 Watermark image", 0.0, 0.30,
                                             st.session_state.get(f"ft_bwa_{prod.slug}", 0.10),
                                             0.01, key=f"ft_bwa_{prod.slug}",
                                             help="0 = invisible, 0.30 = très marqué")

                        if st.button(
                            "✅ Appliquer & recomposer cover (0$ · 2s)",
                            key=f"ft_apply_{prod.slug}",
                            type="primary",
                        ):
                            st.session_state["ft_recompose_request"] = {
                                "folder": str(prod.folder),
                                "slug":   prod.slug,
                                "overrides": {
                                    # Front
                                    "title_size_mult":      ts,
                                    "title_y_offset_pct":   tyo,
                                    "title_color":          tc,
                                    "subtitle_size_mult":   sm,
                                    "band_height_pct":      bhp,
                                    "fade_strength":        fs,
                                    # Spine
                                    "spine_padding_in":     sp,
                                    "spine_visible":        sv,
                                    "spine_text_color":     stc,
                                    "publisher_size_mult":  ps,
                                    # Back
                                    "back_frame_visible":   bfv,
                                    "back_watermark_alpha": bwa,
                                    "back_description_visible": bdv,
                                    "back_title_visible":   btv,
                                    # Typography & colours
                                    "font_pool": (
                                        "" if font_pool.startswith("auto")
                                        else font_pool
                                    ),
                                    # Exact title font (label resolved in cover_generator)
                                    "title_font": (
                                        None if title_font_label.startswith("✨")
                                        or title_font_label.startswith("—")
                                        else title_font_label
                                    ),
                                    "band_color":  _color_used["band"],
                                    "spine_color": _color_used["spine"],
                                    "back_color":  _color_used["back"],
                                },
                            }
                            st.rerun()

                # Inline dim-fix form
                if st.session_state.get("fix_cover_dims_open") == prod.slug:
                    from modules.creation.kdp_specs import TRIM_SIZES
                    listing_data = prod.listing_data or {}
                    cur_w  = float(listing_data.get("trim_size_w") or 6.0)
                    cur_h  = float(listing_data.get("trim_size_h") or 9.0)
                    cur_pp = str(listing_data.get("paper_type") or "white")
                    with st.expander("🔧 Choisir trim + paper (puis Appliquer)", expanded=True):
                        # Pre-select the current trim if it matches a known one
                        trim_labels = [t.label for t in TRIM_SIZES]
                        cur_idx = 0
                        for i, t in enumerate(TRIM_SIZES):
                            if abs(t.width_in - cur_w) < 0.01 and abs(t.height_in - cur_h) < 0.01:
                                cur_idx = i
                                break
                        picked = st.selectbox("📐 Trim KDP",
                                              options=trim_labels, index=cur_idx,
                                              key=f"fix_trim_{prod.slug}",
                                              help="Doit correspondre EXACTEMENT au trim "
                                                   "choisi dans la fiche KDP (Step 2 → Trim size)")
                        chosen_trim = TRIM_SIZES[trim_labels.index(picked)]
                        paper_opts = ["white", "cream", "groundwood", "color", "premium_color"]
                        picked_paper = st.selectbox("📜 Papier",
                                                    options=paper_opts,
                                                    index=paper_opts.index(cur_pp) if cur_pp in paper_opts else 0,
                                                    key=f"fix_paper_{prod.slug}")
                        bc1, bc2 = st.columns([1, 1])
                        with bc1:
                            if st.button("✅ Appliquer & re-rendre cover",
                                         key=f"fix_apply_{prod.slug}", type="primary"):
                                st.session_state["fix_cover_dims_request"] = {
                                    "folder":     str(prod.folder),
                                    "slug":       prod.slug,
                                    "trim_w":     chosen_trim.width_in,
                                    "trim_h":     chosen_trim.height_in,
                                    "paper_type": picked_paper,
                                }
                                st.session_state.pop("fix_cover_dims_open", None)
                                st.rerun()
                        with bc2:
                            if st.button("Annuler", key=f"fix_cancel_{prod.slug}"):
                                st.session_state.pop("fix_cover_dims_open", None)
                                st.rerun()

                # ── 🎯 Quality Score & Auto-fix (NEW) ──────────────────
                quality = validate_product(prod.folder)
                qcols = st.columns([1, 3])
                with qcols[0]:
                    if quality.score >= 90:
                        st.metric("Quality", f"{quality.score}/100", "✅ ready")
                    elif quality.score >= 70:
                        st.metric("Quality", f"{quality.score}/100", "⚠️ has warnings",
                                  delta_color="off")
                    else:
                        st.metric("Quality", f"{quality.score}/100", "❌ blockers",
                                  delta_color="inverse")
                with qcols[1]:
                    if quality.issues:
                        st.markdown(f"**{quality.summary}**")
                        for i in quality.issues[:5]:
                            mk = {"critical":"❌","warning":"⚠️","info":"ℹ️"}.get(i.severity, "·")
                            fix_tag = " · _auto-fixable_" if i.fix_available else ""
                            st.caption(f"{mk} {i.message}{fix_tag}")
                        if len(quality.issues) > 5:
                            st.caption(f"_…and {len(quality.issues) - 5} more_")
                        if quality.auto_fixable:
                            n_fixes = len({i.fix_strategy for i in quality.auto_fixable})
                            if st.button(
                                f"🔧 Auto-fix {n_fixes} issue(s)",
                                key=f"autofix_{prod.slug}",
                                type="primary" if not quality.is_publishable else "secondary",
                            ):
                                st.session_state["autofix_request"] = {
                                    "slug": prod.slug,
                                    "folder": str(prod.folder),
                                    "strategies": sorted({i.fix_strategy for i in quality.auto_fixable}),
                                }
                                st.rerun()
                    else:
                        st.success(quality.summary)

                # ── 📁 KDP Categories — affichées clairement ────────────
                cats = (prod.listing_data or {}).get("categories", []) if prod.listing_data else []
                if cats:
                    st.markdown("**📁 Catégories KDP à cocher manuellement :**")
                    cat_lines = []
                    for c in cats:
                        path = c.get("path", "")
                        is_primary = c.get("primary", False)
                        prefix = "⭐ **PRIMAIRE** — " if is_primary else "▫️ "
                        cat_lines.append(f"{prefix}`{path}`")
                    st.info("\n\n".join(cat_lines))
                    # Copy-paste helper: plain text version
                    plain_cats = "\n".join(c.get("path", "") for c in cats)
                    st.caption("💡 Copie-colle ce bloc dans KDP si besoin :")
                    st.code(plain_cats, language=None)

                    # Categories Optimizer button (live Amazon scrape)
                    if Config.has_anthropic() and st.button(
                        "📊 Optimiser ces 3 catégories (live Amazon scrape)",
                        key=f"opt_cats_{prod.slug}",
                        help="Claude propose 8 candidats + scrape Amazon top results "
                             "par catégorie + ranke par best-bet (volume + pénétrabilité + prix). "
                             "Coût : ~$0.005 + 60s",
                    ):
                        st.session_state["opt_categories_request"] = {
                            "folder": str(prod.folder),
                            "slug":   prod.slug,
                        }
                        st.rerun()
                else:
                    st.warning(
                        "⚠️ Aucune catégorie dans `listing.json` (livre généré "
                        "avant l'ajout de la fonctionnalité). "
                        "Clique le bouton ci-dessous pour les générer maintenant."
                    )
                    if st.button(
                        "🤖 Générer les 3 catégories KDP avec Claude",
                        key=f"gen_cats_{prod.slug}",
                        type="primary",
                    ):
                        st.session_state["gen_cats_request"] = {
                            "slug": prod.slug,
                            "listing_path": str(prod.listing_json),
                        }
                        st.rerun()

                # ── 🔑 Keywords (rappel rapide) ──────────────────────────
                keywords = (prod.listing_data or {}).get("keywords", []) if prod.listing_data else []
                if keywords:
                    st.markdown("**🔑 7 Keywords :** " +
                                "  ·  ".join(f"`{k}`" for k in keywords))

                # ── ✨ A+ Content (5 modules ready to paste in KDP) ─────
                # ── 🎯 SEO Tower — Keyword Optimization scores ─────────
                try:
                    from modules.intelligence.keyword_tower import (
                        analyze_listing, rewrite_listing_zones,
                    )
                    seo = analyze_listing(prod.listing_data or {})
                    grade_color = {
                        "A": "#27AE60", "B": "#F39C12",
                        "C": "#E67E22", "D": "#C0392B",
                    }[seo["grade"]]
                    with st.expander(
                        f"🎯 SEO Tower — Score {seo['global_score']}/100 · Grade {seo['grade']}",
                        expanded=(seo["grade"] in ("C", "D")),
                    ):
                        # Top metrics row
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("📛 Title",    f"{seo['title']['score']}/100")
                        m2.metric("📐 Subtitle", f"{seo['subtitle']['score']}/100")
                        m3.metric("📄 Description", f"{seo['description']['score']}/100")
                        m4.metric("🔑 Keywords", f"{seo['keywords']['score']}/100")
                        st.markdown(
                            f"<div style='background:{grade_color}22;border-left:4px solid {grade_color};"
                            f"padding:8px 12px;border-radius:4px;margin:8px 0;'>"
                            f"<b>Score global : {seo['global_score']}/100 · Grade {seo['grade']}</b><br>"
                            f"<span style='font-size:12px;color:#666;'>"
                            f"{'🟢 Ranking-ready' if seo['grade']=='A' else '🟡 Optimisable' if seo['grade']=='B' else '🟠 Doit être amélioré' if seo['grade']=='C' else '🔴 Quasi-inrankable, à réécrire'}"
                            f"</span></div>",
                            unsafe_allow_html=True,
                        )
                        # Per-zone breakdown
                        for zname, zlabel in [("title","📛 Title"),("subtitle","📐 Subtitle"),
                                                ("description","📄 Description"),("keywords","🔑 7 Keywords")]:
                            z = seo[zname]
                            with st.container():
                                st.markdown(f"**{zlabel}** — {z['score']}/100")
                                if z["issues"]:
                                    for issue in z["issues"][:6]:
                                        st.caption(f"  · {issue}")
                                if z.get("suggestions"):
                                    for s in z["suggestions"][:3]:
                                        st.caption(f"  💡 {s}")
                        # Autocomplete check button
                        ac1, ac2 = st.columns([1, 1])
                        with ac1:
                            if st.button(
                                "🔎 Vérifier 7 keywords sur Amazon autocomplete (~3s)",
                                key=f"seo_ac_{prod.slug}",
                                help="Probe Amazon pour confirmer que tes keywords ont un vrai volume de recherche",
                            ):
                                with st.spinner("Probing Amazon..."):
                                    from modules.intelligence.keyword_tower import (
                                        validate_keywords_amazon,
                                    )
                                    val = validate_keywords_amazon(
                                        (prod.listing_data or {}).get("keywords", []) or [],
                                    )
                                    if val.get("available"):
                                        n = val["validated"]
                                        if n >= 5:
                                            st.success(f"✅ {n}/7 keywords validés par Amazon — bon signal")
                                        elif n >= 3:
                                            st.warning(f"⚠️ {n}/7 keywords validés — la moitié a peu de volume")
                                        else:
                                            st.error(f"❌ {n}/7 keywords validés — la plupart ont 0 volume Amazon")
                                        for kw, info in val["results"].items():
                                            mark = "✅" if info["validated"] else (
                                                "🟡" if info["confidence"] >= 0.5 else "🔴")
                                            st.caption(f"  {mark} `{kw}` (conf {info['confidence']:.2f})")
                        with ac2:
                            if seo["grade"] in ("C", "D") and Config.has_anthropic():
                                if st.button(
                                    "🤖 Claude réécrit les zones faibles",
                                    key=f"seo_fix_{prod.slug}",
                                    type="primary",
                                    help="Claude analyse les issues et propose un nouveau title/subtitle/description/keywords compliant A10",
                                ):
                                    st.session_state["seo_rewrite_request"] = {
                                        "folder": str(prod.folder),
                                        "slug":   prod.slug,
                                    }
                                    st.rerun()
                except Exception as _seo_e:
                    pass

                # ── 🎯 ARC Tracker — launch team management ────────────
                try:
                    from modules.marketing.arc_tracker import (
                        get_team, team_stats, add_reviewer, update_reviewer_status,
                        remove_reviewer, bulk_import_reviewers,
                        VALID_STATUSES, reviewers_to_markdown,
                    )
                    team   = get_team(Config.LEARNING_DIR, prod.slug)
                    tstats = team_stats(team)
                    target = tstats["target"]
                    posted = tstats["posted_review"]
                    sent   = tstats["sent_pdf"] + tstats["reminded"] + tstats["posted_review"]
                    badge = (
                        f"🟢 {posted}/{target} reviews posted" if posted >= target * 0.7 else
                        f"🟡 {posted}/{target} reviews posted" if posted >= target * 0.3 else
                        f"🔴 {posted}/{target} reviews posted" if posted > 0 else
                        f"⚪ ARC team : {tstats['total']}/{target} reviewers"
                    )
                    with st.expander(f"🎯 ARC Tracker — {badge}", expanded=False):
                        st.caption(
                            "ARC = Advance Review Copy. Tu donnes le livre GRATUITEMENT à "
                            "15-30 lecteurs AVANT publi → ils postent des reviews honnêtes "
                            "le jour de la sortie → Amazon te donne le boost ranking."
                        )

                        # Stats row
                        sc1, sc2, sc3, sc4 = st.columns(4)
                        sc1.metric("👥 Total", f"{tstats['total']}/{target}")
                        sc2.metric("📤 PDF envoyés", sent)
                        sc3.metric("⭐ Reviews postées", posted,
                                    delta=f"{tstats['review_pct']}%" if posted else None)
                        sc4.metric("🎯 Objectif", f"{tstats['target_pct']}%")

                        # Settings : amazon link + target size
                        cs1, cs2 = st.columns([3, 1])
                        with cs1:
                            new_amazon = st.text_input(
                                "🔗 Lien Amazon du livre (utilisé dans le PDF + emails)",
                                value=team.get("amazon_url", ""),
                                key=f"arc_url_{prod.slug}",
                                placeholder="https://www.amazon.com/dp/...",
                            )
                        with cs2:
                            new_target = st.number_input(
                                "🎯 Target",
                                min_value=5, max_value=100,
                                value=target, step=5,
                                key=f"arc_target_{prod.slug}",
                            )
                        if new_amazon != team.get("amazon_url", "") or new_target != target:
                            if st.button("💾 Sauvegarder paramètres", key=f"arc_save_{prod.slug}"):
                                team["amazon_url"] = new_amazon.strip()
                                team["team_size_target"] = int(new_target)
                                from modules.marketing.arc_tracker import upsert_team
                                upsert_team(Config.LEARNING_DIR, prod.slug, team)
                                st.toast("✅ Paramètres ARC sauvegardés", icon="💾")
                                st.rerun()

                        # ── ACTIONS : PDF watermark + email templates ───
                        ac1, ac2, ac3 = st.columns(3)
                        with ac1:
                            if st.button(
                                "📄 Générer ARC PDF watermark",
                                key=f"arc_pdf_{prod.slug}",
                                help="PDF intérieur avec watermark diagonal + "
                                     "page brief en intro + page CTA review en fin",
                            ):
                                st.session_state["arc_pdf_request"] = {
                                    "folder": str(prod.folder), "slug": prod.slug,
                                }
                                st.rerun()
                        with ac2:
                            if Config.has_anthropic() and st.button(
                                "✍️ Générer 4 emails Claude",
                                key=f"arc_emails_{prod.slug}",
                                help="Recruitment / Send PDF / Reminder / Thank you, "
                                     "personnalisés sur la niche par Claude",
                            ):
                                st.session_state["arc_emails_request"] = {
                                    "folder": str(prod.folder), "slug": prod.slug,
                                }
                                st.rerun()
                        with ac3:
                            if team.get("templates_personalized"):
                                st.success("📧 4 emails dispo →")

                        # Show emails if generated
                        if team.get("templates_personalized"):
                            with st.expander("📧 Voir les 4 templates emails", expanded=False):
                                for k, label in [
                                    ("recruitment", "1. 📨 Recruitment (invite reviewers)"),
                                    ("send_pdf",    "2. 📤 Send PDF (après accept)"),
                                    ("reminder",    "3. 🔔 Launch reminder (J-day)"),
                                    ("thank_you",   "4. 🙏 Thank you (après review postée)"),
                                ]:
                                    v = team["templates_personalized"].get(k, "")
                                    if v:
                                        st.markdown(f"**{label}**")
                                        st.code(v, language=None)

                        # ── Reviewers list + bulk import ────────────────
                        st.markdown("**👥 Reviewers**")
                        if team.get("reviewers"):
                            for r in team["reviewers"]:
                                rc1, rc2, rc3, rc4 = st.columns([3, 2, 2, 1])
                                rc1.caption(f"📧 `{r['email']}`")
                                rc2.caption(f"👤 {r.get('name','—')}")
                                new_st = rc3.selectbox(
                                    "", options=list(VALID_STATUSES),
                                    index=list(VALID_STATUSES).index(r.get("status","invited")),
                                    key=f"arc_st_{prod.slug}_{r['email']}",
                                    label_visibility="collapsed",
                                )
                                if new_st != r.get("status"):
                                    update_reviewer_status(
                                        Config.LEARNING_DIR, prod.slug, r["email"], new_st,
                                    )
                                    st.rerun()
                                if rc4.button("🗑️", key=f"arc_del_{prod.slug}_{r['email']}"):
                                    remove_reviewer(Config.LEARNING_DIR, prod.slug, r["email"])
                                    st.rerun()
                        else:
                            st.caption("_Aucun reviewer encore — ajoute-en ci-dessous_")

                        # Bulk import paste
                        with st.expander("➕ Ajouter des reviewers (paste depuis Booksprout / email list)"):
                            paste = st.text_area(
                                "Paste 1 reviewer par ligne (email seul OU 'Name <email>')",
                                placeholder="alice@example.com\nBob Smith <bob@x.com>\ncharlie, charlie@y.com",
                                height=120,
                                key=f"arc_paste_{prod.slug}",
                            )
                            if st.button("📥 Importer", key=f"arc_import_{prod.slug}"):
                                n = bulk_import_reviewers(Config.LEARNING_DIR, prod.slug, paste)
                                if n:
                                    st.success(f"✅ {n} nouveau(x) reviewer(s) ajouté(s)")
                                else:
                                    st.info("Aucun nouvel email valide trouvé (ou tous déjà présents)")
                                st.rerun()

                        # Markdown report export
                        if team.get("reviewers"):
                            if st.button("📋 Exporter table reviewers (markdown)", key=f"arc_export_{prod.slug}"):
                                st.code(reviewers_to_markdown(team), language="markdown")
                except Exception as _arc_e:
                    pass

                aplus_modules = (prod.listing_data or {}).get("aplus_content", [])
                if aplus_modules:
                    with st.expander(f"✨ A+ Content — {len(aplus_modules)} modules prêts à coller dans KDP",
                                     expanded=False):
                        try:
                            from modules.creation.aplus import render_module_text
                        except Exception:
                            render_module_text = None
                        st.caption("KDP A+ Content se fait après publication (Bookshelf → A+ Content Manager). "
                                   "+~12% conversion en moyenne.")
                        for i, m in enumerate(aplus_modules, 1):
                            st.markdown(f"**Module {i} — {m.get('kind','?')}**")
                            if render_module_text:
                                st.code(render_module_text(m), language=None)
                            else:
                                st.json(m)

                # ── 🔍 Deep check (Claude Vision genre signaling) ───────
                if Config.has_anthropic() and st.button(
                    "🔬 Deep check cover (Claude Vision · ~$0.003)",
                    key=f"deep_{prod.slug}",
                    help="Vérifie que le cover communique clairement le genre en <3s",
                ):
                    with st.spinner("Claude Vision analyse le cover..."):
                        try:
                            from modules.quality.genre_signal import check_genre_signal
                            niche_g = (prod.listing_data or {}).get("niche", prod.slug)
                            ptype_g = (prod.listing_data or {}).get("product_type", "book")
                            gs = check_genre_signal(
                                prod.folder / "cover.pdf",
                                product_type=ptype_g,
                                niche=niche_g,
                                anthropic_key=Config.ANTHROPIC_API_KEY,
                            )
                            if gs.get("ok"):
                                st.success(f"{gs['verdict']} · score {gs['score']}/100")
                                st.caption(f"📝 {gs.get('critique','')}")
                                st.caption(
                                    f"Genre clarity : {gs.get('genre_score',0)}/100 · "
                                    f"Readability thumbnail : {gs.get('readability',0)}/100"
                                )
                            else:
                                st.warning(f"Deep check indispo : {gs.get('reason','?')}")
                        except Exception as e:
                            st.error(f"Deep check failed: {e}")

                bc1, bc2 = st.columns(2)
                with bc1:
                    push_disabled = not sess_ok
                    if st.button(
                        "📤 Pousser vers KDP (mode brouillon)",
                        key=f"push_{prod.slug}",
                        type="primary",
                        disabled=push_disabled,
                        help=("Logge-toi d'abord à KDP via le bouton en haut."
                              if push_disabled else
                              "Le bot ouvre Firefox, remplit le formulaire KDP, "
                              "upload les PDFs et s'arrête avant Publish."),
                    ):
                        st.session_state["kdp_push_request"] = {
                            "slug": prod.slug, "headless": headless,
                        }
                        st.rerun()
                with bc2:
                    if st.button("✅ Marquer comme publié manuellement",
                                 key=f"mark_{prod.slug}",
                                 help="Si tu as déjà publié sur KDP toi-même, "
                                      "clique ici pour déplacer le dossier dans /published/."):
                        st.session_state["kdp_mark_request"] = {"slug": prod.slug}
                        st.rerun()

    # ── List published ────────────────────────────────────────────────────
    published = [p for p in products if p.status == "published"]
    if published:
        st.markdown("---")
        st.markdown(f"### ✅ Déjà publiés ({len(published)})")
        for prod in published:
            with st.expander(f"📗 {prod.title[:65]}  ·  `{prod.slug}`",
                             expanded=False):
                pc1, pc2 = st.columns([3, 1])
                with pc1:
                    st.markdown(f"**Niche :** {prod.niche}")
                    if prod.published_at:
                        st.caption(f"📅 Publié le : {prod.published_at[:19]}")
                    if prod.published_url:
                        st.markdown(f"🔗 [Voir sur KDP]({prod.published_url})")
                with pc2:
                    if st.button("↩️ Revenir en draft", key=f"rev_{prod.slug}"):
                        try:
                            revert_published(prod, kdp_root)
                            st.success("Déplacé en drafts")
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

                # ── ✨ A+ Content for this PUBLISHED book ───────────────────
                _ld = prod.listing_data or {}
                _existing_aplus = _ld.get("aplus_content", [])
                st.markdown("---")
                st.markdown("**✨ A+ Content (ultra-marketing, dimensions KDP exactes)**")
                st.caption("KDP A+ se fait après publication : Bookshelf → ton livre → "
                           "**A+ Content** → Manager. Copie les modules ci-dessous + uploade "
                           "les images aux dimensions indiquées.")
                ap_c1, ap_c2 = st.columns(2)
                with ap_c1:
                    if st.button("✨ Générer le A+ Content", key=f"aplus_gen_{prod.slug}",
                                 type="primary"):
                        st.session_state["aplus_pub_request"] = {
                            "folder": str(prod.folder), "slug": prod.slug,
                            "with_images": False,
                        }
                        st.rerun()
                with ap_c2:
                    if st.button(
                            "📕 Générer A+ + images du VRAI livre (gratuit, recommandé)",
                            key=f"aplus_real_{prod.slug}", type="primary",
                            help="Images A+ = mockups 3D de ta vraie couverture + intérieur, "
                                 "dimensions exactes. Crédible et gratuit."):
                        st.session_state["aplus_pub_request"] = {
                            "folder": str(prod.folder), "slug": prod.slug,
                            "with_images": True, "mode": "mockup",
                        }
                        st.rerun()
                if Config.has_openai():
                    if st.button("🎨 (alternatif) A+ + images lifestyle DALL-E (~0,35 $)",
                                 key=f"aplus_img_{prod.slug}"):
                        st.session_state["aplus_pub_request"] = {
                            "folder": str(prod.folder), "slug": prod.slug,
                            "with_images": True, "mode": "dalle",
                        }
                        st.rerun()

                # ── 🎨 Canva Smartmockups (photoréaliste, gratuit) ──────────
                st.markdown("**🎨 Mockup photoréaliste via Canva Smartmockups (gratuit)**")
                if st.button("📤 Exporter la couverture + intérieur pour Canva",
                             key=f"canva_export_{prod.slug}",
                             help="Exporte la couverture exacte (avec titre) + une page d'intérieur "
                                  "en haute résolution, prêtes à uploader dans Canva → Apps → Mockups."):
                    st.session_state["canva_export_request"] = {
                        "folder": str(prod.folder), "slug": prod.slug,
                    }
                    st.rerun()
                _cv = prod.folder / "cover_for_canva.png"
                if _cv.exists():
                    st.success("✅ Couverture exportée : `cover_for_canva.png` dans le dossier du livre")
                    with open(_cv, "rb") as f:
                        st.download_button("⬇️ Télécharger la couverture (pour Canva)",
                                           f, file_name=f"{prod.slug}_cover.png",
                                           mime="image/png", key=f"dl_cv_{prod.slug}")
                    st.caption("👉 Dans Canva : **Apps → Mockups** → cherche « paperback » → "
                               "**Uploads** → upload ce fichier → applique → **Save mockup** → Download.")

                # ── 📕 3D book mockups locaux (rapide, gratuit) ──────────────
                if st.button("📕 (alternatif) Mockups 3D locaux instantanés",
                             key=f"mockup_{prod.slug}",
                             help="Rendus 3D générés localement (rapide, pas besoin de Canva)."):
                    st.session_state["mockup_pub_request"] = {
                        "folder": str(prod.folder), "slug": prod.slug,
                    }
                    st.rerun()
                # Show existing mockups
                _mk_dir = prod.folder / "mockups"
                if _mk_dir.exists():
                    mks = sorted(_mk_dir.glob("*.png"))
                    if mks:
                        st.markdown(f"**📕 {len(mks)} mockup(s) 3D :**")
                        st.image([str(x) for x in mks], width=140)

                if _existing_aplus:
                    from modules.creation.aplus import render_module_text, aplus_image_manifest
                    st.success(f"✅ {len(_existing_aplus)} modules A+ prêts")
                    for i, m in enumerate(_existing_aplus, 1):
                        with st.expander(f"Module {i} — {m.get('kdp_module', m.get('kind'))}",
                                         expanded=False):
                            st.code(render_module_text(m), language=None)
                    manifest = aplus_image_manifest(_existing_aplus)
                    if manifest:
                        st.markdown("**📐 Images à créer (dimensions exactes) :**")
                        import pandas as _pd
                        st.dataframe(_pd.DataFrame([{
                            "Module": x["module"][:28], "Dimensions": x["dimensions"],
                            "Image": x["label"], "Idée visuelle": x["prompt"][:50],
                        } for x in manifest]), use_container_width=True, hide_index=True)
                    # Show generated images if present
                    _img_dir = prod.folder / "aplus_images"
                    if _img_dir.exists():
                        imgs = sorted(_img_dir.glob("*.jpg"))
                        if imgs:
                            st.markdown(f"**🖼️ {len(imgs)} image(s) générée(s) dans `aplus_images/`**")
                            st.image([str(x) for x in imgs[:9]], width=120)

    # ── Incomplete ────────────────────────────────────────────────────────
    incompletes = [p for p in products if p.status == "incomplete"]
    if incompletes:
        st.markdown("---")
        with st.expander(f"⚠️ Produits incomplets ({len(incompletes)}) — manque PDF ou listing",
                          expanded=True):
            for prod in incompletes:
                missing = []
                if not prod.interior_pdf: missing.append("interior.pdf")
                if not prod.cover_pdf:    missing.append("cover.pdf")
                if not prod.listing_json: missing.append("listing.json")
                has_listing = bool(prod.listing_json)
                has_interior = bool(prod.interior_pdf)
                # Only_cover_missing is the easy case: just regenerate the cover
                only_cover    = missing == ["cover.pdf"] and has_listing and has_interior
                only_interior = missing == ["interior.pdf"] and has_listing
                no_listing    = not has_listing
                cols = st.columns([2, 1.2, 1.2, 1])
                with cols[0]:
                    st.markdown(f"**`{prod.slug}`** — manque : {', '.join(missing)}")
                with cols[1]:
                    if only_cover:
                        if st.button("🎨 Re-créer cover", key=f"inc_cov_{prod.slug}",
                                      type="primary"):
                            st.session_state["regen_single_request"] = {
                                "kind": "cover", "folder": str(prod.folder),
                                "slug": prod.slug,
                            }
                            st.rerun()
                    elif only_interior:
                        if st.button("📄 Re-créer intérieur", key=f"inc_int_{prod.slug}",
                                      type="primary"):
                            st.session_state["regen_single_request"] = {
                                "kind": "interior", "folder": str(prod.folder),
                                "slug": prod.slug,
                            }
                            st.rerun()
                    elif no_listing:
                        st.caption("❌ Pas de listing → impossible à compléter")
                    else:
                        if st.button("🔧 Tout recréer", key=f"inc_both_{prod.slug}",
                                      type="primary"):
                            st.session_state["regen_single_request"] = {
                                "kind": "both", "folder": str(prod.folder),
                                "slug": prod.slug,
                            }
                            st.rerun()
                with cols[2]:
                    if has_listing:
                        st.caption(f"📁 [Open]({prod.folder})")
                with cols[3]:
                    if st.button("🗑️", key=f"inc_del_{prod.slug}",
                                  help="Supprimer ce dossier vide"):
                        st.session_state["delete_incomplete_request"] = {
                            "folder": str(prod.folder), "slug": prod.slug,
                        }
                        st.rerun()

    # ── Handle push request — START the background runner ────────────────
    push_req = st.session_state.pop("kdp_push_request", None)
    if push_req:
        slug = push_req["slug"]
        target = next((p for p in products if p.slug == slug), None)
        if not target:
            st.error(f"Produit '{slug}' introuvable")
        else:
            # Set the active slug FIRST so the top panel shows immediately
            st.session_state["pub_active_slug"] = slug
            started = pub_start(
                listing      = target.listing_data,
                interior_pdf = target.interior_pdf,
                cover_pdf    = target.cover_pdf,
                learning_dir = Config.LEARNING_DIR,
                headless     = push_req["headless"],
            )
            if not started:
                st.warning(
                    "⚠️ Une publication tourne déjà — le panneau ci-dessus "
                    "affiche son statut. Si elle est vraiment bloquée, clique "
                    "🗑️ Effacer puis relance."
                )
            else:
                logger.info(f"Publish thread started for: {slug}")
            st.rerun()

    # (Live status panel is at the TOP of page_publishing — see above)

    # ── Handle auto-improve cover request (E) ────────────────────────────
    imp_req = st.session_state.pop("improve_cover_request", None)
    if imp_req:
        from modules.quality.auto_improve import improve_cover
        st.markdown("---")
        st.markdown(f"### 🎨 Auto-improve cover : `{imp_req['slug']}`")
        log_msgs = []
        log_box = st.empty()
        def push_imp(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-20:]), language=None)
        with st.spinner("Régénérations en cours (3 essais max)…"):
            try:
                result = improve_cover(
                    product_folder = Path(imp_req["folder"]),
                    anthropic_key  = Config.ANTHROPIC_API_KEY,
                    openai_key     = Config.OPENAI_API_KEY,
                    learning_dir   = Config.LEARNING_DIR,
                    max_attempts   = 3,
                    min_target     = 75,
                    status_cb      = push_imp,
                    force          = True,  # user clicked → ignore early-exit
                )
                delta = result.best_score - result.initial_score
                if delta > 0:
                    st.success(
                        f"✅ Cover amélioré : {result.initial_score} → {result.best_score} "
                        f"(+{delta} points) — candidat #{result.kept_attempt} retenu"
                    )
                else:
                    st.info(
                        f"Cover initial déjà optimal ({result.initial_score}/100) — "
                        f"aucun candidat meilleur trouvé"
                    )
                if st.button("🔄 Recharger pour voir le nouveau cover", key="reload_imp"):
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Erreur : {e}")

    # ── Handle ARC PDF generation ────────────────────────────────────────
    arc_pdf_req = st.session_state.pop("arc_pdf_request", None)
    if arc_pdf_req:
        st.markdown("---")
        st.markdown(f"### 📄 Génération ARC PDF : `{arc_pdf_req['slug']}`")
        try:
            import json as _json
            from modules.marketing.arc_tracker import make_arc_pdf, get_team
            folder = Path(arc_pdf_req["folder"])
            d = _json.loads((folder / "listing.json").read_text(encoding="utf-8"))
            team = get_team(Config.LEARNING_DIR, arc_pdf_req["slug"])
            out_path = folder / "arc_copy.pdf"
            with st.spinner("Watermarking interior PDF + ajout des pages brief/CTA…"):
                ok = make_arc_pdf(
                    interior_pdf=folder / "interior.pdf",
                    output_pdf  = out_path,
                    book_title  = d.get("title", "Untitled"),
                    author      = d.get("publisher_name", "Author"),
                    amazon_url  = team.get("amazon_url", ""),
                )
            if ok and out_path.exists():
                size_kb = out_path.stat().st_size // 1024
                st.success(f"✅ ARC PDF généré → `{out_path.name}` ({size_kb} KB)")
                with open(out_path, "rb") as f:
                    st.download_button(
                        "⬇️ Télécharger arc_copy.pdf",
                        data=f.read(),
                        file_name=f"{arc_pdf_req['slug']}_ARC.pdf",
                        mime="application/pdf",
                        key="arc_dl",
                    )
                st.caption(
                    "👉 Upload ce PDF sur Booksprout (dans ta campagne ARC) "
                    "OU envoie-le directement aux reviewers (Gmail attach)."
                )
            else:
                st.error("❌ Génération échouée — vérifie que interior.pdf existe")
        except Exception as e:
            import traceback as _tb
            st.error(f"❌ {type(e).__name__} : {e}")
            with st.expander("🐛 Traceback"):
                st.code(_tb.format_exc(), language="python")

    # ── Handle ARC email templates generation ────────────────────────────
    arc_em_req = st.session_state.pop("arc_emails_request", None)
    if arc_em_req:
        st.markdown("---")
        st.markdown(f"### ✍️ Personnalisation emails ARC : `{arc_em_req['slug']}`")
        try:
            import json as _json
            from modules.marketing.arc_tracker import (
                generate_email_templates, get_team, upsert_team,
            )
            folder = Path(arc_em_req["folder"])
            d = _json.loads((folder / "listing.json").read_text(encoding="utf-8"))
            log_msgs, log_box = [], st.empty()
            def push_em(m):
                log_msgs.append(m); log_box.code("\n".join(log_msgs[-10:]), language=None)
            with st.spinner("Claude personnalise 4 templates…"):
                templates = generate_email_templates(
                    d, Config.ANTHROPIC_API_KEY, status_cb=push_em,
                )
            if templates:
                team = get_team(Config.LEARNING_DIR, arc_em_req["slug"])
                team["templates_personalized"] = templates
                upsert_team(Config.LEARNING_DIR, arc_em_req["slug"], team)
                st.success(
                    f"✅ 4 templates générés et sauvegardés. "
                    "Tu peux les voir dans 📧 Voir les 4 templates emails."
                )
                if st.button("🔄 Recharger pour voir", key="arc_em_reload"):
                    st.rerun()
            else:
                st.error("❌ Génération échouée")
        except Exception as e:
            import traceback as _tb
            st.error(f"❌ {type(e).__name__} : {e}")
            with st.expander("🐛 Traceback"):
                st.code(_tb.format_exc(), language="python")

    # ── Handle Categories Optimizer (live Amazon scrape, deep) ───────────
    cat_req = st.session_state.pop("opt_categories_request", None)
    if cat_req:
        st.markdown("---")
        st.markdown(f"### 📊 Categories Optimizer : `{cat_req['slug']}`")
        log_msgs, log_box = [], st.empty()
        def push_cat(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-25:]), language=None)
        try:
            import json as _json
            listing_p = Path(cat_req["folder"]) / "listing.json"
            d = _json.loads(listing_p.read_text(encoding="utf-8"))
            niche  = d.get("niche", "")
            ptype  = d.get("product_type", "book")
            with st.spinner("Pipeline : Claude → scrape Amazon → ranking (≈60s)…"):
                from modules.intelligence.categories_optimizer import (
                    optimize_categories, auto_persist_top3,
                )
                results = optimize_categories(
                    niche=niche, product_type=ptype,
                    anthropic_key=Config.ANTHROPIC_API_KEY,
                    max_candidates=6, deep_bsr=True,
                    status_cb=push_cat,
                )
            if not results:
                st.error("❌ Aucune catégorie candidate retournée — vérifie ta clé Anthropic")
            else:
                st.success(f"✅ {len(results)} catégories analysées · meilleur score : "
                            f"{results[0]['scores']['composite']}/100")
                # Display ranked list
                for rank, r in enumerate(results, 1):
                    sc = r["scores"]
                    st_obj = r["stats"]
                    bsr_avg = st_obj.get("bsr_stats", {}).get("avg") if st_obj.get("bsr_stats") else None
                    medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"
                    with st.expander(
                        f"{medal} {sc['composite']}/100 — {r['path']}",
                        expanded=(rank <= 3),
                    ):
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("🎯 Pénétrable", f"{sc['penetrability']:.0f}/100")
                        c2.metric("📈 Volume", f"{sc['volume']:.0f}/100")
                        c3.metric("💰 Prix viable", f"{sc['price_viability']:.0f}/100")
                        c4.metric("Reviews moy.", f"{st_obj.get('avg_reviews','?')}")
                        st.caption(f"**{r['verdict']}**")
                        st.caption(f"💡 _Claude rationale_: {r['rationale']}")
                        details = []
                        if bsr_avg:    details.append(f"BSR top 3 moy : **{bsr_avg:,}**")
                        if st_obj.get("avg_price"): details.append(f"Prix moy : **${st_obj['avg_price']:.2f}**")
                        details.append(f"Low-review top : **{st_obj.get('low_review_pct',0):.0f}%**")
                        st.caption(" · ".join(details))
                        st.caption(f"_Search keyword utilisé pour scrape : `{r['search_keyword']}`_")
                st.markdown("---")
                if st.button(
                    "✅ Appliquer les 3 meilleures (écrase categories existantes)",
                    key="cats_apply", type="primary",
                ):
                    new_cats = auto_persist_top3(Path(cat_req["folder"]), results)
                    if new_cats:
                        st.success(
                            "💾 Sauvegardé dans listing.json. Top 3 :\n\n" +
                            "\n".join(f"{'⭐' if c['primary'] else '▫️'} `{c['path']}`"
                                      for c in new_cats)
                        )
                        if st.button("🔄 Recharger", key="cats_reload"):
                            st.rerun()
        except Exception as e:
            import traceback as _tb
            st.error(f"❌ {type(e).__name__} : {e}")
            with st.expander("🐛 Traceback", expanded=False):
                st.code(_tb.format_exc(), language="python")

    # ── Handle SEO Tower Claude rewrite ──────────────────────────────────
    seo_req = st.session_state.pop("seo_rewrite_request", None)
    if seo_req:
        st.markdown("---")
        st.markdown(f"### 🤖 Claude SEO rewrite : `{seo_req['slug']}`")
        log_msgs, log_box = [], st.empty()
        def push_seo(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-15:]), language=None)
        try:
            import json as _json
            listing_p = Path(seo_req["folder"]) / "listing.json"
            d = _json.loads(listing_p.read_text(encoding="utf-8"))
            from modules.intelligence.keyword_tower import (
                rewrite_listing_zones, analyze_listing,
            )
            with st.spinner("Claude réécrit les zones faibles…"):
                rewrites = rewrite_listing_zones(
                    d, Config.ANTHROPIC_API_KEY, status_cb=push_seo,
                )
            if not rewrites:
                st.info("Aucune zone à réécrire — le listing est déjà fort.")
            else:
                st.success(f"✅ Claude a réécrit : {', '.join(rewrites.keys())}")
                # Side-by-side preview
                for k, v in rewrites.items():
                    st.markdown(f"**{k.upper()}**")
                    cols = st.columns(2)
                    cols[0].caption("AVANT")
                    cols[0].code(str(d.get(k, "(vide)"))[:600], language=None)
                    cols[1].caption("APRÈS (Claude)")
                    cols[1].code(str(v)[:600], language=None)
                # Apply button
                if st.button("✅ Appliquer ces changements (persistant)",
                              key="seo_apply", type="primary"):
                    for k, v in rewrites.items():
                        d[k] = v
                    listing_p.write_text(
                        _json.dumps(d, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    new_seo = analyze_listing(d)
                    st.success(
                        f"💾 Sauvegardé. Nouveau score : {new_seo['global_score']}/100 "
                        f"· Grade {new_seo['grade']}"
                    )
                    if st.button("🔄 Recharger", key="seo_reload"):
                        st.rerun()
        except Exception as e:
            import traceback as _tb
            st.error(f"❌ {type(e).__name__} : {e}")
            with st.expander("🐛 Traceback", expanded=False):
                st.code(_tb.format_exc(), language="python")

    # ── Handle fine-tune cover (recompose with overrides, no DALL-E) ─────
    ft_req = st.session_state.pop("ft_recompose_request", None)
    if ft_req:
        st.markdown("---")
        st.markdown(f"### 🎛️ Fine-tune cover : `{ft_req['slug']}`")
        st.caption(f"Overrides : {ft_req['overrides']}")
        log_msgs, log_box = [], st.empty()
        def push_ft(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-25:]), language=None)
        with st.spinner("Recomposition cover avec image cachée (sans IA)…"):
            try:
                from modules.creation.batch import recompose_cover_with_overrides
                out = recompose_cover_with_overrides(
                    product_dir = Path(ft_req["folder"]),
                    overrides   = ft_req["overrides"],
                    status_cb   = push_ft,
                )
                if out:
                    st.success(
                        f"✅ Cover recomposée en quelques secondes (0 $) → `{Path(out).name}`"
                    )
                    # LEARN from this manual tuning — the bot picks up your
                    # recurring cover preferences and seeds them into future
                    # generations (see cover_preferences()).
                    try:
                        from modules.learning.events import record_cover_finetune
                        record_cover_finetune(
                            Config.LEARNING_DIR, ft_req["slug"], ft_req["overrides"],
                        )
                    except Exception:
                        pass
                    if st.button("🔄 Recharger la card", key="reload_ft"):
                        st.rerun()
            except FileNotFoundError as e:
                st.error(f"❌ {e}")
            except Exception as e:
                import traceback as _tb
                st.error(f"❌ {type(e).__name__} : {e}")
                with st.expander("🐛 Traceback", expanded=False):
                    st.code(_tb.format_exc(), language="python")

    # ── Handle incomplete product completion / deletion ──────────────────
    rs_req = st.session_state.pop("regen_single_request", None)
    if rs_req:
        st.markdown("---")
        st.markdown(f"### 🔧 Complétion : `{rs_req['slug']}`")
        log_msgs, log_box = [], st.empty()
        def push_rs(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-25:]), language=None)
        with st.spinner(f"Régénération ({rs_req['kind']})..."):
            try:
                from modules.creation.batch import (
                    regenerate_cover_only, regenerate_interior_only,
                )
                folder = Path(rs_req["folder"])
                if rs_req["kind"] in ("interior", "both"):
                    regenerate_interior_only(
                        product_dir   = folder,
                        anthropic_key = Config.ANTHROPIC_API_KEY,
                        openai_key    = Config.OPENAI_API_KEY,
                        learning_dir  = Config.LEARNING_DIR,
                        status_cb     = push_rs,
                    )
                if rs_req["kind"] in ("cover", "both"):
                    regenerate_cover_only(
                        product_dir   = folder,
                        anthropic_key = Config.ANTHROPIC_API_KEY,
                        openai_key    = Config.OPENAI_API_KEY,
                        learning_dir  = Config.LEARNING_DIR,
                        status_cb     = push_rs,
                    )
                st.success("✅ Fichiers manquants régénérés. Recharge pour voir.")
                if st.button("🔄 Recharger", key="reload_rs"):
                    st.rerun()
            except Exception as e:
                import traceback as _tb
                st.error(f"❌ {type(e).__name__} : {e}")
                with st.expander("🐛 Traceback complet (pour debug)", expanded=False):
                    st.code(_tb.format_exc(), language="python")
                st.caption("👉 Si OpenAI quota / clé invalide : va dans **Settings** "
                            "et vérifie ta clé. Si rate-limit : attends 1 min et relance. "
                            "Si erreur listing : ouvre le dossier et vérifie que "
                            "`listing.json` contient bien `page_count`, `trim_size_w/h`.")

    del_req = st.session_state.pop("delete_incomplete_request", None)
    if del_req:
        try:
            import shutil as _sh
            _sh.rmtree(del_req["folder"], ignore_errors=False)
            st.success(f"🗑️ Dossier supprimé : `{del_req['slug']}`")
            if st.button("🔄 Recharger", key="reload_del"):
                st.rerun()
        except Exception as e:
            st.error(f"❌ Suppression échouée : {e}")

    # ── Handle cover dim-fix request (from Publishing draft card) ────────
    fix_req = st.session_state.pop("fix_cover_dims_request", None)
    if fix_req:
        st.markdown("---")
        st.markdown(f"### 🔧 Fix dimensions cover : `{fix_req['slug']}`")
        st.caption(f"Trim cible {fix_req['trim_w']}×{fix_req['trim_h']}\" · "
                   f"papier {fix_req['paper_type']}")
        log_msgs = []
        log_box  = st.empty()
        def push_fix(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-25:]), language=None)
        with st.spinner("Recalcule des dims + re-rendu de la cover…"):
            try:
                from modules.creation.batch import fix_cover_dimensions
                out = fix_cover_dimensions(
                    product_dir   = Path(fix_req["folder"]),
                    openai_key    = Config.OPENAI_API_KEY,
                    learning_dir  = Config.LEARNING_DIR,
                    status_cb     = push_fix,
                    new_trim_w    = fix_req["trim_w"],
                    new_trim_h    = fix_req["trim_h"],
                    new_paper_type= fix_req["paper_type"],
                )
                if out:
                    st.success(
                        f"✅ Cover ré-rendue → `{Path(out).name}` aux dimensions KDP. "
                        "Re-upload sur KDP : l'erreur dimension devrait disparaître."
                    )
                    if st.button("🔄 Recharger la card", key="reload_fix_dims"):
                        st.rerun()
                else:
                    st.error("❌ Fix échoué — voir le log ci-dessus")
            except Exception as e:
                st.error(f"❌ Erreur : {e}")

    # ── Handle interior regen request (from Publishing draft card) ───────
    int_req = st.session_state.pop("regen_interior_pub_request", None)
    if int_req:
        st.markdown("---")
        st.markdown(f"### 📄 Régénération intérieur : `{int_req['slug']}`")
        log_msgs = []
        log_box = st.empty()
        def push_int(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-25:]), language=None)
        with st.spinner("Régénération de l'intérieur PDF…"):
            try:
                from modules.creation.batch import regenerate_interior_only
                out = regenerate_interior_only(
                    product_dir   = Path(int_req["folder"]),
                    anthropic_key = Config.ANTHROPIC_API_KEY,
                    openai_key    = Config.OPENAI_API_KEY,
                    learning_dir  = Config.LEARNING_DIR,
                    status_cb     = push_int,
                )
                if out:
                    st.success(
                        f"✅ Intérieur régénéré → `{Path(out).name}` "
                        "(layouts + tracker niche + illustrations rafraîchis)"
                    )
                    if st.button("🔄 Recharger la card", key="reload_int_pub"):
                        st.rerun()
                else:
                    st.error("❌ Régénération échouée — voir le log ci-dessus")
            except Exception as e:
                st.error(f"❌ Erreur : {e}")

    # ── Handle A+ Content generation (published books) ────────────────────
    aplus_req = st.session_state.pop("aplus_pub_request", None)
    if aplus_req:
        st.markdown("---")
        st.markdown(f"### ✨ A+ Content : `{aplus_req['slug']}`")
        log_msgs = []
        log_box = st.empty()
        def push_ap(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-20:]), language=None)
        with st.spinner("Génération A+ Content ultra-marketing…"):
            try:
                import json as _json
                from modules.creation.aplus import (
                    generate_aplus_content, attach_aplus, generate_aplus_images,
                )
                folder = Path(aplus_req["folder"])
                listing = _json.loads((folder / "listing.json").read_text(encoding="utf-8"))
                modules = generate_aplus_content(
                    listing, Config.ANTHROPIC_API_KEY, status_cb=push_ap,
                )
                if modules:
                    attach_aplus(folder / "listing.json", modules)
                    push_ap(f"✅ {len(modules)} modules A+ sauvegardés dans listing.json")
                    if aplus_req.get("with_images"):
                        mode = aplus_req.get("mode", "mockup")
                        if mode == "mockup":
                            from modules.creation.aplus import aplus_image_manifest
                            from modules.creation.book_mockup import make_aplus_images_from_book
                            manifest = aplus_image_manifest(modules)
                            interior = folder / "interior.pdf"
                            make_aplus_images_from_book(
                                manifest, folder / "cover.pdf",
                                interior if interior.exists() else None,
                                listing, folder, status_cb=push_ap,
                            )
                        elif mode == "dalle" and Config.has_openai():
                            generate_aplus_images(
                                modules, listing, folder,
                                openai_key=Config.OPENAI_API_KEY, status_cb=push_ap,
                            )
                    st.success(f"✅ A+ Content généré ({len(modules)} modules). "
                               "Recharge la carte du livre pour le voir.")
                    if st.button("🔄 Recharger", key="reload_aplus_pub"):
                        st.rerun()
                else:
                    st.error("❌ Génération A+ échouée (clé Anthropic ?)")
            except Exception as e:
                import traceback as _tb
                st.error(f"❌ Erreur : {e}")
                with st.expander("🐛 Traceback"):
                    st.code(_tb.format_exc())

    # ── Handle Canva cover export (published books) ───────────────────────
    cv_req = st.session_state.pop("canva_export_request", None)
    if cv_req:
        st.markdown("---")
        st.markdown(f"### 📤 Export pour Canva Smartmockups : `{cv_req['slug']}`")
        with st.spinner("Export couverture + intérieur haute résolution…"):
            try:
                from modules.creation.book_mockup import (
                    export_cover_for_canva, export_interior_for_canva,
                )
                import json as _json
                folder = Path(cv_req["folder"])
                listing = _json.loads((folder / "listing.json").read_text(encoding="utf-8"))
                cv = export_cover_for_canva(folder / "cover.pdf", listing, folder)
                msg = f"✅ Couverture exportée → `{cv.name}`"
                interior = folder / "interior.pdf"
                if interior.exists():
                    ii = export_interior_for_canva(interior, folder)
                    if ii:
                        msg += f" · intérieur → `{ii.name}`"
                st.success(msg)
                st.markdown(
                    "**Étapes Canva (gratuit) :**\n"
                    "1. Ouvre **Canva** → un design vide\n"
                    "2. **Apps → Mockups** (Smartmockups)\n"
                    "3. Cherche « **paperback** » ou « **book** » → choisis un mockup\n"
                    "4. Onglet **Uploads** → uploade `cover_for_canva.png`\n"
                    "5. Applique → **Save mockup** → **Download**\n"
                    "6. Reviens dans l'app : **📕 Générer A+** pour les textes, et uploade "
                    "le mockup Canva comme image hero dans KDP A+."
                )
                if st.button("🔄 Recharger", key="reload_canva_export"):
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Erreur : {e}")

    # ── Handle 3D mockup generation (published books) ─────────────────────
    mk_req = st.session_state.pop("mockup_pub_request", None)
    if mk_req:
        st.markdown("---")
        st.markdown(f"### 📕 Mockups 3D : `{mk_req['slug']}`")
        log_msgs = []
        log_box = st.empty()
        def push_mk(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-20:]), language=None)
        with st.spinner("Génération des mockups 3D (vraie couverture + intérieur)…"):
            try:
                from modules.creation.book_mockup import make_mockups
                folder = Path(mk_req["folder"])
                import json as _json
                listing = _json.loads((folder / "listing.json").read_text(encoding="utf-8"))
                interior = folder / "interior.pdf"
                saved = make_mockups(
                    folder / "cover.pdf",
                    interior if interior.exists() else None,
                    listing, folder, status_cb=push_mk,
                )
                if saved:
                    st.success(f"✅ {len(saved)} mockups générés dans `mockups/`")
                    st.image([s["file"] for s in saved], width=160)
                    if st.button("🔄 Recharger", key="reload_mockup_pub"):
                        st.rerun()
                else:
                    st.error("❌ Aucun mockup généré (cover.pdf manquant ?)")
            except Exception as e:
                import traceback as _tb
                st.error(f"❌ Erreur : {e}")
                with st.expander("🐛 Traceback"):
                    st.code(_tb.format_exc())

    # ── Handle batch auto-fix request ────────────────────────────────────
    batch_req = st.session_state.pop("autofix_batch", None)
    if batch_req:
        st.markdown("---")
        st.markdown(f"### 🔧🔧 Auto-fix batch ({len(batch_req)} livres)")
        progress = st.progress(0.0)
        log_box = st.empty()
        log_msgs = []
        def push_b(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-25:]), language=None)
        for idx, (slug, strategies) in enumerate(batch_req):
            push_b(f"\n=== [{idx+1}/{len(batch_req)}] {slug} ===")
            try:
                fr = auto_fix_product(
                    product_folder = Path(kdp_root) / slug,
                    anthropic_key  = Config.ANTHROPIC_API_KEY,
                    openai_key     = Config.OPENAI_API_KEY,
                    learning_dir   = Config.LEARNING_DIR,
                    strategies     = strategies,
                    status_cb      = push_b,
                )
                for f in fr.fixes:
                    icon = "✅" if f.success else "❌"
                    push_b(f"  {icon} {f.strategy}: {f.message}")
            except Exception as e:
                push_b(f"  ❌ ERROR: {e}")
            progress.progress((idx + 1) / len(batch_req))
        st.success(f"Batch terminé sur {len(batch_req)} livres")
        if st.button("🔄 Recharger pour voir les nouveaux scores", key="reload_batch"):
            st.rerun()

    # ── Handle auto-fix request ───────────────────────────────────────────
    autofix_req = st.session_state.pop("autofix_request", None)
    if autofix_req:
        st.markdown("---")
        st.markdown(f"### 🔧 Auto-fix : `{autofix_req['slug']}`")
        st.caption(f"Stratégies à appliquer : {', '.join(autofix_req['strategies'])}")
        log_msgs = []
        log_box = st.empty()
        def push_fix(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-20:]), language=None)
        with st.spinner("Corrections en cours…"):
            try:
                fix_report = auto_fix_product(
                    product_folder = Path(autofix_req["folder"]),
                    anthropic_key  = Config.ANTHROPIC_API_KEY,
                    openai_key     = Config.OPENAI_API_KEY,
                    learning_dir   = Config.LEARNING_DIR,
                    strategies     = autofix_req["strategies"],
                    status_cb      = push_fix,
                )
                if fix_report.n_failures == 0:
                    st.success(
                        f"✅ {fix_report.n_successes}/{len(fix_report.fixes)} corrections appliquées"
                    )
                else:
                    st.warning(
                        f"⚠️ {fix_report.n_successes} réussies, {fix_report.n_failures} échouées"
                    )
                for f in fix_report.fixes:
                    icon = "✅" if f.success else "❌"
                    st.caption(f"{icon} **{f.strategy}** — {f.message}")
                if st.button("🔄 Recharger pour voir le nouveau score qualité",
                             key="reload_after_autofix"):
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Erreur auto-fix : {e}")

    # ── Handle category-generation request ───────────────────────────────
    gen_req = st.session_state.pop("gen_cats_request", None)
    if gen_req:
        from modules.publishing.categories_helper import generate_categories_for_listing
        st.markdown("---")
        st.markdown(f"### 🤖 Génération des catégories KDP pour `{gen_req['slug']}`")
        log_msgs = []
        log_box = st.empty()
        def push_cat(msg):
            log_msgs.append(msg)
            log_box.code("\n".join(log_msgs[-15:]), language=None)
        with st.spinner("Claude réfléchit aux meilleures catégories…"):
            try:
                cats = generate_categories_for_listing(
                    listing_path  = Path(gen_req["listing_path"]),
                    anthropic_key = Config.ANTHROPIC_API_KEY,
                    status_cb     = push_cat,
                )
                st.success(f"✅ {len(cats)} catégories ajoutées au listing.json. "
                           f"Recharge pour les voir affichées.")
                if st.button("🔄 Recharger la page", key="reload_after_cats"):
                    st.rerun()
            except Exception as e:
                st.error(f"❌ Échec : {e}")

    # ── Handle manual mark-as-published request ──────────────────────────
    mark_req = st.session_state.pop("kdp_mark_request", None)
    if mark_req:
        slug = mark_req["slug"]
        target = next((p for p in products if p.slug == slug), None)
        if target:
            try:
                new_path = mark_as_published(target, kdp_root)
                st.success(f"📦 Déplacé vers `{new_path}`")
                st.rerun()
            except Exception as e:
                st.error(str(e))


def _render_ads_manager():
    """Amazon Ads (Sponsored Products) campaign builder + ACOS tracker."""
    import pandas as pd
    import json as _json
    from pathlib import Path as _P
    from modules.analytics import ads as _ads

    st.caption("Campagne **exact-match** optimisée petit budget + suivi **ACOS** "
               "automatique (⛔ PAUSE / ✅ Garder).")

    kdp = _P.home() / "Desktop/KDP"
    books = []
    for base in [kdp, kdp / "published"]:
        if base.exists():
            for bdir in sorted(base.iterdir()):
                if bdir.is_dir() and bdir.name != "published" and (bdir / "listing.json").exists():
                    books.append(bdir)
    if not books:
        st.info("Aucun livre trouvé dans ~/Desktop/KDP.")
        return

    def _lbl(i):
        try:
            t = _json.loads((books[i] / "listing.json").read_text(encoding="utf-8"))
        except Exception:
            t = {}
        tag = "  ·  [publié]" if "published" in str(books[i]) else ""
        return f"{(t.get('title') or books[i].name)[:52]}{tag}"

    idx = st.selectbox("📕 Livre à promouvoir", range(len(books)),
                       format_func=_lbl, key="ads_book_sel")
    d = books[idx]
    listing = _json.loads((d / "listing.json").read_text(encoding="utf-8"))

    ck = "ads_camp_state"
    if st.session_state.get(ck + "_slug") != d.name:
        st.session_state[ck] = _ads.load_campaign(d) or _ads.new_campaign(listing)
        st.session_state[ck + "_slug"] = d.name
    campaign = st.session_state[ck]
    # Book-specific widget-key suffix — WITHOUT it, Streamlit keeps the previous
    # book's widget values (table / negatives / ASIN) and corrupts the campaign.
    sfx = d.name

    if st.button("🔄 (Re)générer les mots-clés recommandés", key=f"ads_regen_{sfx}"):
        st.session_state[ck] = _ads.new_campaign(listing)
        st.rerun()

    s = campaign["settings"]
    st.markdown(f"**Réglages recommandés** : {s['type']} · {s['targeting']} · "
                f"budget **{s['daily_budget']}$/jour** · enchère défaut **{s['default_bid']}$**")
    c1, c2 = st.columns(2)
    campaign["budget"] = c1.number_input("Budget total ($)", 5.0, 2000.0,
                                         float(campaign.get("budget", 60)), step=5.0, key=f"ads_budget_{sfx}")
    campaign["royalty"] = c2.number_input("Royalty par vente ($)", 0.5, 30.0,
                                          float(campaign.get("royalty", 3.0)), step=0.1, key=f"ads_roy_{sfx}")

    # ── Pré-remplissage auto depuis un rapport Amazon Ads ────────────────────
    with st.expander("📥 Pré-remplir depuis un rapport Amazon Ads (.xlsx / .csv)", expanded=True):
        st.caption("Exporte depuis Amazon Ads le rapport **« Targeting »** ou "
                   "**« Search term »** (Sponsored Products), puis dépose-le ici : "
                   "Dépense / Clics / Ventes se remplissent tout seuls (par mot-clé).")
        up_ads = st.file_uploader("Rapport Amazon Ads", type=["xlsx", "xlsm", "csv"],
                                  key=f"ads_report_up_{sfx}")
        add_new = st.checkbox("Ajouter aussi les nouveaux mots-clés du rapport "
                              "(qui ont eu des clics)", value=True, key=f"ads_addnew_{sfx}")
        if up_ads is not None and st.button("⚙️ Pré-remplir le tableau", key=f"ads_prefill_{sfx}"):
            report, err = _ads.parse_ads_report(up_ads, filename=up_ads.name)
            if err:
                st.error(f"❌ {err}")
            elif not report:
                st.warning("Aucune ligne exploitable trouvée dans ce fichier.")
            else:
                n_up, n_add = _ads.merge_report(campaign, report, add_new=add_new)
                st.session_state[ck] = campaign
                st.success(f"✅ {n_up} mot(s)-clé(s) mis à jour"
                           + (f" · {n_add} nouveau(x) ajouté(s)" if n_add else "")
                           + f" (sur {len(report)} lignes lues).")
                st.rerun()

    st.markdown("#### ✏️ Mots-clés & suivi (remplis Dépense / Clics / Ventes)")
    df = pd.DataFrame(campaign["rows"]) if campaign["rows"] else \
        pd.DataFrame(columns=["keyword", "bid", "spend", "clicks", "orders"])
    df = df.rename(columns={"keyword": "Mot-clé", "bid": "Enchère", "spend": "Dépense",
                            "clicks": "Clics", "orders": "Ventes"})
    try:
        edited = st.data_editor(
            df, use_container_width=True, num_rows="dynamic", key=f"ads_editor_{sfx}",
            column_config={
                "Enchère": st.column_config.NumberColumn(format="%.2f", step=0.05),
                "Dépense": st.column_config.NumberColumn(format="%.2f", step=0.5),
                "Clics": st.column_config.NumberColumn(step=1),
                "Ventes": st.column_config.NumberColumn(step=1),
            })
    except Exception:
        edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", key=f"ads_editor2_{sfx}")
    campaign["rows"] = [
        {"keyword": str(r["Mot-clé"]).strip(), "bid": float(r.get("Enchère") or 0),
         "spend": float(r.get("Dépense") or 0), "clicks": int(r.get("Clics") or 0),
         "orders": int(r.get("Ventes") or 0)}
        for _, r in edited.iterrows() if str(r.get("Mot-clé") or "").strip()]

    roy = campaign["royalty"]
    disp = []
    for r in campaign["rows"]:
        comp = _ads.compute_row(r, roy)
        disp.append({"Mot-clé": r["keyword"], "Dépense $": r["spend"], "Ventes": r["orders"],
                     "Revenu $": comp["revenue"],
                     "ACOS": (f"{comp['acos']*100:.0f}%" if comp["acos"] is not None else "—"),
                     "Décision": comp["decision"]})
    if disp:
        st.markdown("#### 🧮 Décision automatique")
        st.dataframe(pd.DataFrame(disp), use_container_width=True, hide_index=True)

    tot = _ads.totals(campaign)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Dépensé", f"${tot['spend']}")
    m2.metric("Ventes (pub)", tot["orders"])
    m3.metric("ACOS global", f"{tot['acos']*100:.0f}%" if tot["acos"] is not None else "—")
    m4.metric("Budget restant", f"${tot['remaining']}")

    b1, b2, b3 = st.columns(3)
    if b1.button("💾 Enregistrer le suivi", type="primary", key=f"ads_save_{sfx}"):
        _ads.save_campaign(d, campaign)
        st.success("✅ Suivi enregistré dans le dossier du livre (ads_campaign.json).")
    if b2.button("📊 Exporter en Excel", key=f"ads_xls_{sfx}"):
        p = _ads.export_xlsx(d, campaign, d.name)
        st.success(f"✅ Excel créé : {p}") if p else st.error("Export impossible (openpyxl manquant).")
    if b3.button("📋 Voir/copier les mots-clés", key=f"ads_copy_{sfx}"):
        st.code("\n".join(r["keyword"] for r in campaign["rows"]) or "—")

    # ── 📜 Historique des saisies (par livre) ────────────────────────────────
    hist = _ads.load_history(d)
    with st.expander(f"📜 Historique — {len(hist)} enregistrement(s)", expanded=False):
        if not hist:
            st.caption("Aucun historique encore. Chaque clic sur « 💾 Enregistrer le suivi » "
                       "crée un **point daté** ici (évolution dépense / ventes / ACOS dans le temps).")
        else:
            hdf = pd.DataFrame([{
                "Date": h["ts"].replace("T", " ")[:16],
                "Dépensé $": h["totals"]["spend"],
                "Ventes": h["totals"]["orders"],
                "Revenu $": h["totals"]["revenue"],
                "ACOS": (f"{h['totals']['acos']*100:.0f}%"
                         if h["totals"].get("acos") is not None else "—"),
                "Restant $": h["totals"]["remaining"],
            } for h in hist])
            st.dataframe(hdf, use_container_width=True, hide_index=True)
            try:
                cdf = pd.DataFrame([{
                    "Date": h["ts"].replace("T", " ")[:16],
                    "Dépensé": h["totals"]["spend"],
                    "Ventes": h["totals"]["orders"],
                } for h in hist]).set_index("Date")
                st.line_chart(cdf)
            except Exception:
                pass
            kw_opts = sorted({r["keyword"] for h in hist for r in h.get("rows", [])})
            if kw_opts:
                sel_kw = st.selectbox("📈 Évolution d'un mot-clé", kw_opts, key=f"ads_kw_hist_{sfx}")
                kh = _ads.keyword_history(d, sel_kw)
                if kh and len(kh) >= 2:
                    kdf = pd.DataFrame([{
                        "Date": x["ts"].replace("T", " ")[:16],
                        "Dépense": x["spend"], "Clics": x["clicks"], "Ventes": x["orders"],
                    } for x in kh]).set_index("Date")
                    st.line_chart(kdf)
                elif kh:
                    st.caption("Un seul point pour l'instant — enregistre à nouveau plus tard "
                               "pour voir la courbe d'évolution.")

    st.markdown("**🚫 Mots-clés négatifs (Amazon)** — bloquent les recherches où l'acheteur "
                "veut **autre chose que ton livre** (l'appareil, les accessoires, un complément, "
                "une autre méthode). À coller dans Amazon Ads → *Negative keywords* (negative phrase).")
    cneg1, cneg2 = st.columns([3, 2])
    if cneg2.button("🤖 Négatifs intelligents (IA, mis en cache)", key=f"ads_smartneg_{sfx}"):
        prg = st.empty()
        with st.spinner("Génération IA (Claude)…"):
            negs, nsrc = _ads.smart_negatives(
                listing, Config.ANTHROPIC_API_KEY, cache_dir=Config.LEARNING_DIR,
                refresh=False, status_cb=lambda m: prg.caption(m))
        if negs:
            campaign["negatives"] = negs
            st.session_state[ck] = campaign
            st.success(f"✅ {len(negs)} négatifs Amazon générés ({nsrc}).")
            st.rerun()
        else:
            st.warning("Aucun négatif généré (clé API ?).")
    neg_txt = cneg1.text_area(
        "Un mot-clé négatif par ligne (modifiable)",
        value="\n".join(campaign.get("negatives", [])), height=160, key=f"ads_negs_{sfx}",
        help="Ex. pour un cookbook air fryer : « air fryer machine », « air fryer basket », "
             "« protein powder », « slow cooker »… (PAS free/pdf/youtube — c'est du Google, pas Amazon).")
    campaign["negatives"] = [n.strip() for n in neg_txt.splitlines() if n.strip()]
    st.caption("💡 « Négatifs intelligents » = 1 appel IA (Haiku) mis en cache par niche → gratuit ensuite. "
               "Enregistre pour conserver ta liste.")

    # ── 🎯 ASIN concurrents (Product Targeting) — réutilise le déjà-scrapé ────
    with st.expander("🎯 ASIN concurrents (Product Targeting)", expanded=False):
        st.caption("Cible les **livres concurrents les plus demandés** en Product Targeting. "
                   "Par défaut, réutilise ce qui est **déjà scrapé** (0 coût) ; ne scrape "
                   "Amazon **que** si tu cliques « Rafraîchir ».")
        top_kws = [r["keyword"] for r in campaign["rows"][:3]]
        asins, src = _ads.get_competitor_asins(d, top_kws, listing, Config.LEARNING_DIR,
                                               refresh=False)
        st.caption(f"Source : **{src}** · {len(asins)} ASIN")
        kw_search = st.text_area("Mots-clés pour le rafraîchissement (un par ligne, max 5)",
                                 value="\n".join(top_kws), height=80, key=f"ads_asin_kws_{sfx}")
        c_ref1, c_ref2 = st.columns([2, 1])
        n_per = c_ref2.slider("Résultats/kw", 5, 20, 12, key=f"ads_asin_n_{sfx}")
        if c_ref1.button("🔄 Rafraîchir depuis Amazon (scraper 1 fois, puis mis en cache)",
                         key=f"ads_asin_go_{sfx}"):
            kws = [k.strip() for k in kw_search.splitlines() if k.strip()][:5]
            if not kws:
                st.warning("Ajoute au moins un mot-clé.")
            else:
                prog = st.empty()
                with st.spinner("Scraping Amazon (30-90 s)…"):
                    try:
                        asins, src2 = _ads.get_competitor_asins(
                            d, kws, listing, Config.LEARNING_DIR, refresh=True,
                            status_cb=lambda m: prog.caption(m))
                    except Exception as _ee:
                        asins, src2 = [], "erreur"
                        st.error(f"Échec du scraping : {str(_ee)[:100]}")
                if asins:
                    st.success(f"✅ {len(asins)} ASIN ({src2}). Réutilisés automatiquement "
                               "ensuite — plus besoin de re-scraper.")
                else:
                    st.warning("Aucun ASIN (Amazon a peut-être temporisé — réessaie plus tard).")
        if asins:
            adf = pd.DataFrame([{
                "ASIN": a["asin"], "Titre": (a.get("title") or "")[:55],
                "Avis": a.get("reviews", 0), "Note": a.get("rating") or "—",
                "Prix $": a.get("price") or "—", "Via": a.get("keyword", ""),
            } for a in asins])
            st.dataframe(adf, use_container_width=True, hide_index=True)
            st.markdown("**📋 ASIN à coller dans Amazon Ads → Product Targeting :**")
            st.code("\n".join(a["asin"] for a in asins))
        else:
            st.caption("Aucun ASIN en cache pour ce livre — clique « Rafraîchir » une fois.")

    with st.expander("📏 Règles à respecter (petit budget)", expanded=False):
        for r in _ads.RULES:
            st.markdown(f"- {r}")
    st.info("⚠️ Ne lance la pub que si le **compte est ACTIF** et le livre a **quelques avis**. "
            "Ce budget = **test** pour trouver 2-3 mots-clés gagnants, puis réinvestis les gains.")


def page_analytics():
    _show_global_batch_banner()
    st.markdown('<div class="kdp-header"><h1>📊 Module 4 — Analytics</h1>'
                '<p>Ventes & royalties KDP · publicité (Ads) · import du rapport officiel</p></div>',
                unsafe_allow_html=True)

    # ── 📣 Publicité (Amazon Ads) ─────────────────────────────────────────────
    with st.expander("📣 Publicité — Amazon Ads (campagne + suivi ACOS)", expanded=True):
        _render_ads_manager()
    st.divider()
    st.markdown("### 📈 Ventes & Royalties (rapport KDP)")

    from modules.analytics.kdp_import import import_kdp_file, load_sales
    from modules.analytics import reports as _rep
    import pandas as _pd
    from pathlib import Path as _P

    adir = Config.ANALYTICS_DIR

    # ── How-to + upload ──────────────────────────────────────────────────────
    with st.expander("❓ Comment obtenir mon rapport KDP", expanded=False):
        st.markdown(
            "1. Va sur **kdp.amazon.com** → menu **Reports**\n"
            "2. Onglet **Prior months' royalties** (ou **Dashboard**)\n"
            "3. Clique **Download** → tu obtiens un fichier `.xlsx`\n"
            "4. Glisse ce fichier ci-dessous. Ré-importer le même fichier ne crée pas de doublons."
        )

    up = st.file_uploader("📥 Importer un rapport KDP (.xlsx ou .csv)",
                          type=["xlsx", "xlsm", "csv"], key="kdp_upload")
    if up is not None and st.button("🚀 Importer ce rapport", key="kdp_do_import", type="primary"):
        tmp = adir / "_uploads"
        tmp.mkdir(parents=True, exist_ok=True)
        dest = tmp / up.name
        dest.write_bytes(up.getbuffer())
        with st.spinner("Analyse du rapport…"):
            res = import_kdp_file(dest, adir)
        if res["warnings"]:
            for w in res["warnings"]:
                st.warning(w)
        if res["added"] or res["parsed_rows"]:
            st.success(
                f"✅ {res['added']} nouvelle(s) ligne(s) importée(s) "
                f"({res['skipped']} doublon(s) ignoré(s)) · "
                f"{res['matched']}/{res['parsed_rows']} lignes liées à tes livres · "
                f"feuilles : {', '.join(res['sheets_used']) or '—'}"
            )
        else:
            st.error("Aucune donnée exploitable trouvée dans ce fichier.")

    rows = load_sales(adir)
    if not rows:
        st.info("📭 Aucune donnée encore. Importe ton premier rapport KDP ci-dessus "
                "pour voir tes ventes, royalties et tendances.")
        return

    # ── Overview KPIs ────────────────────────────────────────────────────────
    ov = _rep.overview(rows)
    st.markdown("### 📈 Vue d'ensemble")
    roy_str = "  ·  ".join(f"**{v:.2f} {k}**" for k, v in ov["royalty_by_currency"].items()) or "—"
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Unités nettes vendues", ov["total_net_units"])
    k2.metric("Titres avec ventes", ov["n_titles"])
    k3.metric("Remboursements", ov["total_refunds"])
    k4.metric("Période", f"{ov['first_month']} → {ov['last_month']}")
    st.markdown(f"💰 **Royalties totales** : {roy_str}")

    # ── Monthly trend ────────────────────────────────────────────────────────
    months = _rep.by_month(rows)
    if len(months) >= 2:
        st.markdown("### 🗓️ Tendance mensuelle")
        dfm = _pd.DataFrame([{
            "Mois": m["month"],
            "Unités": m["net_units"],
            f"Royalties ({m['currency_primary']})": m["royalty_primary"],
        } for m in months]).set_index("Mois")
        st.line_chart(dfm)

    # ── Movers (rising / falling) ────────────────────────────────────────────
    mv = _rep.movers(rows)
    if mv["rising"] or mv["falling"]:
        cmv1, cmv2 = st.columns(2)
        with cmv1:
            st.markdown("#### 🚀 En accélération")
            if mv["rising"]:
                for e in mv["rising"][:5]:
                    st.markdown(f"- `{e['key'][:40]}` **+{e['delta']}** "
                                f"({e['prev']}→{e['last']} en {e['last_month']})")
            else:
                st.caption("Aucun livre en hausse ce mois.")
        with cmv2:
            st.markdown("#### 📉 En baisse")
            if mv["falling"]:
                for e in mv["falling"][:5]:
                    st.markdown(f"- `{e['key'][:40]}` **{e['delta']}** "
                                f"({e['prev']}→{e['last']} en {e['last_month']})")
            else:
                st.caption("Aucun livre en baisse.")
        if mv["rising"]:
            st.info("💡 Les livres en accélération sont les candidats idéaux pour une "
                    "campagne PPC (Wave 4) — ils vendent déjà en organique.")

    # ── Per-book table ───────────────────────────────────────────────────────
    st.markdown("### 📚 Performance par livre")
    bb = _rep.by_book(rows)
    dfb = _pd.DataFrame([{
        "Livre": b["title"][:45],
        "Unités nettes": b["net_units"],
        "Remb.": b["refunds"],
        "Royalties": b["royalty_str"],
        "Marchés": ", ".join(b["marketplaces"][:3]),
        "Lié": "✅" if b["slug"] else "⚠️ non lié",
    } for b in bb])
    st.dataframe(dfb, use_container_width=True, hide_index=True)
    n_unmatched = sum(1 for b in bb if not b["slug"])
    if n_unmatched:
        st.caption(f"⚠️ {n_unmatched} livre(s) du rapport non liés à un livre local "
                   "(titre KDP différent, ou livre publié hors de cette app).")

    # ── Marketplace breakdown ────────────────────────────────────────────────
    with st.expander("🌍 Répartition par marketplace"):
        for mk in _rep.by_marketplace(rows):
            st.markdown(f"- **{mk['marketplace']}** : {mk['net_units']} unités · {mk['royalty_str']}")

    # ── Reset ────────────────────────────────────────────────────────────────
    with st.expander("🗑️ Gérer les données"):
        st.caption(f"{ov['n_rows']} ligne(s) stockées dans `output/analytics/sales.jsonl`")
        if st.button("Effacer toutes les données analytics", key="kdp_reset"):
            p = adir / "sales.jsonl"
            if p.exists():
                p.unlink()
            st.success("Données effacées. Recharge la page.")


def page_settings():
    _show_global_batch_banner()
    st.markdown('<div class="kdp-header"><h1>⚙️ Settings</h1><p>Configuration API</p></div>',unsafe_allow_html=True)
    c1,c2 = st.columns(2)
    with c1:
        st.markdown("### Statut API")
        st.success("✅ Anthropic (Claude AI)") if Config.has_anthropic() else st.error("❌ Anthropic API manquante")
        st.success("✅ OpenAI (DALL-E)") if Config.has_openai() else st.info("➖ OpenAI optionnel")
    with c2:
        st.markdown("### Fichier `.env`")
        st.code("# KDP Automation/.env\nANTHROPIC_API_KEY=sk-ant-...\nOPENAI_API_KEY=sk-...    # optionnel")
    st.markdown("---")
    with st.expander("🤖 Obtenir clé Anthropic"):
        st.markdown("1. **console.anthropic.com** → compte → **API Keys** → Create\n2. Coller dans `.env` → redémarrer l'app")
    with st.expander("🎨 Obtenir clé OpenAI (optionnel)"):
        st.markdown("1. **platform.openai.com** → **API Keys** → Create\n2. Coller dans `.env` → redémarrer")
    st.markdown("`Ctrl+C` → `streamlit run app.py`")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    Config.validate()
    # ── One-time housekeeping per Streamlit session ──
    if "_housekeeping_done" not in st.session_state:
        try:
            from modules.quality.housekeeping import run_housekeeping
            stats = run_housekeeping(Path("."), Config.LEARNING_DIR)
            if any(v for v in stats.values()):
                logger.info(f"Housekeeping: {stats}")
        except Exception as e:
            logger.debug(f"Housekeeping skipped: {e}")
        st.session_state["_housekeeping_done"] = True
    with st.sidebar:
        st.markdown("""
        <div style="text-align:center;padding:15px 0 5px;">
            <div style="font-size:34px;">📚</div>
            <div style="font-size:15px;font-weight:700;color:#2C3E50;">KDP Automation</div>
            <div style="font-size:10px;color:#888;">v2.0 — 4 modes de scan</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("---")
        page = st.radio("Nav",
            ["🔍  Research","✏️  Creation","🧠  Intelligence","📤  Publishing","📊  Analytics","⚙️  Settings"],
            label_visibility="collapsed")
        st.markdown("---")
        st.caption("API Status")
        st.markdown(
            ("✅ Anthropic" if Config.has_anthropic() else "⚠️ Anthropic")
            +"  |  "+
            ("✅ OpenAI" if Config.has_openai() else "➖ OpenAI")
        )

    if   "Research"     in page: page_research()
    elif "Creation"     in page: page_creation()
    elif "Intelligence" in page: page_intelligence()
    elif "Publishing" in page: page_publishing()
    elif "Analytics"  in page: page_analytics()
    elif "Settings"   in page: page_settings()

if __name__ == "__main__":
    main()
