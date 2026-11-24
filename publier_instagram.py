#!/usr/bin/env python3
"""Publie sur Instagram, par l'API officielle (Instagram API with Instagram Login, graph.instagram.com), un carrousel
par page du site. Stdlib seule pour la publication ; Pillow pour fabriquer les images (visuels_reseaux.py).

Ecrit le 29/10/2026 (prompt un document interne du projet). Aucun modele dans la chaine.
Regles lues le 29/10/2026 (un document interne, entree instagram) : 100 publications par l'API par 24 h glissantes,
un carrousel comptant pour une ; compte professionnel ; JPEG seulement ; 10 elements au plus par carrousel ; avec un
role sur l'app (Standard Access), pas de revue d'app pour publier sur son propre compte.

SOURCE : les pages /skate/ et /guide/ du sitemap (publier_threads.lire_pages), jamais feed.xml (pause Pinterest).

CARROUSEL : l'epingle de la page puis 2 ou 3 diapos d'etapes (visuels_reseaux.py), en JPEG 1080 x 1350, servies par le
site sous /ig/ (le depot est prive : Instagram ne peut lire une image que sur une adresse publique). Le stock d'images
(--stocker) couvre les 2 prochaines pages de chaque categorie ; la chaine le refait a chaque passage, et la
« Publication controlee » le met en ligne. Une page dont la premiere image ne repond pas 200 en ligne ne part pas.

LEGENDE (2 200 caracteres au plus, propre a la page) : le titre de la page ; une ou deux phrases de son paragraphe
d'ouverture (publier_threads.idee) ; 3 a 5 mots-dieses qui tournent ; puis la fin, qui tourne (FINS, toutes disent
« link in bio » : un lien dans la legende ne serait pas cliquable) ; puis la mention d'IA et, si la page porte un
lien Amazon, la mention d'affiliation, qui tournent comme sur Threads. Jamais « nothing to buy ».

RYTHME (garde()) : 2 publications par jour pendant 14 jours a compter de la premiere, puis 3 ; 1 si un signal
d'alerte est actif (_releves/alerte_instagram.txt) ; jamais moins de 3 heures apres la precedente ; une seule par
passage. Rotation des categories : rotation_publications.choisir_pages (une seule page commerciale par jour).

REGLES DURES (lecon de Pinterest, un document interne) : registre _releves/publies_instagram.tsv, une page
inscrite n'est JAMAIS republiee ; un texte dont plus de la moitie des mots se retrouvent dans un texte deja publie ne
part pas ; aucune modification, aucune suppression, aucune interaction avec d'autres comptes.

Variables : INSTAGRAM_ACCESS_TOKEN (jeton long, 60 jours), INSTAGRAM_USER_ID (sinon lu par /me).
  --rafraichir-jeton FICHIER : renouvelle le jeton (GET /refresh_access_token) et l'ecrit dans FICHIER.
  --stocker : fabrique les images des prochaines pages et retire celles des pages publiees depuis plus de 3 jours.
  --simuler : essai a blanc de 14 jours a 2 puis 7 jours a 3.
"""
import argparse, json, os, random, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

import publier_threads as pt
import rotation_publications as rot
from controle_fins_flux import INTERDIT
import suspension as su

API = "https://graph.instagram.com/v23.0"
SITE = pt.SITE
REG = "_releves/publies_instagram.tsv"
ECHECS = "_releves/echecs_instagram.tsv"
EXPIRE = "_releves/jeton_instagram_expire.txt"
ALERTE = "_releves/alerte_instagram.txt"
# 10/11/2026 (chef, poste reseaux) : un refus de type BLOCAGE suspend la chaine (suspension.py) ; plus aucun appel
# avant le prochain essai ; un seul essai ; succes = levee. Origine : Instagram bloque par Meta (4/2207051) du 08/11.
SUSP = "_releves/suspension_instagram.json"
# Page refusee 4 fois par Meta (sous-code 2207051) : exclue pour toujours de la selection (decision du 21/11/2026).
EXCLUES = {"skate/dont-push-hard-on-wet-ground"}
RELEVE_PUBS = "_releves/releve_instagram_publications.csv"
FINS = ["Full guide: link in bio.", "The full guide is free, link in bio.",
        "More in the free guide (link in bio).", "Free guide, no sign-up: link in bio."]
MENTIONS_IA, MENTIONS_AFF = pt.MENTIONS_IA, pt.MENTIONS_AFF
DIESES = ["#rollerskating", "#learntoskate", "#skatetips", "#beginnerskater", "#rollerskate", "#skatinglife",
          "#rollerskatinglife", "#skateeveryday"]
DIESES_CAT = {"guide-achat": "#rollerskategear", "materiel": "#skategear", "figures-sauts": "#rollerdance",
              "dehors": "#outdoorskating", "corps": "#skatefitness", "freiner": "#skatesafety",
              "chutes-protections": "#skatesafety", "tourner": "#skatetechnique", "equilibre-posture": "#skatetechnique"}
PALIER_JOURS, PLAFOND_DEBUT, PLAFOND_ENSUITE, PLAFOND_ALERTE = 14, 2, 3, 1
ECART_MIN = 3 * 3600
PLAFOND = 1
MAX_CHARS = 2200
STOCK_PAR_CATEGORIE = 2
GARDER_JOURS = 3
ALERTE_MOTS = pt.ALERTE_MOTS


def maintenant():
    return datetime.now(timezone.utc)


def note_echec(cle, motif):
    pt.ajouter_ligne(ECHECS, "# horodatage_utc\tcle\tmotif",
                     "%s\t%s\t%s" % (maintenant().strftime("%Y-%m-%d %H:%M:%S"), cle, pt.propre(motif)[:400]))


def dieses(page, rang):
    """3 a 5 mots-dieses : celui de la categorie s'il existe, l'inline ou le quad selon la page, puis 3 du tronc
    commun, decales de 3 a chaque publication (jamais la meme serie deux fois de suite)."""
    out = []
    if DIESES_CAT.get(page["categorie"]):
        out.append(DIESES_CAT[page["categorie"]])
    if "inline" in page["cle"]:
        out.append("#inlineskating")
    elif "quad" in page["cle"]:
        out.append("#quadskates")
    for i in range(3):
        out.append(DIESES[(rang * 3 + i) % len(DIESES)])
    return out[:5]


def corps(page):
    """Titre puis une ou deux phrases du paragraphe d'ouverture."""
    import visuels_reseaux as vr
    i = pt.idee(page, 700)
    return (vr.titre(page) + "\n\n" + i) if i else None


def composer(page, fin, ia, aff, tags):
    c = corps(page)
    if not c:
        return None
    t = c + "\n\n" + " ".join(tags) + "\n\n" + fin + "\n" + ia
    if page["amazon"]:
        t += " " + aff
    if len(t) > MAX_CHARS or INTERDIT.search(t) or re.search(r"https?://", t):
        return None
    return t


def mots(texte):
    for m in FINS:
        texte = texte.replace(m, " ")
    return pt.mots(re.sub(r"#\w+", " ", texte))


def trop_proche(texte, publies):
    m = mots(texte)
    if not m:
        return "aucun mot"
    for cle, ancien in publies:
        part = len(m & mots(ancien)) / len(m)
        if part > pt.SEUIL_PROCHE:
            return "%.0f %% de ses mots deja dans le texte publie de %s" % (part * 100, cle)
    return None


def lire_registre():
    """Colonnes : cle, id, date, texte, horodatage UTC, categorie, fin, mention IA, mention affiliation, images."""
    out = []
    for l in pt.lire_lignes(REG):
        c = l.split("\t")
        if len(c) < 6:
            continue
        try:
            h = datetime.strptime(c[4], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            h = None
        out.append({"cle": c[0], "id": c[1], "date": c[2], "texte": c[3].replace("\\n", "\n"), "heure": h,
                    "categorie": c[5], "fin": c[6] if len(c) > 6 else "", "ia": c[7] if len(c) > 7 else "",
                    "aff": c[8] if len(c) > 8 else "",
                    "commerciale": c[5] == rot.COMMERCIALE or bool(c[8] if len(c) > 8 else "")})
    return out


def debut_compte(reg):
    return datetime.strptime(reg[0]["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc) if reg else None


def plafond_du_jour(reg, quand, alerte):
    if alerte:
        return PLAFOND_ALERTE
    debut = debut_compte(reg)
    jour = quand.replace(hour=0, minute=0, second=0, microsecond=0)
    return PLAFOND_DEBUT if not debut or (jour - debut).days < PALIER_JOURS else PLAFOND_ENSUITE


def garde(reg, quand, alerte):
    jour = quand.strftime("%Y-%m-%d")
    plafond = plafond_du_jour(reg, quand, alerte)
    faites = sum(1 for r in reg if r["date"] == jour)
    if faites >= plafond:
        return "plafond du jour atteint (%d/%d%s)" % (faites, plafond, ", signal d'alerte : %s" % alerte if alerte else "")
    heures = [r["heure"] for r in reg if r["heure"]]
    if heures and (quand - max(heures)).total_seconds() < ECART_MIN:
        return "derniere publication il y a %d min (moins de 3 h)" % ((quand - max(heures)).total_seconds() // 60)
    return None


def candidats(pages, reg, images_requises=True):
    import visuels_reseaux as vr
    deja = set(r["cle"] for r in reg)
    publies = [(r["cle"], r["texte"]) for r in reg]
    table = rot.lire_categories()
    out = []
    for p in pages:
        if p["cle"] in deja or p["cle"] in EXCLUES:
            continue
        p = dict(p, categorie=rot.categorie(p["cle"], table=table))
        c = corps(p)
        if not c or trop_proche(c, publies):
            continue
        if images_requises and len(vr.images_instagram(p)) < 3:
            continue
        out.append(p)
    return out


def choisir(pages, reg, quand, combien, images_requises=True):
    cands = candidats(pages, reg, images_requises)
    hist = [(r["date"], r["categorie"], r["commerciale"]) for r in reg]
    pris = rot.choisir_pages(cands, hist, quand.strftime("%Y-%m-%d"), combien,
                             commerciale=lambda p: p["categorie"] == rot.COMMERCIALE or p["amazon"])
    fin = reg[-1]["fin"] if reg else None
    ia = reg[-1]["ia"] if reg else None
    aff = next((r["aff"] for r in reversed(reg) if r["aff"]), None)
    out = []
    for k, p in enumerate(pris):
        fin, ia = rot.choisir_variante(FINS, fin), rot.choisir_variante(MENTIONS_IA, ia)
        a = None
        if p["amazon"]:
            aff = a = rot.choisir_variante(MENTIONS_AFF, aff)
        t = composer(p, fin, ia, a or MENTIONS_AFF[0], dieses(p, len(reg) + k))
        if t:
            out.append(dict(p, texte=t, fin=fin, ia=ia, aff=a or ""))
    return out, len(cands)


def simuler(pages, jours_debut=PALIER_JOURS, jours_ensuite=7):
    reg, violations = [], []
    debut = datetime(2026, 11, 2, 8, 50, tzinfo=timezone.utc)
    for j in range(jours_debut + jours_ensuite):
        for k in range(3):
            quand = debut + timedelta(days=j, hours=5 * k)
            if garde(reg, quand, None):
                continue
            choix, _ = choisir(pages, reg, quand, 1, images_requises=False)
            if not choix:
                print("%s : aucune page possible" % quand.strftime("%Y-%m-%d %H:%M"))
                continue
            p = choix[0]
            reg.append({"cle": p["cle"], "id": "-", "date": quand.strftime("%Y-%m-%d"), "texte": p["texte"], "heure": quand,
                        "categorie": p["categorie"], "fin": p["fin"], "ia": p["ia"], "aff": p["aff"],
                        "commerciale": p["categorie"] == rot.COMMERCIALE or p["amazon"], "amazon": p["amazon"]})
        jour = (debut + timedelta(days=j)).strftime("%Y-%m-%d")
        du_jour = [r for r in reg if r["date"] == jour]
        attendu = PLAFOND_DEBUT if j < jours_debut else PLAFOND_ENSUITE
        print("%s (%d/%d) : %s" % (jour, len(du_jour), attendu, " | ".join(
            "%s%s" % (r["categorie"], " [aff]" if r["aff"] else "") for r in du_jour)))
        if len(du_jour) > attendu:
            violations.append("%s : %d publications pour un plafond de %d" % (jour, len(du_jour), attendu))
        if len(set(r["categorie"] for r in du_jour)) != len(du_jour):
            violations.append("%s : categorie repetee dans la journee" % jour)
        if sum(1 for r in du_jour if r["commerciale"]) > 1:
            violations.append("%s : plus d'une page commerciale" % jour)
    for a, b in zip(reg, reg[1:]):
        if a["categorie"] == b["categorie"]:
            violations.append("%s puis %s : meme categorie de suite" % (a["cle"], b["cle"]))
        for champ in ("fin", "ia"):
            if a[champ] == b[champ]:
                violations.append("%s puis %s : meme %s" % (a["cle"], b["cle"], champ))
        if (b["heure"] - a["heure"]).total_seconds() < ECART_MIN:
            violations.append("%s puis %s : moins de 3 h" % (a["cle"], b["cle"]))
        if re.findall(r"#\w+", a["texte"]) == re.findall(r"#\w+", b["texte"]):
            violations.append("%s puis %s : memes mots-dieses" % (a["cle"], b["cle"]))
    affs = [r["aff"] for r in reg if r["aff"]]
    if any(x == y for x, y in zip(affs, affs[1:])):
        violations.append("meme mention d'affiliation deux fois de suite")
    for r in reg:
        n = len(re.findall(r"#\w+", r["texte"]))
        if not 3 <= n <= 5:
            violations.append("%s : %d mots-dieses" % (r["cle"], n))
        if INTERDIT.search(r["texte"]) or r["ia"] not in r["texte"] or (r["amazon"] and not r["aff"]):
            violations.append("%s : mention manquante ou « nothing to buy »" % r["cle"])
        if len(r["texte"]) > MAX_CHARS or "link in bio" not in r["texte"]:
            violations.append("%s : legende trop longue ou sans « link in bio »" % r["cle"])
    print("Simulation : %d publications sur %d jours, %d mentions d'affiliation ; violations : %d"
          % (len(reg), jours_debut + jours_ensuite, len(affs), len(violations)))
    for v in violations:
        print("  VIOLATION " + v)
    if reg:
        print("\nExemple de legende (%s) :\n%s" % (reg[0]["cle"], reg[0]["texte"]))
    return 1 if violations else 0


def stocker(pages, reg):
    """Images des 2 prochaines pages de chaque categorie ; retire celles des pages publiees depuis plus de 3 jours."""
    import visuels_reseaux as vr
    faites = 0
    par_cat = {}
    for p in candidats(pages, reg, images_requises=False):
        if par_cat.get(p["categorie"], 0) >= STOCK_PAR_CATEGORIE:
            continue
        par_cat[p["categorie"]] = par_cat.get(p["categorie"], 0) + 1
        if len(vr.images_instagram(p)) < 3 and vr.ecrire_instagram(p):
            faites += 1
    borne = (maintenant() - timedelta(days=GARDER_JOURS)).strftime("%Y-%m-%d")
    retirees = 0
    for r in reg:
        if r["date"] < borne:
            for chemin in vr.images_instagram({"cle": r["cle"]}):
                os.remove(chemin)
                retirees += 1
    print("Stock : %d page(s) fabriquee(s) ; %d image(s) retiree(s) ; categories couvertes : %s"
          % (faites, retirees, ", ".join("%s %d" % kv for kv in sorted(par_cat.items()))))


def params_carrousel(texte, enfants, jeton):
    # is_ai_generated : declaration d'usage de l'IA, a poser sur le SEUL conteneur du carrousel (jamais sur les enfants :
    # erreur d'apres la documentation developers.facebook.com/documentation/instagram-platform/content-publishing)
    return {"media_type": "CAROUSEL", "children": ",".join(enfants), "caption": texte,
            "is_ai_generated": "true", "access_token": jeton}


def appel(methode, chemin, params):
    donnees = urllib.parse.urlencode(params).encode()
    url = chemin if chemin.startswith("https://") else API + chemin
    if methode == "GET":
        url, donnees = url + "?" + donnees.decode(), None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=donnees, method=methode), timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s sur %s : %s" % (e.code, chemin.split("?")[0], e.read()[:400].decode("utf-8", "replace")))
    except Exception as e:
        raise RuntimeError("reseau sur %s : %s" % (chemin, e))


def servie(url):
    try:
        # Cloudflare refuse l'agent par defaut « Python-urllib » (403, mesure le 29/10/2026) ; Meta, lui, passe.
        ua = {"User-Agent": "Mozilla/5.0 (compatible; RollerSkateAestheticBot/1.0; +https://rollerskateaesthetic.com/)"}
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers=ua), timeout=30) as r:
            return r.status == 200 and r.headers.get("Content-Type", "").startswith("image/jpeg")
    except Exception:
        return False


def attendre_conteneur(cid, jeton, essais=12):
    for _ in range(essais):
        s = appel("GET", "/" + cid, {"fields": "status_code", "access_token": jeton}).get("status_code")
        if s == "FINISHED":
            return
        if s in ("ERROR", "EXPIRED"):
            raise RuntimeError("conteneur %s en %s" % (cid, s))
        time.sleep(5)
    raise RuntimeError("conteneur %s pas pret apres %d s" % (cid, essais * 5))


def rafraichir(fichier):
    jeton = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not jeton:
        sys.exit("ERREUR: INSTAGRAM_ACCESS_TOKEN absent")
    r = appel("GET", "https://graph.instagram.com/refresh_access_token", {"grant_type": "ig_refresh_token", "access_token": jeton})
    neuf, duree = r.get("access_token"), int(r.get("expires_in") or 0)
    if not neuf:
        sys.exit("ERREUR: reponse de renouvellement sans jeton")
    with open(fichier, "w", encoding="utf-8") as f:
        f.write(neuf)
    fin = datetime.fromtimestamp(time.time() + duree, timezone.utc).strftime("%Y-%m-%d")
    with open(EXPIRE, "w", encoding="utf-8") as f:
        f.write("# jeton Instagram renouvele le %s UTC ; expire le %s (expires_in=%d s)\n%s\n"
                % (maintenant().strftime("%Y-%m-%d %H:%M"), fin, duree, fin))
    print("Jeton renouvele, expire le %s" % fin)


def lever_alerte(motif):
    pt.ajouter_ligne(ALERTE, "# Signal d'alerte Instagram : tant que ce fichier existe, 1 publication par jour au plus. "
                             "Supprimer le fichier leve l'alerte. Reporter la cause dans l'etat du projet.",
                     "%s\t%s" % (maintenant().strftime("%Y-%m-%d %H:%M:%S"), pt.propre(motif)[:400]))
    print("::warning::Signal d'alerte Instagram : %s -> plafond ramene a %d par jour" % (motif, PLAFOND_ALERTE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-posts", type=int, default=1)
    ap.add_argument("--attente-max", type=int, default=0)
    ap.add_argument("--simuler", action="store_true")
    ap.add_argument("--stocker", action="store_true")
    ap.add_argument("--rafraichir-jeton", metavar="FICHIER")
    a = ap.parse_args()
    if a.rafraichir_jeton:
        return rafraichir(a.rafraichir_jeton)
    if a.simuler:
        return simuler(pt.lire_pages())
    reg = lire_registre()
    if a.stocker:
        return stocker(pt.lire_pages(), reg)
    if a.max_posts > PLAFOND:
        sys.exit("ERREUR: --max-posts %d refuse, plafond %d par passage" % (a.max_posts, PLAFOND))
    alerte = (pt.lire_lignes(ALERTE) or [None])[-1]
    if alerte:
        print("Signal d'alerte actif : %s" % alerte)
    etat_susp, e_susp = su.etat_de(SUSP)
    if etat_susp != "libre":
        print("Suspension : %s" % su.phrase(etat_susp, e_susp))
    if etat_susp == "suspendu" and not a.dry_run:
        print("::warning::Chaine Instagram SUSPENDUE (refus de type blocage) : aucun appel a Meta. %s" % su.phrase(etat_susp, e_susp))
        return
    if a.attente_max > 0 and not a.dry_run:
        pause = random.randint(0, a.attente_max)
        print("Attente au hasard avant publication : %d s" % pause)
        time.sleep(pause)
    quand = maintenant()
    refus = garde(reg, quand, alerte)
    if refus and not a.dry_run:
        print("GARDE : passage refuse, %s. Rien n'est publie." % refus)
        return
    pages = pt.lire_pages()
    a_faire, nb = choisir(pages, reg, quand, a.max_posts)
    print("Pages : %d ; publiables avec images : %d ; registre : %d ; plafond du jour : %d ; a publier : %d%s"
          % (len(pages), nb, len(reg), plafond_du_jour(reg, quand, alerte), len(a_faire),
             " (garde : %s)" % refus if refus else ""))
    if a.dry_run:
        import visuels_reseaux as vr
        for p in a_faire:
            print("---- %s [%s] (%d car.) images : %s ----\n%s\n" % (p["cle"], p["categorie"], len(p["texte"]),
                                                                    " ".join(vr.images_instagram(p)), p["texte"]))
            req = params_carrousel(p["texte"], ["<id_enfant_%d>" % (i + 1) for i in range(len(vr.images_instagram(p)))], "<jeton>")
            print("Requete du conteneur carrousel (a blanc, aucun appel) : POST /<id>/media %s\n"
                  % {k: (v if k != "caption" else "<legende>") for k, v in req.items()})
        return
    if not a_faire:
        print("Rien a publier.")
        return
    jeton = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not jeton:
        sys.exit("ERREUR: INSTAGRAM_ACCESS_TOKEN absent de l'environnement")
    essai = etat_susp == "essai"
    if essai:
        su.prendre_essai(SUSP)
        print("::warning::Essai UNIQUE apres suspension : %s" % su.phrase(etat_susp, e_susp))
    uid = os.environ.get("INSTAGRAM_USER_ID", "").strip() or appel("GET", "/me", {"fields": "user_id", "access_token": jeton})["user_id"]
    import visuels_reseaux as vr
    echecs = 0
    for p in a_faire:
        urls = [SITE + "/" + c for c in vr.images_instagram(p)][:10]
        absentes = [u for u in urls if not servie(u)]
        if absentes:
            print("SKIP %s : image(s) pas encore en ligne : %s" % (p["cle"], " ".join(absentes)))
            continue
        try:
            enfants = []
            for u in urls:
                enfants.append(appel("POST", "/%s/media" % uid, {"image_url": u, "is_carousel_item": "true",
                                                                 "access_token": jeton})["id"])
            for e in enfants:
                attendre_conteneur(e, jeton)
            cid = appel("POST", "/%s/media" % uid, params_carrousel(p["texte"], enfants, jeton))["id"]
            attendre_conteneur(cid, jeton)
            media = appel("POST", "/%s/media_publish" % uid, {"creation_id": cid, "access_token": jeton})["id"]
        except (RuntimeError, KeyError) as e:
            echecs += 1
            print("ECHEC %s : %s" % (p["cle"], e), file=sys.stderr)
            note_echec(p["cle"], str(e))
            if str(e).startswith("HTTP 4") or ALERTE_MOTS.search(str(e)):
                lever_alerte("refus de l'API a la publication de %s : %s" % (p["cle"], pt.propre(str(e))[:250]))
            motif_b = su.blocage(str(e))
            if motif_b:
                s = su.poser(SUSP, "instagram", "%s : %s" % (p["cle"], motif_b))
                print("::error::BLOCAGE Instagram, chaine suspendue (refus n°%d), prochain essai %s : %s"
                      % (s["refus"], s["prochain_essai"], motif_b))
                break
            continue
        if essai:
            su.lever(SUSP, "essai reussi : %s publie (%s)" % (p["cle"], media))
            essai = False
        t = maintenant()
        pt.ajouter_ligne(REG, "# cle\tid_instagram\tdate_utc\ttexte\thorodatage_utc\tcategorie\tfin\tmention_ia\tmention_aff\timages",
                         "\t".join([p["cle"], media, t.strftime("%Y-%m-%d"), p["texte"].replace("\n", "\\n"),
                                    t.strftime("%Y-%m-%d %H:%M:%S"), p["categorie"], p["fin"], p["ia"], p["aff"],
                                    str(len(urls))]))
        try:
            lien = appel("GET", "/" + media, {"fields": "permalink", "access_token": jeton}).get("permalink", "?")
        except RuntimeError as e:
            lien = "lien illisible (%s)" % e
        print("POSTED %s [%s] %d images -> %s %s" % (p["cle"], p["categorie"], len(urls), media, lien))
    if echecs:
        sys.exit("%d publication(s) refusee(s), detail dans %s" % (echecs, ECHECS))


if __name__ == "__main__":
    sys.exit(main())
