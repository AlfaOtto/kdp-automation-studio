"""
Génère le guide PDF complet de l'app KDP Automation.
Sortie : ~/Desktop/KDP/Tuto/Guide_KDP_Automation.pdf
"""

from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, HRFlowable, KeepTogether
)
from reportlab.platypus.flowables import Flowable

# ── Couleurs ──────────────────────────────────────────────────────────────────
BLEU_TITRE   = colors.HexColor("#1a237e")
BLEU_SECTION = colors.HexColor("#283593")
BLEU_SOUS    = colors.HexColor("#3949ab")
BLEU_CLAIR   = colors.HexColor("#e8eaf6")
BLEU_MEDIUM  = colors.HexColor("#c5cae9")
VERT         = colors.HexColor("#2e7d32")
VERT_CLAIR   = colors.HexColor("#e8f5e9")
ORANGE       = colors.HexColor("#e65100")
ORANGE_CLAIR = colors.HexColor("#fff3e0")
ROUGE        = colors.HexColor("#c62828")
ROUGE_CLAIR  = colors.HexColor("#ffebee")
GRIS_TEXTE   = colors.HexColor("#212121")
GRIS_CLAIR   = colors.HexColor("#f5f5f5")
BLANC        = colors.white
JAUNE_CLAIR  = colors.HexColor("#fffde7")

# ── Styles ────────────────────────────────────────────────────────────────────
def build_styles():
    base = getSampleStyleSheet()
    s = {}

    s["titre_doc"] = ParagraphStyle("titre_doc",
        parent=base["Title"], fontSize=28, textColor=BLANC,
        alignment=TA_CENTER, spaceAfter=8, leading=34)

    s["sous_titre_doc"] = ParagraphStyle("sous_titre_doc",
        parent=base["Normal"], fontSize=13, textColor=BLEU_CLAIR,
        alignment=TA_CENTER, spaceAfter=4, leading=18)

    s["h1"] = ParagraphStyle("h1",
        parent=base["Heading1"], fontSize=18, textColor=BLANC,
        spaceBefore=0, spaceAfter=6, leading=24,
        backColor=BLEU_SECTION, borderPadding=(6, 10, 6, 10))

    s["h2"] = ParagraphStyle("h2",
        parent=base["Heading2"], fontSize=13, textColor=BLEU_TITRE,
        spaceBefore=14, spaceAfter=5, leading=18,
        borderPadding=(2, 0, 2, 0))

    s["h3"] = ParagraphStyle("h3",
        parent=base["Heading3"], fontSize=11, textColor=BLEU_SOUS,
        spaceBefore=10, spaceAfter=3, leading=15)

    s["body"] = ParagraphStyle("body",
        parent=base["Normal"], fontSize=10, textColor=GRIS_TEXTE,
        spaceAfter=6, leading=15, alignment=TA_JUSTIFY)

    s["bullet"] = ParagraphStyle("bullet",
        parent=base["Normal"], fontSize=10, textColor=GRIS_TEXTE,
        spaceAfter=3, leading=14, leftIndent=14, bulletIndent=0)

    s["bullet2"] = ParagraphStyle("bullet2",
        parent=base["Normal"], fontSize=9.5, textColor=GRIS_TEXTE,
        spaceAfter=2, leading=13, leftIndent=28, bulletIndent=14)

    s["code"] = ParagraphStyle("code",
        parent=base["Code"], fontSize=8.5, textColor=BLEU_TITRE,
        spaceAfter=4, leading=12, leftIndent=10,
        backColor=GRIS_CLAIR, borderPadding=(4, 6, 4, 6))

    s["note"] = ParagraphStyle("note",
        parent=base["Normal"], fontSize=9.5, textColor=VERT,
        spaceAfter=4, leading=13, leftIndent=10)

    s["warning"] = ParagraphStyle("warning",
        parent=base["Normal"], fontSize=9.5, textColor=ORANGE,
        spaceAfter=4, leading=13, leftIndent=10)

    s["danger"] = ParagraphStyle("danger",
        parent=base["Normal"], fontSize=9.5, textColor=ROUGE,
        spaceAfter=4, leading=13, leftIndent=10)

    s["toc_h1"] = ParagraphStyle("toc_h1",
        parent=base["Normal"], fontSize=11, textColor=BLEU_TITRE,
        spaceAfter=4, leading=16, fontName="Helvetica-Bold")

    s["toc_h2"] = ParagraphStyle("toc_h2",
        parent=base["Normal"], fontSize=10, textColor=GRIS_TEXTE,
        spaceAfter=2, leading=14, leftIndent=16)

    s["caption"] = ParagraphStyle("caption",
        parent=base["Normal"], fontSize=9, textColor=colors.HexColor("#616161"),
        spaceAfter=6, leading=12, alignment=TA_CENTER)

    return s


# ── Helpers ───────────────────────────────────────────────────────────────────
class ColorBlock(Flowable):
    """Bloc coloré avec titre centré (pour les titres de section)."""
    def __init__(self, text, bg=BLEU_SECTION, fg=BLANC, height=32, fontsize=14):
        super().__init__()
        self.text = text
        self.bg = bg
        self.fg = fg
        self.height = height
        self.fontsize = fontsize
        self.width = 0  # sera défini au wrap

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return availWidth, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg)
        c.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=0)
        c.setFillColor(self.fg)
        c.setFont("Helvetica-Bold", self.fontsize)
        c.drawCentredString(self.width / 2, self.height / 2 - self.fontsize * 0.35, self.text)


class InfoBox(Flowable):
    """Boîte d'information colorée avec icône."""
    def __init__(self, text, kind="info", style_obj=None):
        super().__init__()
        cfg = {
            "info":    (BLEU_CLAIR,   BLEU_TITRE,   "ℹ"),
            "tip":     (VERT_CLAIR,   VERT,         "✅"),
            "warning": (ORANGE_CLAIR, ORANGE,       "⚠"),
            "danger":  (ROUGE_CLAIR,  ROUGE,        "🚫"),
            "cost":    (JAUNE_CLAIR,  colors.HexColor("#f57f17"), "💰"),
        }
        self.bg, self.border, self.icon = cfg.get(kind, cfg["info"])
        self.text = text
        self.kind = kind
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        # Estimation hauteur
        n_lines = max(1, len(self.text) // 90 + self.text.count("\n") + 1)
        self.height = 14 + n_lines * 13 + 8
        return availWidth, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg)
        c.setStrokeColor(self.border)
        c.setLineWidth(1.2)
        c.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=1)
        c.setFillColor(self.border)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(8, self.height - 14, self.icon + "  " + self.text[:200])
        if len(self.text) > 200:
            c.setFont("Helvetica", 9)
            c.drawString(20, self.height - 27, self.text[200:400])


def hr(color=BLEU_MEDIUM, thickness=1):
    return HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=6, spaceBefore=4)


def sp(n=8):
    return Spacer(1, n)


def b(text, s):
    return Paragraph(f"<b>•</b>  {text}", s["bullet"])


def b2(text, s):
    return Paragraph(f"◦  {text}", s["bullet2"])


def tbl(data, col_widths=None, header_bg=BLEU_SECTION, stripe=True):
    """Crée un tableau stylisé."""
    n_cols = len(data[0])
    if col_widths is None:
        col_widths = [14 * cm / n_cols] * n_cols

    style = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR",  (0, 0), (-1, 0), BLANC),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 9),
        ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 1), (-1, -1), 9),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#bdbdbd")),
        ("ALIGN",      (0, 0), (-1, -1), "LEFT"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BLANC, BLEU_CLAIR] if stripe else [BLANC]),
    ]
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle(style))
    return t


# ── Contenu ───────────────────────────────────────────────────────────────────
def build_cover(s):
    story = []
    story.append(sp(40))
    # Grand bloc titre
    story.append(ColorBlock("KDP AUTOMATION", bg=BLEU_TITRE, fg=BLANC, height=70, fontsize=26))
    story.append(sp(6))
    story.append(ColorBlock("Guide complet des fonctionnalités", bg=BLEU_SOUS, fg=BLANC, height=40, fontsize=15))
    story.append(sp(20))
    story.append(Paragraph("Votre assistant pour publier 50 à 200 livres/mois sur Amazon KDP", s["sous_titre_doc"]))
    story.append(sp(10))
    story.append(hr(BLEU_MEDIUM, 2))
    story.append(sp(6))

    modules = [
        ("🔍", "Module 1", "Recherche de niches"),
        ("✏️", "Module 2", "Création de livres"),
        ("✅", "Module 2b", "Contrôle qualité"),
        ("📤", "Module 3", "Publication KDP"),
        ("🧠", "Intelligence", "Dashboard & analytics"),
        ("📚", "Puzzles", "9 types de puzzle books"),
        ("🎯", "SEO Tower", "Optimisation listing"),
        ("📊", "Categories", "Optimiseur de catégories"),
        ("🎯", "ARC Tracker", "Gestion des reviewers"),
        ("🎛️", "Fine-tune", "18 réglages couverture"),
    ]
    data = [["", "Module", "Description"]]
    for icon, mod, desc in modules:
        data.append([icon, mod, desc])
    story.append(tbl(data, col_widths=[1.2*cm, 3.5*cm, 10*cm]))
    story.append(sp(30))
    story.append(Paragraph("Version juin 2026 · Application Streamlit", s["caption"]))
    story.append(PageBreak())
    return story


def build_toc(s):
    story = []
    story.append(ColorBlock("TABLE DES MATIÈRES", bg=BLEU_TITRE, fg=BLANC, height=38, fontsize=15))
    story.append(sp(14))

    sections = [
        ("1.", "Démarrage rapide", [
            "Lancer l'application",
            "Workflow quotidien recommandé",
            "Coûts par livre généré",
        ]),
        ("2.", "Module 1 — Recherche de niches", [
            "Mode Crème (scan automatique)",
            "Résultats enrichis : revenus, densité, tendance",
            "Mode Autopilot",
            "Recherche manuelle",
            "Historique des scans",
        ]),
        ("3.", "Module 2 — Création de livres", [
            "Pipeline de création complet",
            "Sélectionner le format & le papier",
            "Options illustrations IA",
            "Puzzle books : 9 types + activité combo",
            "Design brief adaptatif (Claude)",
        ]),
        ("4.", "Module 2b — Contrôle qualité", [
            "Score de validation 0-100",
            "Problèmes détectés et auto-fix",
            "Auto-améliorer la couverture (3× garde le meilleur)",
            "Deep check couverture (Claude Vision)",
        ]),
        ("5.", "Module 3 — Publication KDP", [
            "Dashboard publications",
            "Éditeur de listing (titre / sous-titre / description / mots-clés)",
            "Fine-tune couverture : 18 réglages + 4 présets",
            "SEO Tower : score + réécriture Claude",
            "Optimiseur de catégories (live Amazon)",
            "ARC Tracker : équipe de reviewers",
            "A+ Content : 5 blocs marketing",
            "Pousser vers KDP (Firefox automatisé)",
        ]),
        ("6.", "Module Intelligence", [
            "Overview KPIs",
            "Performance hebdomadaire",
            "Recommandeur de niches",
            "Market Intel",
            "Combo Graph",
            "Brief compétitif",
            "Keywords Pro",
        ]),
        ("7.", "Système d'apprentissage", [
            "Feedback 👍 👎 ✅",
            "Multi-signal true_quality",
            "Prédicteur avant génération",
            "Transfert cross-niche",
        ]),
        ("8.", "Paramètres & Configuration", []),
        ("9.", "Résolution des problèmes courants", []),
    ]

    for num, title, subs in sections:
        story.append(Paragraph(f"{num}  {title}", s["toc_h1"]))
        for sub in subs:
            story.append(Paragraph(f"    — {sub}", s["toc_h2"]))
        story.append(sp(4))

    story.append(PageBreak())
    return story


def build_demarrage(s):
    story = []
    story.append(ColorBlock("1. DÉMARRAGE RAPIDE", bg=BLEU_TITRE, fg=BLANC, height=38, fontsize=15))
    story.append(sp(10))

    story.append(Paragraph("Lancer l'application", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "Ouvrez un Terminal, copiez-collez ces 2 commandes, puis ouvrez "
        "<b>http://localhost:8501</b> dans votre navigateur.", s["body"]))
    story.append(Paragraph('cd kdp-automation-studio', s["code"]))
    story.append(Paragraph("source venv/bin/activate &amp;&amp; streamlit run app.py", s["code"]))
    story.append(InfoBox("L'app tourne en arrière-plan tant que le Terminal est ouvert. "
                         "Ne pas fermer le Terminal pendant une génération.", "warning"))
    story.append(sp(10))

    story.append(Paragraph("Workflow quotidien recommandé", s["h2"]))
    story.append(hr())

    steps = [
        ("🌅 Matin", "Intelligence → Recommandeur",
         "Voir les 8 niches recommandées du jour avec score prédit. "
         "Cliquer 📋 Copier ces niches dans Création."),
        ("✏️ Génération", "Création → Générer",
         "Ajuster format/papier si besoin. Cliquer 🚀 Générer. "
         "~3 min par livre, la page reste utilisable pendant la génération."),
        ("✅ Qualité", "Publication → Tableau de bord qualité",
         "Cliquer 🔧🔧 Auto-fix TOUS les brouillons en 1 clic. "
         "Corriger les problèmes critiques restants manuellement."),
        ("🎨 Révision", "Publication → carte livre",
         "Vérifier titre, couverture, SEO Tower. Régénérer couverture si nécessaire. "
         "Fine-tuner si besoin (0 coût DALL-E si image déjà générée)."),
        ("📤 Publication", "Publication → Pousser vers KDP",
         "Le bot Firefox remplit les étapes 1 et 2 automatiquement. "
         "Vous choisissez catégories et prix manuellement (étape 3), puis cliquez ✅ Fait."),
        ("📝 Feedback", "Chaque carte livre",
         "Noter 👍 ou 👎. Le système d'apprentissage s'améliore à chaque note."),
    ]

    data = [["Étape", "Où", "Action"]]
    for step, where, action in steps:
        data.append([step, where, action])
    story.append(tbl(data, col_widths=[3*cm, 4.5*cm, 8.5*cm]))
    story.append(sp(12))

    story.append(Paragraph("Coûts par livre généré", s["h2"]))
    story.append(hr())

    cost_data = [
        ["Étape", "Coût estimé", "Temps"],
        ["Listing Claude Sonnet", "~0,03 $", "5 s"],
        ["Optimisation hook (Claude)", "~0,015 $", "3 s"],
        ["Design brief (journal/log/planner)", "~0,015 $", "3 s"],
        ["Expansion contenu (Claude)", "~0,03 $", "5-30 s"],
        ["Icônes + hero IA (1ère fois, puis cache)", "~0,16 $", "30-60 s"],
        ["Pages coloring (par page)", "~0,10 $", "30-60 s"],
        ["Couverture DALL-E (gpt-image-2)", "~0,04 $", "30 s"],
        ["A+ Content (optionnel)", "~0,01 $", "3 s"],
        ["TOTAL livre classique", "≈ 0,30 $", "~3 min"],
        ["Regen couverture seule (cache actif)", "0,00 $", "2 s"],
        ["SEO Tower autocomplete", "Gratuit", "3 s"],
        ["Optimiseur catégories", "~0,005 $", "60-90 s"],
        ["Deep check couverture Vision", "~0,003 $", "5 s"],
        ["ARC emails (4 templates)", "~0,01 $", "3 s"],
    ]
    story.append(tbl(cost_data, col_widths=[8*cm, 3*cm, 3*cm]))
    story.append(sp(4))
    story.append(InfoBox(
        "Pour les puzzle books (sudoku, mazes…), il n'y a pas de coût Claude pour le contenu "
        "— les puzzles sont générés algorithmiquement (0 $). Seuls le listing et la couverture sont facturés.",
        "tip"))
    story.append(PageBreak())
    return story


def build_module1(s):
    story = []
    story.append(ColorBlock("2. MODULE 1 — RECHERCHE DE NICHES", bg=BLEU_TITRE, fg=BLANC, height=38, fontsize=15))
    story.append(sp(10))
    story.append(Paragraph(
        "Le module Recherche trouve des niches Amazon à faible concurrence "
        "avec un potentiel de revenu estimé. Il analyse les résultats Amazon en temps réel "
        "et les note sur 5 critères experts.", s["body"]))
    story.append(sp(6))

    # Mode Crème
    story.append(Paragraph("Mode Crème — Scan automatique 1 clic", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "Le mode Crème parcourt automatiquement <b>114 seeds répartis en 8 catégories</b> "
        "et filtre les meilleures opportunités en 2 phases.", s["body"]))

    cats = [
        ["Catégorie", "Nb seeds", "Exemples"],
        ["📔 Logs santé spécialisés", "12", "nurse log, diabetes tracker…"],
        ["💼 Professions ultra-niche", "12", "electrician log, farmer log…"],
        ["🎨 Hobbies", "14", "birdwatching log, hiking journal…"],
        ["🧩 Quiz & Trivia", "24", "history trivia, movie quiz…"],
        ["🖍️ Coloring adultes", "24", "mandala, botanical, floral…"],
        ["🧒 Coloring enfants/ados", "16", "dinosaur coloring, mermaid…"],
        ["✨ Bizarre/tendance", "12", "ufo sighting log, cryptid tracker…"],
        ["🤖 IA & Workflows tech (2026)", "20", "ai prompt tracker, vibe coding log…"],
    ]
    story.append(tbl(cats, col_widths=[5.5*cm, 2.5*cm, 8*cm]))
    story.append(sp(8))

    story.append(Paragraph("Comment lancer un scan Crème", s["h3"]))
    steps = [
        "Aller dans <b>Recherche → onglet Crème</b>",
        "Ouvrir ⚙️ Paramètres avancés pour ajuster : catégories, max reviews (défaut 25), score min (défaut 60)",
        "Cocher <b>🔬 Mode hyper-niche</b> pour élargir chaque seed vers 2-6 audiences (ex: 'anxiety journal' → 'pour ados', 'pour seniors large print'…)",
        "Cocher <b>🤖 Enrichissement Claude IA</b> pour une analyse narrative des meilleures niches",
        "Cliquer <b>🚀 Lancer le scan Crème</b>",
        "Phase 1 (rapide) : 15 résultats Amazon par seed, filtre avg_reviews ≤ max_reviews",
        "Phase 2 (enrichissement BSR) : ajoute le Best Seller Rank réel sur les survivants",
    ]
    for step in steps:
        story.append(b(step, s))
    story.append(sp(8))

    story.append(Paragraph("Comprendre les résultats enrichis", s["h3"]))
    metrics = [
        ["Métrique", "Ce que ça signifie", "Bon signe"],
        ["💰 Revenu/mois estimé", "Modèle power-law sur le BSR → ventes/jour × prix × 35%", "> 200 $/mois"],
        ["📦 Ventes/mois médiane", "Médiane des ventes estimées des top 15", "> 15/mois"],
        ["🔥 Densité opportunité", "autocomplete_demand / avg_reviews — mesure l'espace libre", "≥ 4.0 = excellent"],
        ["🪪 Pénétration indé", "% des top 10 avec moins de 100 avis (vous pouvez vous y glisser)", "> 50%"],
        ["📈 Tendance", "Comparaison avec le scan précédent sur la même niche", "↑ ou ↗"],
        ["⭐ Score Crème", "Score expert 0-100 : compétition + volume + qualité + indie", "≥ 60"],
    ]
    story.append(tbl(metrics, col_widths=[4*cm, 7*cm, 3*cm]))
    story.append(sp(8))

    story.append(Paragraph("Modes Autopilot, Manuel et Historique", s["h2"]))
    story.append(hr())
    modes = [
        ("<b>Autopilot</b>", "4 sous-modes : Discovery / Trending / Profession / Bizarre. "
         "Plus rapide que Crème (pas de Phase 2 BSR). Idéal pour des idées rapides."),
        ("<b>Manuel</b>", "Saisir un mot-clé unique → 30 résultats Amazon → score expert. "
         "Parfait pour valider une idée spécifique avant de générer."),
        ("<b>Historique</b>", "Liste tous les scans Crème passés (sauvegardés dans output/history/). "
         "Recharger et ré-afficher un scan précédent sans rescanner Amazon."),
    ]
    for title, desc in modes:
        story.append(b(f"{title} — {desc}", s))
    story.append(sp(8))

    story.append(InfoBox(
        "Astuce : après un scan Crème, cochez les niches qui vous intéressent "
        "et cliquez 📋 Envoyer vers Création. Elles s'ajoutent directement à la liste de génération.",
        "tip"))
    story.append(PageBreak())
    return story


def build_module2(s):
    story = []
    story.append(ColorBlock("3. MODULE 2 — CRÉATION DE LIVRES", bg=BLEU_TITRE, fg=BLANC, height=38, fontsize=15))
    story.append(sp(10))
    story.append(Paragraph(
        "Le module Création transforme une niche en livre KDP complet : "
        "listing optimisé, intérieur PDF et couverture. "
        "Tout tourne en arrière-plan — vous pouvez naviguer ailleurs pendant la génération.", s["body"]))
    story.append(sp(6))

    story.append(Paragraph("Pipeline complet (dans l'ordre)", s["h2"]))
    story.append(hr())
    pipeline = [
        ("1", "Détection du type produit", "journal | log | quiz | planner | coloring | puzzle | activity_book"),
        ("2", "Génération listing (Claude Sonnet)", "Titre ≤60 chars, sous-titre, description HTML, 7 mots-clés, 3 catégories, publisher"),
        ("2a", "Vérification anti-stuffing", "Réécrit si titre > 2 virgules/colons ou chevauche les mots-clés"),
        ("2b", "Optimisation hook A/B", "3 variantes → meilleure → remplace l'intro de la description"),
        ("2c", "Design brief adaptatif (Claude)", "Pour journal/log/planner uniquement — tracker fields personnalisés"),
        ("3", "Expansion contenu", "Remplit les sections : prompts d'écriture, colonnes de log, Q&A (5 sous-thèmes × 10 en parallèle)"),
        ("3a", "Preset de template", "Choisit le préset visuel selon la niche"),
        ("4b", "Génération assets IA", "Icônes + hero image (cache — regénère si absent)"),
        ("4c", "Puzzles algorithmiques", "Pour puzzle/activity_book uniquement — déterministe par seed"),
        ("5", "Création intérieur PDF", "ReportLab → interior.pdf (4 layouts rotatifs, gutters dynamiques)"),
        ("6", "Recalibration pages réelles", "Re-lit le PDF généré pour obtenir le vrai nombre de pages (spine précis)"),
        ("6b", "Sync description", "Met à jour 'N pages', 'N puzzles', 'N questions' avec les vrais chiffres"),
        ("7", "Génération couverture DALL-E", "gpt-image-2 → Pillow composite → cover.pdf + cache .cover_front.png"),
        ("8", "Sauvegarde listing.json", "Tous les champs + métadonnées (fingerprint, design brief, preset…)"),
    ]
    data = [["#", "Étape", "Détail"]]
    for num, step, detail in pipeline:
        data.append([num, step, detail])
    story.append(tbl(data, col_widths=[0.8*cm, 5*cm, 10.2*cm]))
    story.append(sp(8))

    story.append(Paragraph("Format & papier KDP", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "Ouvrir l'expander <b>📏 Format & papier KDP</b> dans la page Création "
        "pour personnaliser avant de générer.", s["body"]))

    formats = [
        ["Option", "Défaut", "Choix disponibles"],
        ["Trim size", "6×9\"", "15 formats KDP (5×8, 8.5×11, 8.5×8.5, 7×10…)"],
        ["Type de papier", "white (B&W)", "white · cream · groundwood · color · premium_color"],
        ["Nombre de pages", "Calculé par Claude", "Forcez un nombre précis (24-828)"],
    ]
    story.append(tbl(formats, col_widths=[3*cm, 3.5*cm, 9.5*cm]))
    story.append(sp(4))
    story.append(InfoBox(
        "Le nombre de pages dans la description et le sous-titre est automatiquement "
        "mis à jour avec le vrai nombre de pages du PDF généré. "
        "Vous n'avez pas besoin de le corriger manuellement.", "tip"))
    story.append(sp(8))

    story.append(Paragraph("Types de produits", s["h2"]))
    story.append(hr())
    types = [
        ["Type", "Contenu intérieur", "Spécificités"],
        ["journal", "Prompts d'écriture niche-spécifiques", "Design brief + 4 layouts rotatifs + tracker"],
        ["log", "Colonnes de tableau personnalisées (Claude)", "Design brief → headers adaptés à la niche"],
        ["planner", "Blocs quotidiens + revue hebdo", "4 layouts A/B/C/D + wellness + focus"],
        ["quiz", "Q&A avec sous-thèmes parallèles", "5 sous-thèmes × 10 Q&A simultanés"],
        ["coloring", "Pages de coloriage IA", "Grayscale, traits ≥2.5pt, atmosphères niche"],
        ["puzzle", "1 type de puzzle algorithmique", "Déterministe, solutions en fin de livre"],
        ["activity_book", "Mix 5 types de puzzles", "40% sudoku, 25% wordsearch, 15% crypto…"],
    ]
    story.append(tbl(types, col_widths=[2.5*cm, 5.5*cm, 8*cm]))
    story.append(sp(8))

    story.append(Paragraph("Puzzle books — 9 types disponibles", s["h2"]))
    story.append(hr())
    puzzles = [
        ["Type", "Description", "Solutions incluses"],
        ["mazes", "Labyrinthes ASCII + graphiques", "✅"],
        ["sudoku", "Grilles 4×4 à 9×9 selon la difficulté", "✅"],
        ["wordsearch", "Grilles de mots cachés avec liste", "✅"],
        ["cryptogram", "Phrases chiffrées à déchiffrer", "✅"],
        ["logic_grid", "Puzzles de logique (qui fait quoi)", "✅"],
        ["nonogram", "Picross / Hanjie (pixels à coloriage)", "✅"],
        ["kakuro", "Mots croisés numériques", "✅"],
        ["kenken", "Sudoku + opérations arithmétiques", "✅"],
        ["dot_to_dot", "Relier les points 1→N", "❌ (pas besoin)"],
    ]
    story.append(tbl(puzzles, col_widths=[3*cm, 9*cm, 4*cm]))
    story.append(sp(6))

    story.append(Paragraph("Options de difficulté", s["h3"]))
    diffs = [
        ["Mode", "Progression"],
        ["easy / medium / hard / expert", "Tous les puzzles au même niveau"],
        ["gradient (easy→expert)", "25% facile → 30% moyen → 30% difficile → 15% expert"],
        ["warmup (facile puis base)", "20% faciles pour s'échauffer, puis difficulté de base"],
        ["mixed (aléatoire)", "Mélange aléatoire de tous les niveaux"],
    ]
    story.append(tbl(diffs, col_widths=[6*cm, 10*cm]))
    story.append(sp(4))
    story.append(InfoBox(
        "Volume # : générer plusieurs volumes (Vol. 1, Vol. 2…) avec des puzzles "
        "différents. Le seed change automatiquement selon le numéro de volume — "
        "impossible d'avoir 2 fois les mêmes puzzles.", "tip"))
    story.append(PageBreak())
    return story


def build_module_qualite(s):
    story = []
    story.append(ColorBlock("4. MODULE 2b — CONTRÔLE QUALITÉ", bg=BLEU_TITRE, fg=BLANC, height=38, fontsize=15))
    story.append(sp(10))
    story.append(Paragraph(
        "Chaque livre généré est automatiquement noté sur 100. "
        "Les problèmes sont catégorisés par sévérité et la plupart sont corrigibles en 1 clic.", s["body"]))
    story.append(sp(6))

    story.append(Paragraph("Score de validation 0-100", s["h2"]))
    story.append(hr())
    checks = [
        ["Critère vérifié", "Sévérité si échec", "Auto-fixable"],
        ["Fichiers présents (listing.json, interior.pdf, cover.pdf)", "Critique", "❌"],
        ["Titre 10-200 chars", "Critique", "✅ regen_listing"],
        ["Titre stuffé (trop de virgules/colons)", "Critique", "✅ regen_listing"],
        ["Description 200-4000 chars + HTML valide", "Warning/Critique", "✅ regen_listing"],
        ["7 mots-clés exacts, ≤50 chars, sans doublons", "Critique", "✅ fix_keywords"],
        ["3 catégories, 1 primaire, format 'A > B > C'", "Warning", "✅ gen_categories"],
        ["Nombre pages intérieur ±25% vs listing", "Warning", "✅ regen_interior"],
        ["Dimensions couverture correspondent au trim/spine", "Critique si >0.1\"", "✅ regen_cover"],
        ["Lisibilité miniature couverture (contraste titre)", "Warning", "✅ regen_cover"],
        ["Signal genre couverture (Deep Check Vision)", "Warning", "✅ regen_cover"],
    ]
    story.append(tbl(checks, col_widths=[8.5*cm, 3*cm, 4.5*cm]))
    story.append(sp(8))

    story.append(Paragraph("Utiliser l'auto-fix", s["h2"]))
    story.append(hr())
    story.append(b("Dans la page <b>Publication → 🎯 Tableau de bord qualité</b>", s))
    story.append(b("Bouton <b>🔧🔧 Auto-fix TOUS les brouillons</b> — corrige tout ce qui est corrigible en 1 clic", s))
    story.append(b("Ou par livre : bouton <b>🔧 Auto-fix</b> dans la carte du livre", s))
    story.append(sp(6))

    story.append(Paragraph("Stratégies de correction", s["h3"]))
    strategies = [
        ["Stratégie", "Déclenche quand", "Action"],
        ["gen_categories", "Catégories manquantes", "Claude génère 3 catégories KDP"],
        ["fix_keywords", "< 7 mots-clés ou doublons", "Claude rééquilibre + complète"],
        ["infer_page_count", "Listing.page_count ne correspond pas", "Lit le vrai PDF"],
        ["regen_listing", "Titre/desc/keywords hors spec", "Regénère tout le listing Claude"],
        ["regen_interior", "Intérieur corrompu ou manquant", "Recrée interior.pdf"],
        ["regen_cover", "Couverture hors dimensions ou illisible", "Recrée cover.pdf + DALL-E"],
    ]
    story.append(tbl(strategies, col_widths=[3.5*cm, 5*cm, 7.5*cm]))
    story.append(sp(8))

    story.append(Paragraph("Auto-améliorer la couverture", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "Le bouton <b>🔄 Auto-améliorer cover</b> régénère la couverture jusqu'à 3 fois "
        "et conserve automatiquement la version avec le meilleur score visuel.", s["body"]))
    story.append(b("Toutes les tentatives sont sauvegardées dans <b>.cover_candidates/</b>", s))
    story.append(b("Le bouton <b>🎨 Cover A/B test</b> apparaît quand ≥2 candidats existent", s))
    story.append(b("Choisir un candidat enregistre un événement d'apprentissage (cover_picked)", s))
    story.append(sp(6))

    story.append(Paragraph("Deep Check couverture (Claude Vision)", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "Le bouton <b>🔬 Deep check cover</b> envoie une image de la couverture à "
        "Claude Haiku Vision (~0,003 $). Il vérifie :", s["body"]))
    story.append(b("Le genre est-il immédiatement reconnaissable depuis la miniature Amazon ?", s))
    story.append(b("Le titre est-il lisible à petite taille ?", s))
    story.append(b("Les couleurs et le style correspondent-ils à la niche ?", s))
    story.append(b("Score 0-100 + critique textuelle + verdict OK/À regénérer", s))
    story.append(PageBreak())
    return story


def build_module_publishing(s):
    story = []
    story.append(ColorBlock("5. MODULE 3 — PUBLICATION KDP", bg=BLEU_TITRE, fg=BLANC, height=38, fontsize=15))
    story.append(sp(10))
    story.append(Paragraph(
        "Le module Publication affiche tous vos brouillons, vous permet de les affiner, "
        "et automatise la saisie du formulaire KDP via Firefox. "
        "Vous gardez le contrôle sur le login, les catégories et le prix.", s["body"]))
    story.append(sp(6))

    story.append(Paragraph("Dashboard des publications", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "La page Publication scanne automatiquement <b>~/Desktop/KDP/</b> "
        "et affiche chaque livre sous forme de carte.", s["body"]))
    story.append(b("<b>Brouillons</b> : ~/Desktop/KDP/{slug}/", s))
    story.append(b("<b>Publiés</b> : ~/Desktop/KDP/published/{slug}/", s))
    story.append(b("Badge de statut toujours visible en haut : PRÊT / EN COURS / TERMINÉ / ERREUR", s))
    story.append(sp(8))

    story.append(Paragraph("Carte d'un livre — contenu (de haut en bas)", s["h2"]))
    story.append(hr())
    items = [
        ("1. Vignette + méta", "Couverture miniature, niche, type, pages, trim, papier. "
         "Alerte ⚠️ si pages réelles ≠ listing."),
        ("2. 📂 Ouvrir le dossier", "Ouvre le dossier Finder du livre."),
        ("3. ✏️ Éditeur de listing", "Modifier titre, sous-titre, description, 7 mots-clés. "
         "Badge 'Modifié' si changements non sauvegardés. "
         "Bouton 💾 Sauvegarder et 🎨 Sauv + Régén cover."),
        ("4. 🎨 Cover A/B test", "Visible si ≥2 candidats. Choisir la meilleure version."),
        ("5. Boutons regen", "🔄 Auto-améliorer · 📄 Régénérer intérieur · 🔧 Fix dimensions"),
        ("6. 🎛️ Fine-tune cover", "18 réglages + 4 présets (voir section dédiée ci-dessous)."),
        ("7. 🎯 SEO Tower", "Score SEO + grade + détails par zone + rewrite Claude."),
        ("8. 🎯 Qualité & Auto-fix", "Score 0-100 + liste problèmes + bouton auto-fix."),
        ("9. 📁 Catégories KDP", "Affiche les 3 catégories + bouton Optimiser (live Amazon)."),
        ("10. 🔑 Mots-clés", "Affiche les 7 mots-clés actuels."),
        ("11. 🎯 ARC Tracker", "Gestion des reviewers ARC (voir section dédiée)."),
        ("12. ✨ A+ Content", "5 blocs marketing prêts à copier-coller."),
        ("13. 🔬 Deep check cover", "Analyse Claude Vision (optionnel, ~0,003 $)."),
        ("14. 📤 Pousser vers KDP", "Lance le bot Firefox. Ou ✅ Marquer publié manuellement."),
        ("15. 👍 👎 ✅ Feedback", "Note le livre pour améliorer le système d'apprentissage."),
    ]
    for num_title, desc in items:
        story.append(KeepTogether([
            b(f"<b>{num_title}</b> — {desc}", s),
        ]))
    story.append(sp(8))

    # Fine-tune
    story.append(Paragraph("Fine-tune couverture — 18 réglages", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "L'expander <b>🎛️ Fine-tune cover</b> permet de recomposer la couverture "
        "instantanément sans rappeler DALL-E (0 $ · 2 secondes). "
        "L'image front est mise en cache la première fois.", s["body"]))

    overrides = [
        ["Zone", "Réglage", "Valeurs", "Effet"],
        ["Front", "title_size_mult", "0.4 → 1.5", "Taille du titre"],
        ["Front", "title_y_offset_pct", "-15% → +15%", "Position verticale titre"],
        ["Front", "title_color", "white / black / auto", "Couleur texte titre"],
        ["Front", "subtitle_size_mult", "0.5 → 1.5", "Taille sous-titre"],
        ["Front", "subtitle_visible", "Oui / Non", "Afficher/cacher sous-titre"],
        ["Front", "band_height_pct", "20% → 40%", "Hauteur de la bande du bas"],
        ["Front", "fade_strength", "5% → 45%", "Intensité du fondu image→bande"],
        ["Spine", "spine_padding_in", "0.375\" → 0.8\"", "Marge sécurité KDP"],
        ["Spine", "spine_visible", "Oui / Non", "Afficher texte sur le dos"],
        ["Spine", "spine_text_color", "white / black / auto", "Couleur texte dos"],
        ["Spine", "publisher_size_mult", "0.5 → 2.0", "Taille logo éditeur"],
        ["Back", "back_frame_visible", "Oui / Non", "Cadre décoratif 4ème de couv"],
        ["Back", "back_watermark_alpha", "0% → 30%", "Transparence watermark"],
        ["Back", "back_description_visible", "Oui / Non", "Texte 4ème de couv"],
        ["Back", "back_title_visible", "Oui / Non", "Titre 4ème de couv"],
        ["Typo", "font_pool", "auto/serif/sans/display/script/hand/fantasy", "Famille de polices"],
        ["Couleurs", "band_color / spine_color / back_color", "#RRGGBB ou auto", "3 color pickers"],
    ]
    story.append(tbl(overrides, col_widths=[1.8*cm, 4.5*cm, 4.5*cm, 5.2*cm]))
    story.append(sp(6))

    story.append(Paragraph("4 Présets rapides", s["h3"]))
    presets = [
        ["Préset", "Ce qu'il fait"],
        ["⚙️ Défauts", "Réinitialise tous les réglages aux valeurs par défaut"],
        ["📛 Big title", "title_size ×1.30, title_y −3%, band 35% — pour titres courts percutants"],
        ["🌫️ Minimal back", "Désactive le cadre + watermark 5% — design épuré"],
        ["🦴 KDP-safe spine", "spine_padding 0.55\" — marge de sécurité maximale pour le dos"],
    ]
    story.append(tbl(presets, col_widths=[3.5*cm, 12.5*cm]))
    story.append(sp(8))

    # Publication Firefox
    story.append(Paragraph("Pousser vers KDP — Bot Firefox", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "Le bouton <b>📤 Pousser vers KDP</b> lance Firefox et remplit automatiquement "
        "les étapes 1 et 2 du formulaire KDP. Vous intervenez uniquement pour les catégories et le prix.", s["body"]))

    etapes = [
        ["Étape KDP", "Ce que fait le bot", "Votre rôle"],
        ["Étape 1 — Détails", "Titre, sous-titre, auteur, description, droits, 7 mots-clés, dates", "Choisir les catégories dans la modale (30s)"],
        ["Étape 2 — Contenu", "ISBN, papier, trim size, bleed, couverture, manuscrit, IA disclosure", "Néant — tout automatique"],
        ["Étape 3 — Prix", "Affiche les instructions — RIEN d'automatique", "Remplir territoires + prix → Save as Draft"],
        ["Fin", "Détecte l'URL /bookshelf ou la fermeture Firefox", "Cliquer ✅ J'ai cliqué Publish"],
    ]
    story.append(tbl(etapes, col_widths=[3.5*cm, 7.5*cm, 5*cm]))
    story.append(sp(6))

    story.append(Paragraph("Bouton ✅ Fait — continue maintenant", s["h3"]))
    story.append(Paragraph(
        "Pendant que le bot attend votre action (catégories, pricing), "
        "cliquez <b>✅ Fait — continue maintenant</b> pour signaler que vous avez terminé. "
        "Le bot passe immédiatement à l'étape suivante sans attendre le délai max.", s["body"]))
    story.append(sp(6))

    story.append(InfoBox(
        "Première utilisation : cliquer 🔐 Login KDP et se connecter manuellement dans Firefox. "
        "La session est sauvegardée — vous ne vous reconnectez plus (jusqu'à expiration).",
        "info"))
    story.append(sp(4))
    story.append(InfoBox(
        "Si le bot se bloque : cliquer 🗑️ Effacer état dans le panneau de statut. "
        "Redémarrer Streamlit si nécessaire (Ctrl+C dans le Terminal → streamlit run app.py).",
        "warning"))
    story.append(PageBreak())
    return story


def build_seo_categories_arc(s):
    story = []
    story.append(ColorBlock("5b. SEO TOWER · CATÉGORIES · ARC TRACKER", bg=BLEU_SECTION, fg=BLANC, height=38, fontsize=14))
    story.append(sp(10))

    # SEO Tower
    story.append(Paragraph("SEO Tower — Score & optimisation listing", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "Analyse votre listing en 4 zones et donne un grade de A à D. "
        "Accessible via l'expander <b>🎯 SEO Tower — Score X/100 · Grade Y</b>.", s["body"]))

    zones = [
        ["Zone", "Poids", "Problèmes détectés"],
        ["Titre", "30%", "Trop long (>60), 2+ colons, 2+ virgules, trop de majuscules, niche absente"],
        ["Sous-titre", "15%", "Vide, >80 chars, trop similaire au titre, pas de promesse chiffrée"],
        ["Description", "25%", "Trop courte, HTML mal formé (<ul><li> interdit), accroches faibles, pas de CTA"],
        ["Mots-clés", "30%", "< 7 utilisés, 1 seul mot, trop de chevauchement avec le titre"],
    ]
    story.append(tbl(zones, col_widths=[2.5*cm, 1.5*cm, 12*cm]))
    story.append(sp(6))

    story.append(Paragraph("Grades", s["h3"]))
    grades = [
        ["Grade", "Score", "Signification"],
        ["A", "≥ 85", "Excellent — listing prêt à publier"],
        ["B", "≥ 70", "Bon — quelques optimisations suggérées"],
        ["C", "≥ 55", "Passable — réécriture recommandée"],
        ["D", "< 55", "Insuffisant — bouton Claude réécriture disponible"],
    ]
    story.append(tbl(grades, col_widths=[2*cm, 2*cm, 12*cm]))
    story.append(sp(6))
    story.append(b("🔎 Bouton <b>Vérifier 7 keywords sur Amazon autocomplete</b> : vérifie chaque mot-clé en live (~3s, gratuit)", s))
    story.append(b("🤖 Bouton <b>Claude réécrit les zones faibles</b> : visible seulement pour les grades C et D (~0,015 $)", s))
    story.append(sp(10))

    # Categories Optimizer
    story.append(Paragraph("Optimiseur de catégories — live Amazon", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "Le bouton <b>📊 Optimiser ces 3 catégories</b> analyse en direct les catégories KDP "
        "pour trouver les 3 plus faciles à pénétrer pour votre livre (~0,005 $ · 60-90s).", s["body"]))

    story.append(Paragraph("Pipeline :", s["h3"]))
    story.append(b("Claude propose 6-10 catégories KDP candidates avec leurs mots de recherche", s))
    story.append(b("Pour chaque candidate → scraping des 15 top livres Amazon", s))
    story.append(b("Score composite = 45% pénétrabilité + 35% volume + 20% prix", s))
    story.append(b("Les 3 meilleures sont sauvegardées dans listing.json → utilisées lors du push KDP", s))

    story.append(Paragraph("Score de pénétrabilité :", s["h3"]))
    pen = [
        ["Avg reviews top 15", "Score"],
        ["≤ 25", "95 — 🥇 EXPLOITABLE"],
        ["≤ 50", "85 — ✅ Bon choix"],
        ["≤ 100", "70 — ✅ Pénétrable"],
        ["≤ 200", "50 — 🟡 Risqué"],
        ["≤ 500", "30 — 🟡 Difficile"],
        ["> 500", "12 — 🔴 À éviter"],
    ]
    story.append(tbl(pen, col_widths=[7*cm, 9*cm]))
    story.append(sp(10))

    # ARC Tracker
    story.append(Paragraph("ARC Tracker — Équipe de reviewers", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "ARC = Advance Review Copy. "
        "Avant de publier, vous envoyez gratuitement votre livre à des lecteurs "
        "qui s'engagent à laisser une review Amazon. "
        "L'ARC Tracker gère toute cette équipe par livre.", s["body"]))

    statuts = [
        ["Statut", "Signification"],
        ["invited", "Contacté — pas encore répondu"],
        ["sent_pdf", "PDF ARC envoyé — attend la lecture"],
        ["reminded", "Relancé le jour du lancement"],
        ["posted_review", "✅ Review postée sur Amazon"],
        ["declined", "A refusé de participer"],
        ["no_reply", "Jamais répondu après relance"],
    ]
    story.append(tbl(statuts, col_widths=[3.5*cm, 12.5*cm]))
    story.append(sp(6))

    story.append(Paragraph("Fonctionnalités", s["h3"]))
    story.append(b("📄 <b>Générer ARC PDF</b> : ajoute un watermark diagonal 'ARC Copy', une page d'intro et une page CTA review", s))
    story.append(b("✍️ <b>Générer 4 emails Claude</b> : recruitment · send_pdf · reminder · thank_you (~0,01 $)", s))
    story.append(b("<b>Bulk import</b> : coller une liste d'emails (un par ligne, format flexible)", s))
    story.append(b("<b>Export Markdown</b> : tableau de votre équipe à copier-coller", s))
    story.append(sp(6))

    story.append(Paragraph("Workflow ARC recommandé :", s["h3"]))
    workflow = [
        "Générer l'ARC PDF watermarqué",
        "Uploader sur Booksprout (9$/mois · 1 campagne active · 25 copies)",
        "Copier le template recruitment → partager dans groupes FB/TikTok",
        "Importer les emails des volontaires via bulk import",
        "Jour du lancement : envoyer le template reminder",
        "Mettre à jour les statuts au fil des reviews",
        "Cible : 15+ reviews avant le lancement officiel",
    ]
    for i, step in enumerate(workflow, 1):
        story.append(b(f"Étape {i} : {step}", s))
    story.append(PageBreak())
    return story


def build_intelligence(s):
    story = []
    story.append(ColorBlock("6. MODULE INTELLIGENCE — DASHBOARD", bg=BLEU_TITRE, fg=BLANC, height=38, fontsize=15))
    story.append(sp(10))
    story.append(Paragraph(
        "Le dashboard Intelligence donne une vue stratégique de votre catalogue. "
        "7 onglets, tous en cache pour des performances optimales.", s["body"]))
    story.append(sp(6))

    tabs = [
        ("📊 Overview", "8 KPIs globaux + meilleur livre + patterns des livres perdants",
         "Coût : gratuit · Cache : 2 min"),
        ("📈 Performance", "Graphique des ventes simulées semaine par semaine (8 semaines)",
         "Coût : gratuit · Cache : 5 min"),
        ("🎯 Recommandeur", "8 niches recommandées avec score prédit + bouton 📋 Copier vers Création",
         "Formule = 40% qualité prédite + 30% (100 - compétition) + 30% score Crème · Cache : 5 min"),
        ("🌐 Market Intel", "Scraper une catégorie KDP : prix moyen, avis médian, top mots de titre",
         "Cache 7 jours · ~30s par scrape"),
        ("🔗 Combo Graph", "Graphe de connaissances : niche ↔ variant/thème/publisher (chemins forts ≥70)",
         "Coût : gratuit · Cache : 10 min"),
        ("🔍 Brief Compétitif", "Analyse approfondie d'une niche : top 10 livres + résumé tactique",
         "~60s · Cache : 1h"),
        ("🔑 Keywords Pro", "Expansion multi-sources : autocomplete + alphabet trick + probes adjacentes",
         "Sélectionne les 7 meilleurs avec mix d'intentions · Coût : gratuit"),
    ]

    for icon_title, desc, meta in tabs:
        story.append(KeepTogether([
            Paragraph(icon_title, s["h3"]),
            Paragraph(desc, s["body"]),
            Paragraph(meta, s["note"]),
            sp(4),
        ]))
    story.append(sp(6))

    story.append(Paragraph("Keywords Pro — Détail", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "L'outil Keywords Pro est le plus puissant pour trouver des mots-clés "
        "longue traîne à haut volume et faible compétition.", s["body"]))
    sources = [
        ["Source", "Méthode"],
        ["Amazon autocomplete", "Complète votre seed avec toutes les suggestions Amazon"],
        ["Alphabet trick", "Ajoute a→z après votre seed et collecte chaque résultat"],
        ["Single-word probes", "Teste des mots seuls liés à votre niche"],
        ["Adjacent pairs", "Combine 2 mots adjacents pour trouver des expressions"],
    ]
    story.append(tbl(sources, col_widths=[5*cm, 11*cm]))
    story.append(sp(4))
    story.append(Paragraph(
        "Résultat : jusqu'à 40 candidats scorés → sélection des 7 meilleurs "
        "avec mix d'intentions (découverte, achat, comparaison).", s["body"]))
    story.append(PageBreak())
    return story


def build_apprentissage(s):
    story = []
    story.append(ColorBlock("7. SYSTÈME D'APPRENTISSAGE", bg=BLEU_TITRE, fg=BLANC, height=38, fontsize=15))
    story.append(sp(10))
    story.append(Paragraph(
        "Plus vous utilisez l'app, plus elle s'améliore. "
        "Le système d'apprentissage capture vos préférences et les injecte dans les futures générations.", s["body"]))
    story.append(sp(6))

    story.append(Paragraph("Feedback — Comment noter vos livres", s["h2"]))
    story.append(hr())
    feedbacks = [
        ["Bouton", "Signification", "Effet sur le système"],
        ["👍 J'aime", "Bon livre — style, contenu, couverture", "Booste ce variant + thème + éditeur"],
        ["👎 Je n'aime pas", "Pas satisfaisant", "Réduit la probabilité de ce variant + thème"],
        ["✅ Publié", "Livre publié avec succès sur KDP", "Signal fort positif (×2 feedback)"],
    ]
    story.append(tbl(feedbacks, col_widths=[2*cm, 5*cm, 9*cm]))
    story.append(sp(8))

    story.append(Paragraph("Score true_quality — 5 signaux fusionnés", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "Chaque livre reçoit un score de qualité réel calculé automatiquement "
        "à partir de 5 sources de signal :", s["body"]))
    signals = [
        ["Signal", "Poids", "Mesure"],
        ["Feedback rating", "35%", "👍 = 100, 👎 = 0, ✅ = 100, neutre = 50"],
        ["Score validateur", "25%", "Score 0-100 de validator.py"],
        ["Temps de publication", "15%", "Publié vite = bon livre (moins d'itérations)"],
        ["Auto-fixes appliqués", "-15%", "Pénalité : chaque auto-fix diminue le score"],
        ["Régénérations cover", "-10%", "Pénalité : trop regen = couverture médiocre"],
        ["Choix candidat cover", "+7%", "Bonus si vous avez choisi parmi des candidats A/B"],
    ]
    story.append(tbl(signals, col_widths=[4.5*cm, 1.8*cm, 9.7*cm]))
    story.append(sp(8))

    story.append(Paragraph("Prédicteur de qualité", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "Avant chaque génération, l'app affiche une bannière 🔮 avec la qualité prédite "
        "pour chaque niche sélectionnée, basée sur vos feedbacks passés.", s["body"]))
    story.append(b("Devient fiable après ~10 feedbacks (confidence ≥50%)", s))
    story.append(b("Exact match (variant + thème) → moyenne observée", s))
    story.append(b("Sinon : fallback marginal (variant seul, ou thème seul, ou moyenne globale)", s))
    story.append(sp(8))

    story.append(Paragraph("Transfert cross-niche", s["h2"]))
    story.append(hr())
    story.append(Paragraph(
        "Si un style fonctionne bien sur vos journals, l'app le suggèrera aussi "
        "pour vos logs et planners (même famille thématique).", s["body"]))
    families = [
        ["Famille", "Types inclus"],
        ["writing", "journal, diary, log"],
        ["games", "quiz, trivia, puzzle"],
        ["creative", "coloring, sketchbook"],
        ["wellness", "planner, tracker, gratitude"],
        ["lifestyle", "habit, budget, fitness"],
        ["tech", "ai workflow, coding, productivity"],
    ]
    story.append(tbl(families, col_widths=[4*cm, 12*cm]))
    story.append(sp(6))
    story.append(InfoBox(
        "Pour activer le plein potentiel du système : notez chaque livre après publication. "
        "10 feedbacks = prédictions fiables. 25+ = optimisation fine.", "tip"))
    story.append(PageBreak())
    return story


def build_parametres(s):
    story = []
    story.append(ColorBlock("8. PARAMÈTRES & CONFIGURATION", bg=BLEU_TITRE, fg=BLANC, height=38, fontsize=15))
    story.append(sp(10))

    story.append(Paragraph("Clés API requises", s["h2"]))
    story.append(hr())
    keys = [
        ["Clé", "Service", "Utilisation dans l'app"],
        ["ANTHROPIC_API_KEY", "Anthropic Claude", "Listings, design brief, SEO rewrite, emails ARC, genre check"],
        ["OPENAI_API_KEY", "OpenAI (DALL-E)", "Couvertures + illustrations (gpt-image-2)"],
    ]
    story.append(tbl(keys, col_widths=[4*cm, 3.5*cm, 8.5*cm]))
    story.append(sp(6))
    story.append(Paragraph(
        "Les clés sont stockées dans le fichier <b>.env</b> à la racine du projet. "
        "La page Paramètres de l'app affiche l'emplacement du fichier et le statut de chaque clé.", s["body"]))
    story.append(sp(8))

    story.append(Paragraph("Fichiers de données importants", s["h2"]))
    story.append(hr())
    files = [
        ["Fichier / Dossier", "Contenu — NE PAS supprimer"],
        ["output/learning/feedback.jsonl", "Tous vos 👍/👎/✅ — historique d'apprentissage"],
        ["output/learning/events.jsonl", "Événements multi-signal (cover picks, regens…)"],
        ["output/learning/arc_teams.json", "Équipes ARC de tous vos livres"],
        ["output/learning/interior_fingerprints.json", "Anti-duplication des intérieurs"],
        ["output/learning/kdp_session.json", "Session Firefox KDP (login persisté)"],
        ["output/history/creme_*.json", "Résultats des scans Crème"],
        ["~/Desktop/KDP/{slug}/listing.json", "Le listing de chaque livre"],
        ["~/Desktop/KDP/{slug}/.cover_front.png", "Cache image couverture (fine-tune 0$)"],
    ]
    story.append(tbl(files, col_widths=[6.5*cm, 9.5*cm]))
    story.append(sp(8))

    story.append(Paragraph("Réinitialisation et debug", s["h2"]))
    story.append(hr())
    resets = [
        ("Réinitialiser la session Firefox (forcer re-login)",
         "rm output/learning/kdp_session.json"),
        ("Réinitialiser les données d'apprentissage",
         "rm output/learning/feedback.jsonl output/learning/events.jsonl"),
        ("Débloquer un thread de publication bloqué",
         "Cliquer 🗑️ Effacer état dans le panneau Publication, OU redémarrer Streamlit (Ctrl+C → streamlit run app.py)"),
        ("Vider le cache Streamlit",
         "rm -rf ~/.cache/streamlit/ puis redémarrer"),
        ("Voir les logs bruts de génération Q&A",
         "ls output/debug/qa_*.txt (pruné automatiquement après 7 jours)"),
        ("Voir les captures KDP en cas d'erreur",
         "ls output/learning/publishing_snaps/ (pruné après 14 jours)"),
    ]
    for title, cmd in resets:
        story.append(b(f"<b>{title}</b>", s))
        story.append(b2(cmd, s))
        story.append(sp(2))
    story.append(PageBreak())
    return story


def build_depannage(s):
    story = []
    story.append(ColorBlock("9. RÉSOLUTION DES PROBLÈMES COURANTS", bg=BLEU_TITRE, fg=BLANC, height=38, fontsize=15))
    story.append(sp(10))

    problemes = [
        (
            "L'app ne démarre pas",
            "Streamlit ou les dépendances ne sont pas installés correctement.",
            [
                "Vérifier que le venv est activé : source venv/bin/activate",
                "Réinstaller : pip install -r requirements.txt",
                "Vérifier Python 3.9+ : python3 --version",
            ]
        ),
        (
            "La génération échoue avec 'API error'",
            "Clé API invalide ou quota dépassé.",
            [
                "Vérifier les clés dans le fichier .env",
                "Tester la clé Anthropic sur console.anthropic.com",
                "Tester la clé OpenAI sur platform.openai.com",
            ]
        ),
        (
            "La couverture est rejetée par KDP (dimensions incorrectes)",
            "Le spine calculé ne correspond pas à la couverture générée.",
            [
                "Aller dans la carte du livre → 🔧 Fix dimensions cover",
                "Sélectionner le bon trim + papier → Appliquer",
                "Si l'erreur persiste : Auto-améliorer cover pour forcer un recalcul",
            ]
        ),
        (
            "Firefox ne s'ouvre pas / bot bloqué",
            "Session KDP expirée ou Playwright non installé.",
            [
                "Vérifier Playwright : playwright install firefox",
                "Cliquer 🗑️ Effacer état sur la page Publication",
                "Cliquer 🔐 Login KDP et se reconnecter manuellement",
                "Si toujours bloqué : Ctrl+C terminal → streamlit run app.py",
            ]
        ),
        (
            "Le fine-tune cover donne une erreur 'image cache manquant'",
            ".cover_front.png n'existe pas pour ce livre (généré avant le système de cache).",
            [
                "Cliquer 🔄 Auto-améliorer cover UNE FOIS — cela génère le cache",
                "Le fine-tune sera disponible sans frais ensuite",
            ]
        ),
        (
            "Le score SEO Tower est bas malgré un bon listing",
            "Souvent un problème d'HTML ou de chevauchement titre/mots-clés.",
            [
                "Cliquer 🔎 Vérifier les keywords sur Amazon",
                "Utiliser 🤖 Claude réécrit les zones faibles si grade C ou D",
                "Vérifier que la description n'utilise pas <ul><li><h1> (interdits KDP)",
            ]
        ),
        (
            "Les puzzles générés semblent toujours identiques",
            "Même niche + même volume → même seed (c'est normal, c'est voulu).",
            [
                "Changer le numéro de Volume # dans les options puzzle",
                "Vol. 1, 2, 3… donnent des puzzles totalement différents",
            ]
        ),
        (
            "La sidebar a disparu",
            "Elle s'est réduite et le bouton est caché.",
            [
                "Essayer Cmd+Shift+R pour rafraîchir sans cache",
                "Ou ouvrir la console navigateur (F12) et taper : localStorage.clear(); location.reload()",
            ]
        ),
    ]

    for titre, cause, solutions in problemes:
        story.append(KeepTogether([
            Paragraph(f"❓ {titre}", s["h3"]),
            Paragraph(f"<i>Cause probable : {cause}</i>", s["warning"]),
        ] + [b(sol, s) for sol in solutions] + [sp(8)]))

    story.append(sp(10))
    story.append(hr(BLEU_MEDIUM, 2))
    story.append(sp(8))
    story.append(Paragraph("Fin du guide — KDP Automation v3 · Juin 2026", s["caption"]))
    story.append(Paragraph(
        "Pour toute question ou évolution : ouvrir une session Claude Code et décrire votre besoin.",
        s["caption"]))
    return story


# ── Entête + pied de page ─────────────────────────────────────────────────────
def _header_footer(canvas, doc):
    canvas.saveState()
    w, h = A4

    # Header (sauf page 1)
    if doc.page > 1:
        canvas.setFillColor(BLEU_TITRE)
        canvas.rect(0, h - 1.4*cm, w, 1.4*cm, fill=1, stroke=0)
        canvas.setFillColor(BLANC)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(1.5*cm, h - 0.95*cm, "KDP Automation — Guide des fonctionnalités")
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(w - 1.5*cm, h - 0.95*cm, f"Page {doc.page}")

    # Footer
    canvas.setFillColor(BLEU_MEDIUM)
    canvas.rect(0, 0, w, 0.8*cm, fill=1, stroke=0)
    canvas.setFillColor(BLEU_TITRE)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(1.5*cm, 0.27*cm, "© 2026 KDP Automation · Usage personnel uniquement")
    canvas.drawRightString(w - 1.5*cm, 0.27*cm, "streamlit run app.py → http://localhost:8501")
    canvas.restoreState()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    out_path = Path.home() / "Desktop/KDP/Tuto/Guide_KDP_Automation.pdf"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        rightMargin=1.8*cm,
        leftMargin=1.8*cm,
        topMargin=2.0*cm,
        bottomMargin=1.8*cm,
        title="Guide KDP Automation — Fonctionnalités complètes",
        author="KDP Automation",
        subject="Guide utilisateur",
    )

    s = build_styles()

    story = []
    story += build_cover(s)
    story += build_toc(s)
    story += build_demarrage(s)
    story += build_module1(s)
    story += build_module2(s)
    story += build_module_qualite(s)
    story += build_module_publishing(s)
    story += build_seo_categories_arc(s)
    story += build_intelligence(s)
    story += build_apprentissage(s)
    story += build_parametres(s)
    story += build_depannage(s)

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    print(f"✅ PDF généré : {out_path}")
    print(f"   Pages : voir le fichier")


if __name__ == "__main__":
    main()
