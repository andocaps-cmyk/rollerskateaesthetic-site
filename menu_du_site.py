#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LE MENU DU SITE, EN UN SEUL ENDROIT.

Pose le 08/10/2026. Avant cette date le site n'avait aucun menu : le guide d'achat (/guide/) et les
quatre outils (/tools/...) etaient en ligne, mais un visiteur ne les trouvait pas — et ce sont les
pages qui portent les liens d'affiliation.

Le menu tient en quatre liens, dans cet ordre : le nom du site (accueil), « Beginner's guide »
(accueil), « Buying guides » (/guide/), « Free tools » (/tools/). Il est sobre, sans menu
deroulant, et tient sur une ou deux lignes a 375 px de large (le trafic vient de Pinterest, donc
du telephone).

OU IL EST POSE
  - Les gabarits Python (build_pages.py, build_portes.py, build_about.py) appellent `appliquer()`
    sur chaque page qu'ils ecrivent : une page generee demain porte le menu sans geste de plus.
  - Les pages ecrites a la main ou par un agent (guide/, tools/, accueil, contact, privacy) le
    recoivent en lancant ce fichier : `python3 menu_du_site.py` a la racine du depot.
  - `python3 menu_du_site.py --verifier` ne modifie rien : il compte les pages qui portent le menu
    et sort en erreur s'il en manque une.

IL EST IDEMPOTENT. Le menu vit entre deux marques ; une page qui le porte deja est remise a jour
entre les marques, jamais doublee. Une page qui porte l'ancien en-tete `<header class="top">`
le voit remplace par le menu (le menu reprend le nom du site et le lien vers le guide debutant
qu'il contenait). Une page sans en-tete (accueil, contact, privacy) recoit le menu juste apres
`<body>`. Les pages de /oauth/ ne sont pas des pages de visiteur et ne sont pas touchees.
"""

import pathlib
import re
import sys

SITE = "https://rollerskateaesthetic.com"

DEBUT = "<!-- menu du site -->"
FIN = "<!-- fin menu du site -->"
CSS_ID = "menu-du-site"

# Dossiers dont les pages ne recoivent pas le menu : oauth (pas une page de visiteur) et embed
# (outils integres chez un club, sans menu ; voir build_embeds.py).
EXCLUS = {"oauth", "embed"}

MENU = (
    DEBUT + "\n"
    '<nav class="sitemenu" aria-label="Site menu"><div class="sitemenu-in">\n'
    '<a class="sitemenu-brand" href="' + SITE + '/">Roller Skate Aesthetic</a>\n'
    '<span class="sitemenu-links">'
    '<a href="' + SITE + '/">Beginner&rsquo;s guide</a>'
    '<a href="' + SITE + '/guide/">Buying guides</a>'
    '<a href="' + SITE + '/tools/">Free tools</a>'
    '</span>\n'
    '</div></nav>\n'
    + FIN
)

# Couleurs ecrites en dur, pas en var() : une partie des pages ne declare pas les variables.
# Toutes les classes commencent par « sitemenu » pour ne rien heriter du CSS propre a chaque page.
CSS = (
    '<style id="' + CSS_ID + '">'
    "nav.sitemenu{background:#EEE0D4;border-bottom:3px solid #2C2230;padding:12px 0;"
    "font-family:'Jost',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.4}"
    "nav.sitemenu .sitemenu-in{max-width:720px;margin:0 auto;padding:0 16px;display:flex;"
    "flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px 20px}"
    "nav.sitemenu a{color:#2C2230;text-decoration:none}"
    "nav.sitemenu .sitemenu-brand{font-family:'Fraunces',Georgia,serif;font-weight:900;"
    "font-size:1.4rem;letter-spacing:-.01em;line-height:1.15}"
    # Les trois liens sont des onglets, sur ordinateur comme sur telephone (08/10/2026, le propriétaire :
    # la version soulignee faisait bizarre ; les onglets « c'est moins bizarre »).
    "nav.sitemenu .sitemenu-links{display:flex;gap:8px;font-size:.92rem;font-weight:500}"
    "nav.sitemenu .sitemenu-links a{display:flex;align-items:center;justify-content:center;"
    "text-align:center;background:#F7EEE5;border:2px solid #2C2230;border-radius:8px;"
    "padding:5px 14px;line-height:1.2;min-height:38px}"
    "nav.sitemenu .sitemenu-links a:hover{background:#fff;color:#2C2230;border-color:#E88A74}"
    "nav.sitemenu .sitemenu-brand:hover{color:#E88A74}"
    # Telephone (capture du propriétaire, page traduite en francais par Chrome : les libelles allonges
    # cassaient le menu sur trois lignes) : le nom centre, puis trois onglets de meme largeur sur
    # UNE ligne ; un libelle long revient a la ligne DANS son onglet au lieu de pousser les autres.
    "@media (max-width:520px){nav.sitemenu{padding:10px 0 12px}"
    "nav.sitemenu .sitemenu-in{display:block;padding:0 12px}"
    "nav.sitemenu .sitemenu-brand{display:block;text-align:center;font-size:1.3rem;margin:2px 0 10px}"
    "nav.sitemenu .sitemenu-links{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;"
    "font-size:.85rem}"
    "nav.sitemenu .sitemenu-links a{padding:6px 4px;min-height:40px}}"
    # Ordinateur seulement (08/10/2026, le propriétaire : cale a gauche, ce n'etait « pas harmonieux » a cote
    # d'un accueil centre ; le telephone, lui, reste tel quel) : le nom centre, les onglets centres
    # en dessous.
    "@media (min-width:521px){nav.sitemenu{padding:14px 0 16px}"
    "nav.sitemenu .sitemenu-in{flex-direction:column;justify-content:center;align-items:center;"
    "gap:10px;text-align:center}}"
    # Espace sous le menu (08/10/2026) : sur les pages skate/, guide/ et about, la regle .wrap de la
    # page annule le padding haut de <main>, et le premier titre collait au menu (0 px mesure).
    "nav.sitemenu+main.wrap{padding-top:40px}"
    "@media (max-width:520px){nav.sitemenu+main.wrap{padding-top:28px}}"
    "</style>"
)

ANCIEN_ENTETE = re.compile(r'<header class="top">.*?</header>', re.S)
BLOC_MENU = re.compile(re.escape(DEBUT) + r".*?" + re.escape(FIN), re.S)
BLOC_CSS = re.compile(r'<style id="' + CSS_ID + r'">.*?</style>', re.S)
BODY = re.compile(r"<body[^>]*>")


def appliquer(html):
    """Rend la page avec le menu et son style. Ne change rien d'autre."""
    # 1. le style, dans <head>
    if BLOC_CSS.search(html):
        html = BLOC_CSS.sub(lambda m: CSS, html, count=1)
    elif "</head>" in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    else:
        raise ValueError("page sans </head> : menu non pose")

    # 2. le menu, en tete de <body>
    if BLOC_MENU.search(html):
        return BLOC_MENU.sub(lambda m: MENU, html, count=1)
    if ANCIEN_ENTETE.search(html):
        return ANCIEN_ENTETE.sub(lambda m: MENU, html, count=1)
    m = BODY.search(html)
    if not m:
        raise ValueError("page sans <body> : menu non pose")
    return html[:m.end()] + "\n" + MENU + "\n" + html[m.end():]


def porte_le_menu(html):
    return MENU in html and CSS in html


def pages(racine):
    for f in sorted(racine.rglob("*.html")):
        rel = f.relative_to(racine)
        if rel.parts[0] in EXCLUS or rel.parts[0].startswith("."):
            continue
        yield f, rel


def main():
    verifier = "--verifier" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    racine = pathlib.Path(args[0] if args else pathlib.Path(__file__).parent).resolve()

    total = avec = modifiees = 0
    sans = []
    for f, rel in pages(racine):
        total += 1
        source = f.read_bytes().decode("utf-8")
        if verifier:
            if porte_le_menu(source):
                avec += 1
            else:
                sans.append(str(rel))
            continue
        nouveau = appliquer(source)
        if nouveau != source:
            f.write_bytes(nouveau.encode("utf-8"))
            modifiees += 1
        avec += 1

    print("pages de visiteur : %d" % total)
    print("pages qui portent le menu : %d" % avec)
    if not verifier:
        print("pages reecrites : %d" % modifiees)
    for s in sans:
        print("  SANS MENU : %s" % s)
    if sans:
        sys.exit(1)


if __name__ == "__main__":
    main()
