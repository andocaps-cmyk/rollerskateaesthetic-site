#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LE CONTROLEUR DE REFERENCEMENT. Il fait foi sur les regles de un document interne.

Pose le 09/10/2026. Avant cette date, les regles de referencement vivaient dans un fichier de
savoir et rien ne les verifiait : les pages /guide/ (07/10) et /tools/ ont ete fabriquees par
d'autres chemins que les pages /skate/, et elles sont parties en ligne sans auteur nomme, sans
image de partage, et pour /tools/ sans date. Personne ne l'a vu pendant deux jours.

Ce fichier ne corrige rien. Il lit chaque page publique du depot et dit ce qui manque. La
correction se fait dans les generateurs (build_referencement.py pour les donnees structurees,
la ligne de signature et l'image de partage), jamais a la main dans le HTML.

CE QU'IL VERIFIE, POUR CHAQUE PAGE PUBLIQUE (tout index.html hors /embed/ et /oauth/) :
  titre        un <title> non vide
  description  une <meta name="description"> non vide
  canonical    un <link rel="canonical"> qui pointe vers l'adresse de la page elle-meme
  h1           exactement un <h1>
  auteur       dans les donnees structurees, un `author` de type Person nomme Cass, avec
               l'adresse de /about/ ; et dans le texte, la signature « Cass » liee a /about/
               (regle 2 de un document interne)
  date         un `dateModified` dans les donnees structurees ET une date visible dans le
               texte (regle 6)
  og_image     une <meta property="og:image">, et soit son fichier existe dans le site produit
               (donc Cloudflare le servira), soit l'adresse repond deja 200 en ligne (image
               hebergee ailleurs, ou deja publiee)
  ia           la mention « written with an AI assistant »
  affiliation  la mention « As an Amazon Associate… » quand la page porte un lien Amazon, et
               (depuis le 22/10/2026) la phrase exacte AVANT le premier lien d'affiliation
  tag_suivi    (depuis le 25/10/2026) un identifiant de suivi par emplacement de clic : un lien
               panier (gp/aws/cart/add.html) porte `AssociateTag=rskacart-20`, un lien texte
               (/dp/<ASIN>) porte `tag=rskatext-20` ; `rollerskateae-20` et tout autre
               identifiant sur ces deux formes sont un defaut. Motif : lire les commandes par
               emplacement dans le rapport Amazon (colonne Tracking ID).
  via          (depuis le 25/10/2026) attribution outil -> achat : chaque page qui mene a Amazon
               porte le script `id="via-tag"` (via_outils_2026-10-25.py) ; chaque page /tools/<outil>/
               porte l'ecouteur `id="via-out"` et chacun de ses liens statiques vers /guide/ porte
               `via=quiz|size|wheel|gear`.
  plan         la page est dans sitemap.xml ; et aucune adresse de sitemap.xml n'est en
               noindex ni ne manque dans le depot
  servi        (depuis le 22/10/2026) tout fichier de la RACINE du depot qui n'est pas une page ou
               un flux (.py, .csv, ...) a sa regle dans _redirects : exacte (/nom ...) ou joker
               (/prefixe* ...). Quatrieme recidive le 12/10/2026 (sept .py servis en 200) : la regle
               « se range dans le geste qui le cree » etait un commentaire, elle devient bloquante.

Aucune exception : l'accueil (WebSite), /about/ (AboutPage), /contact/ (ContactPage) et
/privacy/ (WebPage) ne sont pas des articles, mais ils portent la meme signature « by Cass »
et doivent declarer le meme auteur et les memes dates dans leur noeud de page.

DEUX MODES, SEPARES LE 09/10/2026 :

  BLOQUANT (par defaut). Tout ce qui se juge sur le site produit, AVANT la mise en ligne. C'est
  lui que `publier.yml` lance a chaque envoi sur `main` : s'il rend autre chose que 0, la
  branche `prod` n'avance pas et Cloudflare ne publie rien. Il ne demande JAMAIS au serveur une
  image dont le fichier est dans le depot : une page neuve a une image qui n'est pas encore en
  ligne au moment du controle, et l'exiger en 200 bloquerait toute publication.
  Sortie : une ligne `DEFAUT <regle> <adresse> — <detail>` par defaut, un resume par regle et
  par dossier, code 1 s'il y a au moins un defaut, 0 sinon.

  APRES DEPLOIEMENT (--apres-deploiement). Demande chaque og:image au serveur et exige 200.
  NE BLOQUE RIEN : il sort toujours en 0. Ses defauts s'ecrivent dans le journal de
  l'execution (lignes `DEFAUT_EN_LIGNE`, avertissements GitHub, resume de l'execution).

Usage :
  python3 verifier_referencement.py                      controle bloquant du depot courant
  python3 verifier_referencement.py --apres-deploiement  controle des images en ligne
  python3 verifier_referencement.py --racine D           travaille sur le dossier D
"""

import html
import json
import pathlib
import re
import sys
import urllib.request
from collections import Counter

SITE = "https://rollerskateaesthetic.com"
ABOUT = SITE + "/about/"
EXCLUS = {"embed", "oauth"}

REGLES = ("titre", "description", "canonical", "h1", "auteur", "date", "og_image", "ia",
          "affiliation", "prix_amazon", "evaluation", "plan", "servi", "longueur")

# ⛔ 24/10/2026 — REGLE AMAZON (bloquante). Le reglement du Partenariat Amazon
# (affiliate-program.amazon.com/help/operating/policies, maj du 14/04/2026, lu le 24/10/2026)
# interdit d'afficher un prix, une disponibilite, une note ou un nombre d'avis Amazon releves a la
# main : seuls un lien servi par Amazon ou Creators API / PA API y ont droit. Le 24/10, 29 pages
# /guide/ portaient 234 prix releves le 07/10 (« Amazon.com $91.36 ... read 2026-10-07 »).
# 25/10/2026 : identifiants de suivi Amazon par emplacement de clic (demande du projet).
TAGS_AMAZON = ("rollerskateae-20", "rskacart-20", "rskatext-20", "rskakit-20")
TAG_RE = re.compile(r"(?:tag|AssociateTag)=(" + "|".join(t.replace("-", r"\-") for t in TAGS_AMAZON) + r")\b", re.I)
LIEN_PANIER = re.compile(r'href="https?://www\.amazon\.com/gp/aws/cart/add\.html\?AssociateTag=([^&"]+)', re.I)
LIEN_TEXTE = re.compile(r'href="https?://www\.amazon\.com/dp/[A-Z0-9]{10}\?tag=([^&"]+)', re.I)

VIA_OUTILS = {"skate-quiz": "quiz", "size-calculator": "size", "wheel-hardness": "wheel",
              "protective-gear-checklist": "gear", "starter-kit-cost": "kit"}
# Le lien nu vers /guide/ (menu du site) est exempte : l'ecouteur via-out le couvre au clic.
LIEN_GUIDE_STATIQUE = re.compile(r'href="((?:https://rollerskateaesthetic\.com)?/guide/[a-z0-9-]+/?[^"\']*)"')

PRIX_INTERDITS = [
    (re.compile(r"Amazon\.com\s*\$\s?\d"), "prix « Amazon.com $… »"),
    (re.compile(r"\$\s?\d[\d,]*\.\d{2}\b"), "prix au centime"),
    (re.compile(r"\bonly \d+ left\b", re.I), "stock Amazon « only N left »"),
    (re.compile(r"out of 5 stars", re.I), "note Amazon « out of 5 stars »"),
    (re.compile(r"\b\d[\d,]*\s+(?:global\s+)?ratings\b", re.I), "nombre de notes"),
    (re.compile(r"\b\d[\d,]*\s+(?:customer\s+)?reviews\s+on\s+Amazon", re.I), "nombre d'avis Amazon"),
    (re.compile(r"bought in (?:the )?past month", re.I), "volume d'achats Amazon"),
]
# Page qui porte des prix Amazon releves a la main et qui n'a pas encore ete reprise : elle est
# signalee a CHAQUE passage (ligne AVERTISSEMENT prix_amazon), sans bloquer la publication,
# jusqu'a ce qu'elle soit corrigee. VIDE depuis le 24/10/2026 (calculateur mis hors ligne, voir
# hors_ligne_2026-10-24/un document interne) : la regle est bloquante partout. Etait : ajoutee le 24/10/2026 : le calculateur de cout tire tout son
# contenu de prix Amazon ; le corriger, c'est refaire l'outil (remontee du 24/10).
PRIX_EN_ATTENTE = set()

# ⛔ 15/11/2026 — LA PAGE « KIT AS ONE LIST » (build_kit_list.py ; decision de plateforme du projet du
# 15/11/2026 04 h 43, un document interne du dossier du projet). Elle porte UN bouton panier de
# plusieurs articles, a l'identifiant du calculateur (rskakit-20) et non rskacart-20 ; et elle ne doit
# porter AUCUN prix (reponse d'Amazon du 31/10/2026 : pas de prix hors PA API sur une page a lien
# affilie) : ni « $ », ni « € », ni le mot « price », ni disponibilite. Le script via-tag n'y est pas
# exige : il ne reecrit jamais rskakit-20 (il ne touche que rskatext, rskacart, rollerskateae), et
# son code porte un « $1 » qui mettrait un « $ » sur la page.
PANIER_TAG_PAR_PAGE = {"tools/starter-kit-cost/kit/": "rskakit-20"}
PAGES_SANS_PRIX = {"tools/starter-kit-cost/kit/"}
SANS_PRIX_INTERDITS = [
    (re.compile(r"\$"), "signe « $ »"),
    (re.compile("\u20ac"), "signe « € »"),
    (re.compile(r"price", re.I), "mot « price »"),
    (re.compile(r"\bcost\b[^<\n]{0,20}\d|\d[^<\n]{0,5}\bcost\b", re.I), "cout chiffre"),
    (re.compile(r"in stock|out of stock|availability|available", re.I), "disponibilite"),
]

# Fichiers de la racine qui ont le droit d'etre servis tels quels (pages, flux, robots).
# Tout autre fichier de la racine doit avoir sa regle dans _redirects.
RACINE_SERVIE = {".html", ".xml", ".txt", ".ico", ".png", ".jpg", ".jpeg", ".webp", ".svg",
                 ".css", ".js", ".webmanifest"}
# Fichiers de configuration de Cloudflare Pages : jamais servis.
RACINE_CONFIG = {"_redirects", "_headers"}

MOIS = ("January|February|March|April|May|June|July|August|September|October|November|"
        "December")
# Une date de PAGE, pas n'importe quelle date : « read 9 October 2026 » (date de lecture d'une
# source) ne dit pas quand la page a ete ecrite.
DATE_VISIBLE = re.compile(r"\b(?:Written|Compiled|Published|Updated|updated) "
                          r"\d{1,2} (?:%s) 20\d\d\b" % MOIS)


def lire(motif, texte):
    m = re.search(motif, texte, re.I | re.S)
    return html.unescape(m.group(1).strip()) if m else ""


def texte_visible(source):
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", source, flags=re.S | re.I)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s))


def noeuds_ld(source):
    """Tous les objets JSON-LD de la page, @graph deplie. Un bloc illisible est un defaut."""
    noeuds, erreurs = [], []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', source, re.S):
        try:
            donnee = json.loads(m.group(1))
        except ValueError as e:
            erreurs.append(str(e))
            continue
        pile = donnee if isinstance(donnee, list) else [donnee]
        for d in pile:
            if isinstance(d, dict) and "@graph" in d:
                noeuds.extend(x for x in d["@graph"] if isinstance(x, dict))
            elif isinstance(d, dict):
                noeuds.append(d)
    return noeuds, erreurs


def est_cass(auteur):
    auteurs = auteur if isinstance(auteur, list) else [auteur]
    for a in auteurs:
        if (isinstance(a, dict) and a.get("@type") == "Person" and a.get("name") == "Cass"
                and a.get("url", "").rstrip("/") == ABOUT.rstrip("/")):
            return True
    return False


def plan_du_site(racine):
    f = racine / "sitemap.xml"
    if not f.exists():
        return []
    return [html.unescape(x) for x in re.findall(r"<loc>(.*?)</loc>", f.read_text("utf-8"))]


def image_repond(url, cache):
    """Rend 200 seulement pour une IMAGE servie en 200.

    ⛔ MESURE LE 09/10/2026 : le site n'a pas de page 404, donc Cloudflare Pages sert l'accueil
    (200, text/html) pour toute adresse absente — /pins/pin_999_neuve.png repond 200. Un code
    200 seul ne prouve donc pas qu'une image existe : le type doit etre image/*.
    """
    if url not in cache:
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "verifier_referencement"})
            with urllib.request.urlopen(req, timeout=30) as r:
                genre = r.headers.get("Content-Type", "")
                cache[url] = r.status if genre.startswith("image/") else                     "200 mais %s (repli de Cloudflare, image absente)" % (genre or "sans type")
        except urllib.error.HTTPError as e:
            cache[url] = e.code
        except Exception as e:  # reseau coupe : on le dit, on ne le tait pas
            cache[url] = "erreur %s" % type(e).__name__
    return cache[url]


def controler_page(racine, fichier, urls_plan, cache):
    relatif = fichier.relative_to(racine)
    segments = relatif.parts[:-1]
    url = SITE + "/" + ("/".join(segments) + "/" if segments else "")
    dossier = segments[0] if segments else "(accueil)"
    source = fichier.read_text(encoding="utf-8")
    visible = texte_visible(source)
    tete = source.split("</head>", 1)[0]
    defauts = []

    def d(regle, detail):
        defauts.append((regle, url, dossier, detail))

    if not lire(r"<title[^>]*>(.*?)</title>", tete):
        d("titre", "pas de <title>")
    if not lire(r'<meta name="description" content="([^"]*)"', tete):
        d("description", "pas de meta description")
    # 26/10/2026 (remise en route) : longueurs que Google affiche. 228 titres > 60 et 242 meta
    # (> 155 ou coupees par « … ») corriges ce jour (corriger_titres_meta_2026-10-26.py) ;
    # la regle est bloquante pour qu'un generateur ne les fasse pas revenir.
    _t = html.unescape(lire(r"<title[^>]*>(.*?)</title>", tete) or "")
    _m = html.unescape(lire(r'<meta name="description" content="([^"]*)"', tete) or "")
    if len(_t) > 60:
        d("longueur", "<title> de %d caracteres (60 au plus)" % len(_t))
    if len(_m) > 155 or _m.rstrip().endswith(("\u2026", "...")):
        d("longueur", "meta description de %d caracteres ou coupee par « … » (155 au plus, phrase finie)" % len(_m))
    canon = lire(r'<link rel="canonical" href="([^"]*)"', tete)
    if canon != url:
        d("canonical", "canonical = %r, attendu %r" % (canon or None, url))
    n_h1 = len(re.findall(r"<h1[\s>]", source, re.I))
    if n_h1 != 1:
        d("h1", "%d balises <h1>" % n_h1)

    robots = lire(r'<meta name="robots" content="([^"]*)"', tete).lower()
    noindex = "noindex" in robots

    noeuds, erreurs = noeuds_ld(source)
    for e in erreurs:
        d("auteur", "bloc JSON-LD illisible : %s" % e)
    principaux = [n for n in noeuds if n.get("@type") in ("Article", "WebSite", "WebPage",
                                                           "AboutPage", "ContactPage", "CollectionPage")]

    if True:
        if not any(est_cass(n.get("author")) for n in principaux):
            vus = [json.dumps(n.get("author"), ensure_ascii=False) for n in principaux]
            d("auteur", "pas d'author Person « Cass » -> /about/ dans les donnees structurees"
              + (" (vu : %s)" % "; ".join(vus) if vus else " (aucun bloc Article/WebSite)"))
        if not re.search(r'by <a href="%s/?">Cass</a>' % re.escape(SITE + "/about"), source):
            d("auteur", "pas de signature « by Cass » liee a /about/ dans le texte")
        if not any(n.get("dateModified") for n in principaux):
            d("date", "pas de dateModified dans les donnees structurees")
        if not DATE_VISIBLE.search(visible):
            d("date", "pas de date visible dans le texte")
        if "written with an ai assistant" not in visible.lower():
            d("ia", "pas de mention « written with an AI assistant »")

    image = lire(r'<meta property="og:image" content="([^"]*)"', tete)
    if not image:
        d("og_image", "pas de og:image")
    else:
        local = racine / image[len(SITE) + 1:] if image.startswith(SITE + "/") else None
        if not (local and local.is_file()):
            # Pas de fichier dans le site produit : l'image n'est acceptee que si elle est deja
            # en ligne. Une image du depot n'est jamais demandee au serveur ici.
            code = image_repond(image, cache)
            if code != 200:
                d("og_image", "ni dans le site produit, ni en ligne (%s) : %s" % (code, image))

    if re.search(r"https?://(?:www\.)?(?:amazon\.[a-z.]+|amzn\.to)/", source):
        if "as an amazon associate" not in visible.lower():
            d("affiliation", "lien Amazon sans la mention « As an Amazon Associate »")
    # ⛔ 22/10/2026 : la phrase exacte AVANT le premier lien d'affiliation (contrat Amazon
    # Associates US, section 5, « clearly and prominently » ; lecture du projet,
    # un document interne § 9.0). Ce jour-la, les 68 pages a lien Amazon la mettaient toutes
    # apres : l'encadre du haut (02/10) portait le premier lien, la phrase etait restee en bas.
    m_tag = TAG_RE.search(source)
    premier = m_tag.start() if m_tag else -1
    phrase = source.find("As an Amazon Associate I earn from qualifying purchases.")
    if premier >= 0 and not 0 <= phrase < premier:
        d("affiliation", "le premier lien Amazon precede la phrase « As an Amazon Associate I "
                         "earn from qualifying purchases. »")
    # ⛔ 23/10/2026 : « nothing to buy » est faux sur une page qui mene a des produits Amazon,
    # directement (tag d'affiliation) ou par un lien vers un guide d'achat (/guide/). Mesure ce
    # jour-la : 251 pages (223 /skate/, 28 /guide/) finissaient l'encadre « Keep going » par
    # « Free, no sign-up, nothing to buy. », contre l'objectif d'au moins 100 € de ventes.
    # 29/10/2026 : refusee sur TOUTE page, avec ou sans lien Amazon (prompt fins de publication) :
    # le site entier porte des liens d'affiliation, et la phrase a ete retenue par Pinterest.
    if re.search(r"nothing\s+to\s+buy", source, re.I):
        d("affiliation", "« nothing to buy » sur la page (refuse partout depuis le 29/10/2026)")

    # Regle Amazon du 24/10/2026 : aucun prix, stock, note ni nombre d'avis Amazon.
    chemin = "/".join(segments) + "/" if segments else ""
    if chemin not in PRIX_EN_ATTENTE and (dossier in ("guide", "skate") or TAG_RE.search(source)):
        for motif, nom in PRIX_INTERDITS:
            m = motif.search(source)
            if m:
                d("prix_amazon", "%s : « %s »" % (nom, source[max(0, m.start() - 30):m.end() + 20].replace("\n", " ")))
    # 24/10/2026 : une page /guide/ qui mene a Amazon dit comment les produits ont ete juges
    # (Google, « Write high-quality product reviews », maj du 10/12/2025, lu le 24/10/2026).
    if dossier == "guide" and len(segments) > 1 and TAG_RE.search(source) \
            and not re.search(r"<h2[^>]*>\s*How we evaluated", source):
        d("evaluation", "pas de <h2> « How we evaluated » sur une page /guide/ qui mene a Amazon")
    # 25/10/2026 : un identifiant de suivi par emplacement de clic. Un lien panier porte
    # rskacart-20, un lien texte /dp/ porte rskatext-20 ; sinon le rapport Amazon ne dit pas
    # d'ou vient la commande. L'ancien identifiant rollerskateae-20 reste pour les autres
    # emplacements (biographies, epingles, flux), jamais sur ces deux formes.
    panier_attendu = PANIER_TAG_PAR_PAGE.get(chemin, "rskacart-20")
    for m in LIEN_PANIER.finditer(source):
        if m.group(1) != panier_attendu:
            d("tag_suivi", "lien panier avec AssociateTag=%s au lieu de %s" % (m.group(1), panier_attendu))
    if chemin in PAGES_SANS_PRIX:
        for motif, nom in SANS_PRIX_INTERDITS:
            m = motif.search(source)
            if m:
                d("prix_amazon", "page sans prix : %s « %s »" % (nom, source[max(0, m.start() - 30):m.end() + 20].replace("\n", " ")))
    for m in LIEN_TEXTE.finditer(source):
        if m.group(1) != "rskatext-20":
            d("tag_suivi", "lien texte /dp/ avec tag=%s au lieu de rskatext-20" % m.group(1))
    # 25/10/2026 : attribution outil -> guide -> Amazon (REMONTEE du projet, 14 h 20).
    if "amazon.com" in source and 'id="via-tag"' not in source and chemin not in PANIER_TAG_PAR_PAGE:
        d("via", "page qui mene a Amazon sans le script via-tag (via_outils_2026-10-25.py)")
    if dossier == "tools" and len(segments) > 1:
        via_attendu = VIA_OUTILS.get(segments[1])
        if via_attendu:
            if 'id="via-out"' not in source:
                d("via", "page d'outil sans l'ecouteur via-out (via_outils_2026-10-25.py)")
            for m in LIEN_GUIDE_STATIQUE.finditer(source):
                if ("via=%s" % via_attendu) not in m.group(1):
                    d("via", "lien d'outil vers un guide sans via=%s : %s" % (via_attendu, m.group(1)))

    if noindex and url in urls_plan:
        d("plan", "page en noindex presente dans sitemap.xml")
    if not noindex and url not in urls_plan:
        d("plan", "page publique absente de sitemap.xml")

    return url, noindex, defauts



def sources_redirigees(racine):
    """Chemins (« /skate/x/ ») qu'une regle de _redirects renvoie ailleurs en 301 ou 302 : la page
    n'est pas servie, elle ne va donc pas au plan du site. Ajoute le 07/11/2026 : la liste de
    verification du chef a trouve /skate/inline-skates-are-stable/ (301 depuis le 05/08) dans le plan."""
    f = racine / "_redirects"
    out = set()
    if f.exists():
        for ligne in f.read_text("utf-8").splitlines():
            m = ligne.split("#")[0].split()
            if len(m) >= 3 and m[2] in ("301", "302") and not m[0].endswith("*"):
                out.add(m[0] if m[0].endswith("/") else m[0] + "/")
    return out


def fichiers_racine_non_ranges(racine):
    """Fichiers de la racine (hors dossiers, hors fichiers caches) qui seraient servis en 200 alors
    qu'ils ne sont ni une page ni un flux, et qu'aucune regle de _redirects ne couvre."""
    regles = []
    f = racine / "_redirects"
    if f.exists():
        for ligne in f.read_text("utf-8").splitlines():
            ligne = ligne.strip()
            if ligne and not ligne.startswith("#"):
                regles.append(ligne.split()[0])
    exactes = set(regles)
    jokers = [r[:-1] for r in regles if r.endswith("*")]
    manquants = []
    for x in sorted(racine.iterdir()):
        if not x.is_file() or x.name.startswith(".") or x.name in RACINE_CONFIG:
            continue
        if x.suffix.lower() in RACINE_SERVIE:
            continue
        chemin = "/" + x.name
        if chemin in exactes or any(chemin.startswith(j) for j in jokers):
            continue
        manquants.append(x.name)
    return manquants


def pages_publiques(racine):
    for fichier in sorted(racine.rglob("index.html")):
        rel = fichier.relative_to(racine)
        if rel.parts[0] in EXCLUS or rel.parts[0].startswith((".", "_")):
            continue
        yield fichier, rel


def apres_deploiement(racine):
    """Chaque og:image doit repondre 200 en ligne. Ecrit ses defauts, ne bloque jamais."""
    import os
    cache, defauts, n = {}, [], 0
    for fichier, rel in pages_publiques(racine):
        n += 1
        segments = rel.parts[:-1]
        url = SITE + "/" + ("/".join(segments) + "/" if segments else "")
        tete = fichier.read_text(encoding="utf-8").split("</head>", 1)[0]
        image = lire(r'<meta property="og:image" content="([^"]*)"', tete)
        if not image:
            continue          # deja refuse par le controle bloquant
        code = image_repond(image, cache)
        if code != 200:
            defauts.append((url, image, code))
    for url, image, code in defauts:
        print("DEFAUT_EN_LIGNE og_image %s — %s repond %s" % (url, image, code))
        if os.environ.get("GITHUB_ACTIONS"):
            print("::warning title=og:image hors ligne::%s — %s repond %s" % (url, image, code))
    bilan = ("controle apres deploiement : %d pages, %d images distinctes demandees, %d defaut(s)"
             % (n, len(cache), len(defauts)))
    print("---")
    print(bilan)
    resume = os.environ.get("GITHUB_STEP_SUMMARY")
    if resume:
        with open(resume, "a", encoding="utf-8") as f:
            f.write("### Controle apres deploiement\n\n" + bilan + "\n\n")
            for url, image, code in defauts:
                f.write("- %s : `%s` repond %s\n" % (url, image, code))
    sys.exit(0)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    args = sys.argv[1:]
    racine = pathlib.Path(".")
    if "--racine" in args:
        racine = pathlib.Path(args[args.index("--racine") + 1])
    racine = racine.resolve()
    if "--apres-deploiement" in args:
        apres_deploiement(racine)
        return

    urls_plan = plan_du_site(racine)
    redirigees = sources_redirigees(racine)
    cache = {}
    defauts, vues = [], set()
    for fichier in sorted(racine.rglob("index.html")):
        rel = fichier.relative_to(racine)
        if rel.parts[0] in EXCLUS or rel.parts[0].startswith((".", "_")):
            continue
        if "/" + "/".join(rel.parts[:-1]) + "/" in redirigees:
            continue
        url, noindex, dd = controler_page(racine, fichier, set(urls_plan), cache)
        vues.add(url)
        defauts.extend(dd)

    # Le plan du site dans l'autre sens : chaque adresse du plan doit etre une page du depot.
    for u in urls_plan:
        if u[len(SITE):] in redirigees:
            defauts.append(("plan", u, "(plan)", "adresse redirigee par _redirects dans le sitemap"))
            continue
        if u not in vues:
            defauts.append(("plan", u, "(plan)", "adresse du sitemap sans page dans le depot"))
        if any(u.startswith(SITE + "/" + x + "/") for x in EXCLUS):
            defauts.append(("plan", u, "(plan)", "adresse exclue (embed/oauth) dans le sitemap"))

    # Les fichiers de la racine qui ne sont pas des pages doivent etre coupes du public.
    for nom in fichiers_racine_non_ranges(racine):
        defauts.append(("servi", SITE + "/" + nom, "(racine)",
                        "fichier servi publiquement : ajouter « /%s / 301 » a _redirects" % nom))

    for regle, url, dossier, detail in defauts:
        print("DEFAUT %s %s — %s" % (regle, url, detail))
    for chemin in sorted(PRIX_EN_ATTENTE):
        f = racine / chemin / "index.html"
        if f.exists():
            print("AVERTISSEMENT prix_amazon %s/%s — porte encore des prix Amazon releves a la main "
                  "(regle Amazon du 24/10/2026), non bloquant tant qu'elle est dans PRIX_EN_ATTENTE" % (SITE, chemin))

    print("---")
    print("pages controlees : %d (adresses dans sitemap.xml : %d)" % (len(vues), len(urls_plan)))
    print("defauts : %d" % len(defauts))
    par_regle = Counter(x[0] for x in defauts)
    par_dossier = Counter((x[2], x[0]) for x in defauts)
    for r in REGLES:
        if par_regle[r]:
            detail = ", ".join("%s %d" % (dos, n) for (dos, rr), n in sorted(par_dossier.items())
                               if rr == r)
            print("  %-12s %4d  (%s)" % (r, par_regle[r], detail))
    sys.exit(1 if defauts else 0)


if __name__ == "__main__":
    main()
