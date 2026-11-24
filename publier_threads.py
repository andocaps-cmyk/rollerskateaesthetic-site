#!/usr/bin/env python3
"""Publie sur Threads, par l'API officielle graph.threads.net, une page du site par publication. Stdlib seule.

Ecrit le 26/10/2026 (prompt un document interne du projet). Aucun modele dans la chaine.

SOURCE : la liste des pages du site (sitemap.xml), limitee a /skate/ et /guide/. PAS le flux Pinterest :
feed.xml est servi vide depuis le 26/10/2026 (_releves/PAUSE_PINTEREST.txt) et ce script n'y touche pas.

TEXTE (500 caracteres au plus, limite de l'API) : une idee concrete en une ou deux phrases, tiree du
paragraphe d'ouverture de la page (div.lede), a defaut de sa meta-description ; puis le lien de la page ;
puis la mention d'IA ; et la mention d'affiliation si la page porte un lien Amazon. Depuis le 29/10/2026 les
deux mentions TOURNENT (MENTIONS_IA, MENTIONS_AFF), jamais la meme deux fois de suite. Pas de mot-diese.

PROMESSE (20/11/2026, directive du 16/11/2026 « raison de cliquer ») : une phrase dit ce que la page contient de plus que
le fil, entre l'idee et le lien (promesse()). Elle est calculee sur la page elle-meme (questions h2.q, tableau, FAQ,
paragraphes, guide lie) et ne dit que ce qui s'y trouve ; sans rien de verifiable, la page ne part pas. Le debut de
phrase tourne (PROMESSES_DEBUT), jamais le meme deux fois de suite. Rien d'autre ne change.

RYTHME ET ROTATION (29/10/2026, rattrapage du prompt un document interne) :
- 07/11/2026 (un document interne, decision du propriétaire du 02/11/2026 a 3 h 50) :
  UN seul passage programme par jour (threads.yml) et plafond PERMANENT de 1 publication par jour, code en dur
  (PLAFOND_JOUR). Plus de palier 3 puis 5. Motifs : Threads bloque les comptes au comportement automatise
  (blocage « personne reelle » du 29 au 31/10) ; la moitie des vues vient des reponses, personne ne repond ;
- garde (garde()) : plafond du jour PLAFOND_JOUR ; PLAFOND_ALERTE si un signal d'alerte est actif
  (_releves/alerte_threads.txt ; 1 aujourd'hui, a mettre a 0 pour que l'alerte coupe la chaine) ;
  jamais moins de 2 heures apres la precedente ;
- categories (rotation_publications.py) : jamais deux fois la meme le meme jour, ni deux de suite ; une seule
  page commerciale par jour (guide d'achat ou page a lien Amazon) ;
- ouverture : les quatre premiers mots ne reprennent jamais ceux d'une des 30 dernieres publications ;
- signaux d'alerte (ecrits dans _releves/alerte_threads.txt, qui ramene a 1 par jour tant qu'il existe) :
  refus HTTP de l'API a la publication, erreur qui parle de restriction ou de spam, vues a zero sur toutes
  les publications des 3 derniers jours alors que les premieres en avaient. Un courriel de Meta qui parle de
  restriction : l'ecrire a la main dans ce fichier (une ligne datee). Supprimer le fichier = lever l'alerte.
  Le fichier ne sert plus qu'aux vraies alertes : il ne porte plus le rythme.
  --simuler : essai a blanc de 21 jours a 1 par jour, qui verifie chacune de ces regles.

REGLES DURES (ce que Pinterest a sanctionne le 26/10/2026, voir un document interne) :
- registre _releves/publies_threads.tsv : une page inscrite n'est JAMAIS republiee ;
- un texte dont plus de la moitie des mots (hors mentions, lien et mots-outils) se retrouvent dans un
  texte deja publie ne part pas ;
- « nothing to buy » n'apparait jamais ;
- une ou deux publications par passage, jamais plus (plafond code en dur) ;
- aucune modification, aucune suppression, aucune interaction avec d'autres comptes.
Un refus de l'API s'ecrit dans _releves/echecs_threads.tsv et n'arrete pas les suivantes (lecon Bluesky du 11/10).

Variables : THREADS_ACCESS_TOKEN (jeton long, 60 jours), THREADS_USER_ID (sinon lu par /me).
  --rafraichir-jeton FICHIER : renouvelle le jeton (GET /refresh_access_token) et l'ecrit dans FICHIER.
"""
import argparse, glob, html, json, os, random, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

API = "https://graph.threads.net/v1.0"
SITE = "https://rollerskateaesthetic.com"
SITEMAP = "sitemap.xml"
REG = "_releves/publies_threads.tsv"
ECHECS = "_releves/echecs_threads.tsv"
EXPIRE = "_releves/jeton_threads_expire.txt"
MENTIONS_IA = ["Written with AI from a skater's notes.", "Drafted with AI, based on a skater's notes.",
               "AI-written from notes by a skater.", "Made with AI from real skating notes."]
MENTIONS_AFF = ["This page contains affiliate links.", "Some links on this page are affiliate links.",
                "The page includes affiliate links."]
MENTION_IA, MENTION_AFF = MENTIONS_IA[0], MENTIONS_AFF[0]
PROMESSES_DEBUT = ["On the full page:", "The page adds:", "Past this post, the page has:"]
ALERTE = "_releves/alerte_threads.txt"
# 10/11/2026 (chef, poste reseaux) : un refus de type BLOCAGE suspend la chaine (suspension.py) ; plus aucun appel
# avant le prochain essai ; un seul essai ; succes = levee. Origine : Instagram bloque par Meta (4/2207051) du 08/11.
SUSP = "_releves/suspension_threads.json"
RELEVE_PUBS = "_releves/releve_threads_publications.csv"
DEBUT_COMPTE = datetime(2026, 10, 28, tzinfo=timezone.utc)
PLAFOND_JOUR = 1      # permanent depuis le 07/11/2026 (decision du propriétaire du 02/11/2026, 3 h 50)
PLAFOND_ALERTE = 1    # sous signal d'alerte ; 0 = l'alerte arrete la chaine
JOURS_SIMULES = 21
ECART_MIN = 2 * 3600
OUVERTURE_MOTS, OUVERTURE_DERNIERES = 4, 30
ALERTE_MOTS = re.compile(r"restrict|spam|suspend|blocked|bloqu|violat|abuse", re.I)
MAX_CHARS = 500
IDEE_MAX = 300
PLAFOND = 2
SEUIL_PROCHE = 0.5
from controle_fins_flux import INTERDIT   # une seule regle « nothing to buy » pour tout le depot
import rotation_publications as rot
import suspension as su
JUNK = re.compile(r"nothing to buy|free beginner|free guide|no sign-up|sign[- ]up|written with an? ai|affiliate|"
                  r"amazon associate|qualifying purchases|\bAI\b|we do not show prices", re.I)
MOTS_OUTILS = set("""a an and are as at be but by can do does for from has have how if in into is it its just more
most no not of on one or so than that the their them then there these they this to too up was we what when where
which while who why will with you your yours it's don't isn't can't""".split())


def maintenant():
    return datetime.now(timezone.utc)


def lire_lignes(chemin):
    if not os.path.exists(chemin):
        return []
    with open(chemin, encoding="utf-8") as f:
        return [l.rstrip("\n") for l in f if l.strip() and not l.startswith("#")]


def ajouter_ligne(chemin, entete, ligne):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    neuf = not os.path.exists(chemin)
    with open(chemin, "a", encoding="utf-8") as f:
        if neuf:
            f.write(entete + "\n")
        f.write(ligne + "\n")
        f.flush(); os.fsync(f.fileno())


def propre(texte):
    return re.sub(r"\s+", " ", texte.replace("\t", " ")).strip()


def note_echec(cle, motif):
    ajouter_ligne(ECHECS, "# horodatage_utc\tcle\tmotif",
                  "%s\t%s\t%s" % (maintenant().strftime("%Y-%m-%d %H:%M:%S"), cle, propre(motif)[:400]))


def texte_html(fragment):
    return propre(html.unescape(re.sub(r"<[^>]+>", " ", fragment)))


def phrases(texte):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])", texte) if s.strip()]


def traits_page(s):
    """Ce que la page contient en plus du paragraphe d'ouverture, lu dans son HTML (base de la promesse)."""
    corps = s.split("<main", 1)[1].split("</main>")[0] if "<main" in s else s
    faq = re.search(r'<section class="faq">(.*?)</section>', corps, re.S)
    guide = re.search(r'<!-- lien-guide -->\s*<div class="gear-note"><p><strong>[^<]*</strong> <a href="https://rollerskateaesthetic\.com/(guide|tools)/[^"]*">([^<]*)</a>', corps)
    reste = re.sub(r'<div class="(?:lede|gear-note|next|scope)".*?</div>', "", corps, flags=re.S)
    reste = re.sub(r"<aside.*?</aside>", "", reste, flags=re.S)
    reste = re.sub(r'<p class="[^"]*">.*?</p>', "", reste, flags=re.S)
    return {"questions": [texte_html(q) for q in re.findall(r'<h2 class="q">(.*?)</h2>', corps, re.S)],
            "faq": len(re.findall(r"<h3", faq.group(1))) if faq else 0,
            "table": "<table" in corps,
            "paras": len(re.findall(r"<p>.*?</p>", reste, re.S)),
            "guide": texte_html(guide.group(2)) if guide else "",
            "guide_type": guide.group(1) if guide else ""}


def detail_promesse(page):
    """Ce que la page contient de plus, en un groupe de mots exact ; None si rien de verifiable."""
    t = page["traits"]
    if page["cle"].startswith("guide/"):
        morceaux = (["a table"] if t["table"] else []) + (["%d beginner FAQ answers" % t["faq"]] if t["faq"] >= 2 else [])
        return " and ".join(morceaux) or None
    if t["questions"]:
        n = len(t["questions"])
        return ("%d beginner questions answered, such as “%s”" % (n, t["questions"][-1]) if n > 1
                else "a beginner question answered: “%s”" % t["questions"][0])
    if t["paras"] >= 2 and t["guide"]:
        return "%d more paragraphs of detail and a link to %s “%s”" % (
            t["paras"], "the buying guide" if t["guide_type"] == "guide" else "the free tool", t["guide"])
    return None


def promesse(page, debut):
    d = detail_promesse(page)
    return "%s %s." % (debut, d) if d else None


def lire_pages():
    """Pages /skate/ et /guide/ du sitemap, avec leur fichier local, plus ancienne d'abord."""
    try:
        sm = open(SITEMAP, encoding="utf-8").read()
    except OSError as e:
        sys.exit("ERREUR: %s illisible: %s" % (SITEMAP, e))
    pages = []
    for url in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm):
        m = re.match(re.escape(SITE) + r"/((?:skate|guide)/[^/]+)/$", url)
        if not m:
            continue
        cle = m.group(1)
        fichier = os.path.join(cle, "index.html")
        if not os.path.isfile(fichier):
            continue
        s = open(fichier, encoding="utf-8").read()
        if re.search(r'<meta name="robots" content="[^"]*noindex', s):
            continue
        lede = re.search(r'<div class="lede">(.*?)</div>', s, re.S)
        meta = re.search(r'<meta name="description" content="([^"]*)"', s)
        ecrit = re.search(r'class="byline">\s*Written (\d{1,2} \w+ \d{4})', s)
        try:
            date = datetime.strptime(ecrit.group(1), "%d %B %Y") if ecrit else datetime(2100, 1, 1)
        except ValueError:
            date = datetime(2100, 1, 1)
        pages.append({"cle": cle, "url": url, "date": date, "traits": traits_page(s),
                      "lede": texte_html(lede.group(1)) if lede else "",
                      "meta": html.unescape(meta.group(1)).strip() if meta else "",
                      "amazon": bool(re.search(r'href="https?://(?:www\.)?amazon\.', s))})
    pages.sort(key=lambda p: (p["date"], p["cle"]))
    return pages


def idee(page, maxi=IDEE_MAX):
    """Une ou deux phrases completes, sans mention ni formule, dans maxi caracteres (publier_reseaux.py s'en sert aussi pour Bluesky)."""
    for source in (page["lede"], page["meta"]):
        retenues = []
        for s in phrases(source):
            if JUNK.search(s):
                continue
            if s[-1] not in ".!?":
                break
            if len(" ".join(retenues + [s])) > maxi:
                break
            retenues.append(s)
            if len(retenues) == 2:
                break
        if retenues:
            return " ".join(retenues)
    return None


def avec_src(url, reseau):
    """07/11/2026 (correctif 6 de la remontee du 02/11, case N.8) : une adresse distincte par plateforme,
    lue par Cloudflare Web Analytics. Jamais sur une adresse Amazon."""
    if not url or re.search(r"amazon\.|amzn\.to", url) or "src=" in url:
        return url
    return url + ("&" if "?" in url else "?") + "src=" + reseau


def composer(page, ia=MENTION_IA, aff=MENTION_AFF, debut=PROMESSES_DEBUT[0]):
    pro = promesse(page, debut)
    if not pro:
        return None
    url = avec_src(page["url"], "threads")
    fin = "\n\n" + ia + (" " + aff if page["amazon"] else "")
    i = idee(page, min(IDEE_MAX, MAX_CHARS - len(pro) - len(url) - len(fin) - 4))
    if not i:
        return None
    t = i + "\n\n" + pro + "\n" + url + fin
    if len(t) > MAX_CHARS or INTERDIT.search(t):
        return None
    return t


def mention_de(texte, variantes):
    """La variante presente dans le texte (None si aucune)."""
    for v in variantes:
        if v in texte:
            return v
    return None


def ouverture(texte):
    return tuple(re.findall(r"[a-z0-9']+", texte.lower())[:OUVERTURE_MOTS])


def mots(texte):
    corps = texte
    for m in MENTIONS_IA + MENTIONS_AFF:
        corps = corps.replace(m, " ")
    corps = re.sub(r"https?://\S+", " ", corps)
    return set(w for w in re.findall(r"[a-z0-9']+", corps.lower()) if w not in MOTS_OUTILS and len(w) > 1)


def trop_proche(texte, publies):
    m = mots(texte)
    if not m:
        return "aucun mot"
    for cle, ancien in publies:
        part = len(m & mots(ancien)) / len(m)
        if part > SEUIL_PROCHE:
            return "%.0f %% de ses mots deja dans le texte publie de %s" % (part * 100, cle)
    return None


def lire_registre():
    """Publications passees, plus ancienne d'abord. Colonnes : cle, id, date, texte, horodatage UTC, categorie
    (les deux dernieres depuis le 29/10/2026 ; une ligne plus ancienne est classee a la volee)."""
    out = []
    for l in lire_lignes(REG):
        c = l.split("\t")
        if len(c) < 4:
            continue
        h = None
        if len(c) >= 5 and c[4]:
            try:
                h = datetime.strptime(c[4], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                h = None
        out.append({"cle": c[0], "id": c[1], "date": c[2], "texte": c[3].replace("\\n", "\n"), "heure": h,
                    "categorie": c[5] if len(c) >= 6 and c[5] else rot.categorie(c[0]),
                    "commerciale": c[0].startswith("guide/") or bool(mention_de(c[3], MENTIONS_AFF))})
    return out


def alerte_vues():
    """Vues a zero sur toutes les publications des 3 derniers jours, alors qu'une plus ancienne en a eu."""
    lignes = [l.split(";") for l in lire_lignes(RELEVE_PUBS)[1:]]
    lignes = [c for c in lignes if len(c) >= 4 and c[3].isdigit()]
    if not lignes:
        return None
    dernier = max(c[0] for c in lignes)
    vues = {}
    for c in lignes:
        vues[c[1]] = max(vues.get(c[1], 0), int(c[3]))
    borne = (datetime.strptime(dernier, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
    reg = lire_registre()
    recentes = [r["cle"] for r in reg if borne <= r["date"] < dernier and r["cle"] in vues]
    anciennes = [r["cle"] for r in reg if r["date"] < borne and vues.get(r["cle"], 0) > 0]
    if recentes and anciennes and all(vues[k] == 0 for k in recentes):
        return "vues a zero sur les %d publications du %s au %s (releve du %s), alors que %d plus anciennes en ont eu" % (
            len(recentes), borne, dernier, dernier, len(anciennes))
    return None


def lire_alerte():
    l = lire_lignes(ALERTE)
    return l[-1] if l else None


def lever_alerte(motif):
    ajouter_ligne(ALERTE, "# Signal d'alerte Threads : tant que ce fichier existe, %d publication par jour au plus. " % PLAFOND_ALERTE +
                          "Supprimer le fichier leve l'alerte. Reporter la cause dans l'etat du projet.",
                  "%s\t%s" % (maintenant().strftime("%Y-%m-%d %H:%M:%S"), propre(motif)[:400]))
    print("::warning::Signal d'alerte Threads : %s -> plafond ramene a %d par jour" % (motif, PLAFOND_ALERTE))


def plafond_du_jour(quand, alerte):
    return min(PLAFOND_ALERTE, PLAFOND_JOUR) if alerte else PLAFOND_JOUR


def garde(reg, quand, alerte):
    """Motif de refus du passage, ou None si une publication peut partir."""
    jour = quand.strftime("%Y-%m-%d")
    plafond = plafond_du_jour(quand, alerte)
    faites = sum(1 for r in reg if r["date"] == jour)
    if faites >= plafond:
        return "plafond du jour atteint (%d/%d%s)" % (faites, plafond, ", signal d'alerte : %s" % alerte if alerte else "")
    heures = [r["heure"] for r in reg if r["heure"]]
    if heures and (quand - max(heures)).total_seconds() < ECART_MIN:
        return "derniere publication il y a %d min (moins de 2 h)" % ((quand - max(heures)).total_seconds() // 60)
    return None


def choisir(pages, reg, quand, combien):
    """Pages a publier ce passage, avec leur texte (rotation des categories, des ouvertures et des mentions)."""
    deja = set(r["cle"] for r in reg)
    publies = [(r["cle"], r["texte"]) for r in reg]
    ouvertures = set(ouverture(r["texte"]) for r in reg[-OUVERTURE_DERNIERES:])
    table = rot.lire_categories()
    candidats = []
    for p in pages:
        if p["cle"] in deja:
            continue
        t = composer(p)
        if not t:
            continue
        if ouverture(t) in ouvertures or trop_proche(t, publies):
            continue
        candidats.append(dict(p, categorie=rot.categorie(p["cle"], table=table)))
    hist = [(r["date"], r["categorie"], r["commerciale"]) for r in reg]
    pris = rot.choisir_pages(candidats, hist, quand.strftime("%Y-%m-%d"), combien,
                             commerciale=lambda p: p["categorie"] == rot.COMMERCIALE or p["amazon"])
    ia = mention_de(reg[-1]["texte"], MENTIONS_IA) if reg else None
    debut = mention_de(reg[-1]["texte"], PROMESSES_DEBUT) if reg else None
    aff = next((mention_de(r["texte"], MENTIONS_AFF) for r in reversed(reg) if mention_de(r["texte"], MENTIONS_AFF)), None)
    out = []
    for p in pris:
        ia = rot.choisir_variante(MENTIONS_IA, ia)
        debut = rot.choisir_variante(PROMESSES_DEBUT, debut)
        if p["amazon"]:
            aff = rot.choisir_variante(MENTIONS_AFF, aff)
        out.append(dict(p, texte=composer(p, ia, aff or MENTIONS_AFF[0], debut)))
    return out, len(candidats)


def simuler(pages, jours=JOURS_SIMULES):
    """Essai a blanc sur un registre vide en memoire : 21 jours a PLAFOND_JOUR par jour. Code 1 si une regle est
    violee (categorie repetee dans un jour ou deux de suite, ouverture repetee sur 30, mention repetee deux fois
    de suite, deux pages commerciales le meme jour, garde des 2 heures ou plafond inoperant)."""
    reg, violations = [], []
    debut = DEBUT_COMPTE.replace(hour=7, minute=20)
    for j in range(jours):
        for k in range(PLAFOND_JOUR):
            quand = debut + timedelta(days=j, hours=3 * k)
            g = garde(reg, quand, None)
            if g:
                violations.append("%s : garde refuse a tort (%s)" % (quand, g))
                continue
            choix, _ = choisir(pages, reg, quand, 1)
            if not choix:
                print("%s : aucune page possible" % quand.strftime("%Y-%m-%d %H:%M"))
                continue
            p = choix[0]
            reg.append({"cle": p["cle"], "id": "-", "date": quand.strftime("%Y-%m-%d"), "texte": p["texte"],
                        "heure": quand, "categorie": p["categorie"],
                        "commerciale": p["categorie"] == rot.COMMERCIALE or p["amazon"]})
        jour = (debut + timedelta(days=j)).strftime("%Y-%m-%d")
        du_jour = [r for r in reg if r["date"] == jour]
        print("%s (%d) : %s" % (jour, len(du_jour), " | ".join(
            "%s%s" % (r["categorie"], " [aff]" if mention_de(r["texte"], MENTIONS_AFF) else "") for r in du_jour)))
        if len(set(r["categorie"] for r in du_jour)) != len(du_jour):
            violations.append("%s : categorie repetee dans la journee" % jour)
        if sum(1 for r in du_jour if r["commerciale"]) > 1:
            violations.append("%s : plus d'une page commerciale" % jour)
    dernier = reg[-1]["heure"]
    if not garde(reg, dernier + timedelta(minutes=30), None):
        violations.append("garde des 2 heures inoperante")
    if not garde(reg, dernier.replace(hour=23, minute=59), None):
        violations.append("plafond du jour inoperant")
    if len(reg) > jours * PLAFOND_JOUR or any(sum(1 for r in reg if r["date"] == d) > PLAFOND_JOUR
                                               for d in set(r["date"] for r in reg)):
        violations.append("plus de %d publication(s) un meme jour" % PLAFOND_JOUR)
    if plafond_du_jour(dernier, "essai") > PLAFOND_JOUR:
        violations.append("le signal d'alerte releve le plafond au lieu de le baisser")
    lendemain = dernier.replace(hour=7, minute=20) + timedelta(days=1)
    essai = reg + [{"cle": "-", "date": lendemain.strftime("%Y-%m-%d"), "texte": "", "heure": lendemain,
                    "categorie": "-", "commerciale": False}]
    if not garde(essai, lendemain + timedelta(hours=5), "essai"):
        violations.append("plafond d'alerte inoperant")
    for a, b in zip(reg, reg[1:]):
        if a["categorie"] == b["categorie"]:
            violations.append("%s puis %s : meme categorie de suite" % (a["cle"], b["cle"]))
        if mention_de(a["texte"], MENTIONS_IA) == mention_de(b["texte"], MENTIONS_IA):
            violations.append("%s puis %s : meme mention d'IA" % (a["cle"], b["cle"]))
    if not all(mention_de(r["texte"], PROMESSES_DEBUT) for r in reg):
        violations.append("texte sans promesse de page")
    for a, b in zip(reg, reg[1:]):
        if mention_de(a["texte"], PROMESSES_DEBUT) == mention_de(b["texte"], PROMESSES_DEBUT):
            violations.append("%s puis %s : meme debut de promesse" % (a["cle"], b["cle"]))
    affs = [mention_de(r["texte"], MENTIONS_AFF) for r in reg if mention_de(r["texte"], MENTIONS_AFF)]
    if any(a == b for a, b in zip(affs, affs[1:])):
        violations.append("meme mention d'affiliation deux fois de suite")
    for i, r in enumerate(reg):
        if ouverture(r["texte"]) in set(ouverture(x["texte"]) for x in reg[max(0, i - OUVERTURE_DERNIERES):i]):
            violations.append("%s : ouverture repetee" % r["cle"])
    if any(INTERDIT.search(r["texte"]) for r in reg) or not all(mention_de(r["texte"], MENTIONS_IA) for r in reg):
        violations.append("texte sans mention d'IA ou avec « nothing to buy »")
    if any(r["amazon"] and not mention_de(r["texte"], MENTIONS_AFF) for r in [dict(x, amazon=bool(next(
            (p["amazon"] for p in pages if p["cle"] == x["cle"]), False))) for x in reg]):
        violations.append("page a lien Amazon sans mention d'affiliation")
    print("Simulation : %d publications sur %d jours, %d mentions d'affiliation ; violations : %d"
          % (len(reg), jours, len(affs), len(violations)))
    for v in violations:
        print("  VIOLATION " + v)
    return 1 if violations else 0


def appel(methode, chemin, params):
    donnees = urllib.parse.urlencode(params).encode()
    url = chemin if chemin.startswith("https://") else API + chemin
    if methode == "GET":
        url, donnees = url + "?" + donnees.decode(), None
    req = urllib.request.Request(url, data=donnees, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        corps = e.read()[:400].decode("utf-8", "replace")
        raise RuntimeError("HTTP %s sur %s : %s" % (e.code, chemin, corps))
    except Exception as e:
        raise RuntimeError("reseau sur %s : %s" % (chemin, e))


def rafraichir(fichier):
    jeton = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not jeton:
        sys.exit("ERREUR: THREADS_ACCESS_TOKEN absent")
    r = appel("GET", "https://graph.threads.net/refresh_access_token", {"grant_type": "th_refresh_token", "access_token": jeton})
    neuf, duree = r.get("access_token"), int(r.get("expires_in") or 0)
    if not neuf:
        sys.exit("ERREUR: reponse de renouvellement sans jeton")
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(neuf)
    fin = datetime.fromtimestamp(time.time() + duree, timezone.utc).strftime("%Y-%m-%d")
    with open(EXPIRE, "w", encoding="utf-8") as f:
        f.write("# jeton Threads renouvele le %s UTC ; expire le %s (expires_in=%d s)\n%s\n"
                % (maintenant().strftime("%Y-%m-%d %H:%M"), fin, duree, fin))
    print("Jeton renouvele, expire le %s (%s)" % (fin, "meme chaine" if neuf == jeton else "chaine nouvelle"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-posts", type=int, default=1)
    ap.add_argument("--attente-max", type=int, default=0, help="attente au hasard, 0 a N secondes, avant de publier")
    ap.add_argument("--simuler", action="store_true", help="essai a blanc : 21 jours a 1 par jour")
    ap.add_argument("--rafraichir-jeton", metavar="FICHIER")
    a = ap.parse_args()
    if a.rafraichir_jeton:
        return rafraichir(a.rafraichir_jeton)
    if a.simuler:
        return simuler(lire_pages())
    if a.max_posts > PLAFOND:
        sys.exit("ERREUR: --max-posts %d refuse, plafond %d par passage" % (a.max_posts, PLAFOND))

    reg = lire_registre()
    vues = alerte_vues()
    if vues and not a.dry_run and not any(vues.split(" (")[0] in l for l in lire_lignes(ALERTE)):
        lever_alerte(vues)
    alerte = lire_alerte() or (vues if a.dry_run else None)
    if alerte:
        print("Signal d'alerte actif : %s" % alerte)
    etat_susp, e_susp = su.etat_de(SUSP)
    if etat_susp != "libre":
        print("Suspension : %s" % su.phrase(etat_susp, e_susp))
    if etat_susp == "suspendu" and not a.dry_run:
        print("::warning::Chaine Threads SUSPENDUE (refus de type blocage) : aucun appel a Meta. %s" % su.phrase(etat_susp, e_susp))
        return
    if a.attente_max > 0 and not a.dry_run:
        pause = random.randint(0, a.attente_max)
        print("Attente au hasard avant publication : %d s" % pause)
        time.sleep(pause)
    quand = maintenant()
    refus = garde(reg, quand, alerte)
    if refus:
        print("GARDE : passage refuse, %s. Rien n'est publie." % refus)
        return
    plafond = plafond_du_jour(quand, alerte)
    reste = plafond - sum(1 for r in reg if r["date"] == quand.strftime("%Y-%m-%d"))
    pages = lire_pages()
    a_faire, nb = choisir(pages, reg, quand, min(a.max_posts, reste) if not a.dry_run else a.max_posts)
    print("Pages candidates: %d ; publiables apres gardes de texte: %d ; registre: %d ; plafond du jour: %d ; a publier: %d"
          % (len(pages), nb, len(reg), plafond, len(a_faire)))
    if a.dry_run:
        for p in a_faire:
            print("---- %s [%s] (%d car.)%s ----\n%s\n" % (p["cle"], p["categorie"], len(p["texte"]),
                                                       " [amazon]" if p["amazon"] else "", p["texte"]))
        return
    if not a_faire:
        print("Rien a publier.")
        return

    jeton = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not jeton:
        sys.exit("ERREUR: THREADS_ACCESS_TOKEN absent de l'environnement")
    essai = etat_susp == "essai"
    if essai:
        su.prendre_essai(SUSP)
        print("::warning::Essai UNIQUE apres suspension : %s" % su.phrase(etat_susp, e_susp))
    uid = os.environ.get("THREADS_USER_ID", "").strip() or appel("GET", "/me", {"fields": "id", "access_token": jeton})["id"]
    echecs = 0
    for p in a_faire:
        try:
            conteneur = appel("POST", "/%s/threads" % uid, {"media_type": "TEXT", "text": p["texte"],
                                                           "link_attachment": avec_src(p["url"], "threads"), "access_token": jeton})["id"]
            time.sleep(5)
            media = appel("POST", "/%s/threads_publish" % uid, {"creation_id": conteneur, "access_token": jeton})["id"]
        except (RuntimeError, KeyError) as e:
            echecs += 1
            print("ECHEC %s : %s" % (p["cle"], e), file=sys.stderr)
            note_echec(p["cle"], str(e))
            if str(e).startswith("HTTP") or ALERTE_MOTS.search(str(e)):
                lever_alerte("refus de l'API a la publication de %s : %s" % (p["cle"], propre(str(e))[:250]))
            motif_b = su.blocage(str(e))
            if motif_b:
                s = su.poser(SUSP, "threads", "%s : %s" % (p["cle"], motif_b))
                print("::error::BLOCAGE Threads, chaine suspendue (refus n°%d), prochain essai %s : %s"
                      % (s["refus"], s["prochain_essai"], motif_b))
                break
            continue
        if essai:
            su.lever(SUSP, "essai reussi : %s publie (%s)" % (p["cle"], media))
            essai = False
        ajouter_ligne(REG, "# cle\tid_threads\tdate_utc\ttexte\thorodatage_utc\tcategorie",
                      "%s\t%s\t%s\t%s\t%s\t%s" % (p["cle"], media, maintenant().strftime("%Y-%m-%d"),
                                                  p["texte"].replace("\n", "\\n"),
                                                  maintenant().strftime("%Y-%m-%d %H:%M:%S"), p["categorie"]))
        try:
            lien = appel("GET", "/" + media, {"fields": "permalink", "access_token": jeton}).get("permalink", "?")
        except RuntimeError as e:
            lien = "lien illisible (%s)" % e
        print("POSTED %s [%s] -> %s %s" % (p["cle"], p["categorie"], media, lien))
    if echecs:
        sys.exit("%d publication(s) refusee(s), detail dans %s" % (echecs, ECHECS))


if __name__ == "__main__":
    main()
