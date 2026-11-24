#!/usr/bin/env python3
"""Publie sur YouTube, par l'API officielle YouTube Data v3 (videos.insert), une courte video verticale par page du
site. Stdlib seule pour l'envoi ; Pillow et ffmpeg pour la video (visuels_reseaux.py).

Ecrit le 29/10/2026 (prompt un document interne du projet). Aucun modele dans la chaine.

VIDEO : 1080 x 1920, 20 a 40 s, SANS SON (aucune musique, donc aucune licence a tenir) : l'epingle de la page, puis
2 ou 3 phrases de son paragraphe d'ouverture en surimpression, puis une diapo de fin vers le site.
TITRE : le titre de la page (100 caracteres au plus). DESCRIPTION : une ou deux phrases du paragraphe d'ouverture, le
lien complet de la page (precede d'une formule qui tourne, FINS), puis la mention d'IA et, si la page porte un lien
Amazon, la mention d'affiliation, qui tournent comme sur Threads. Jamais « nothing to buy ».
DECLARATION DE CONTENU SYNTHETIQUE : status.containsSyntheticMedia = false. Regle lue le 29/10/2026
(support.google.com/youtube/answer/14328491) : « Creators don't need to disclose non-realistic content that's made
with AI » ; ces videos sont des illustrations et du texte, rien qui paraisse reel.

RYTHME (garde()) : 0 par jour tant que _releves/youtube_ouvert.txt n'existe pas (prompt du 29/10 : rien en serie
avant l'audit ; voir un document interne, entree youtube, sur ce que dit la page de l'API depuis le 15/10/2026).
Ensuite 1 par jour pendant 14 jours a compter de la premiere video publique, puis 2 ; 1 si un signal d'alerte est
actif (_releves/alerte_youtube.txt) ; jamais moins de 4 heures apres la precedente. Rotation des categories :
rotation_publications.choisir_pages (une seule page commerciale par jour).
REGISTRE : _releves/publies_youtube.tsv, une page inscrite n'est JAMAIS republiee. La video d'essai privee va dans
_releves/essai_youtube.tsv, pas au registre : sa page reste disponible pour une vraie publication.
Aucune modification, aucune suppression, aucune interaction avec d'autres chaines.

Variables : YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN (portee youtube.upload + youtube.readonly).
  --essai-prive : fabrique et envoie UNE video en prive (preuve que la chaine marche), quel que soit le plafond.
  --fabriquer N DOSSIER : fabrique les N prochaines videos dans l'ordre de rotation, sans rien envoyer.
  --releve : chiffres de la chaine et des videos -> _releves/releve_youtube.csv (une fois par jour).
  --simuler : essai a blanc de 14 jours a 1 puis 7 jours a 2.
"""
import argparse, json, os, random, re, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

import publier_threads as pt
import rotation_publications as rot
from controle_fins_flux import INTERDIT
import suspension as su

REG = "_releves/publies_youtube.tsv"
ESSAI = "_releves/essai_youtube.tsv"
ECHECS = "_releves/echecs_youtube.tsv"
ALERTE = "_releves/alerte_youtube.txt"
# 10/11/2026 (chef, poste reseaux) : un refus de type BLOCAGE suspend la chaine (suspension.py) ; plus aucun appel
# avant le prochain essai ; un seul essai ; succes = levee. Origine : Instagram bloque par Meta (4/2207051) du 08/11.
SUSP = "_releves/suspension_youtube.json"
OUVERT = "_releves/youtube_ouvert.txt"
JOUR = "_releves/releve_youtube.csv"
FINS = ["Full page:", "Read the whole tip:", "The complete page, free:", "More on this in the guide:"]
MENTIONS_IA, MENTIONS_AFF = pt.MENTIONS_IA, pt.MENTIONS_AFF
PALIER_JOURS, PLAFOND_DEBUT, PLAFOND_ENSUITE, PLAFOND_ALERTE = 14, 1, 2, 1
ECART_MIN = 4 * 3600
PLAFOND = 1
TITRE_MAX, DESC_MAX = 100, 5000
CATEGORIE_YT = "26"   # Howto & Style
ALERTE_MOTS = pt.ALERTE_MOTS


def maintenant():
    return datetime.now(timezone.utc)


def note_echec(cle, motif):
    pt.ajouter_ligne(ECHECS, "# horodatage_utc\tcle\tmotif",
                     "%s\t%s\t%s" % (maintenant().strftime("%Y-%m-%d %H:%M:%S"), cle, pt.propre(motif)[:400]))


def composer(page, fin, ia, aff):
    import visuels_reseaux as vr
    i = pt.idee(page, 600)
    titre = vr.titre(page)
    if not i or len(titre) > TITRE_MAX or re.search(r"[<>]", titre):
        return None
    d = i + "\n\n" + fin + " " + pt.avec_src(page["url"], "youtube") + "\n\n" + ia
    if page["amazon"]:
        d += " " + aff
    if len(d) > DESC_MAX or INTERDIT.search(d + titre):
        return None
    return titre, d


def lire_registre(chemin=REG):
    """Colonnes : cle, id, date, titre, horodatage UTC, categorie, fin, mention IA, mention affiliation, statut, duree."""
    out = []
    for l in pt.lire_lignes(chemin):
        c = l.split("\t")
        if len(c) < 10:
            continue
        try:
            h = datetime.strptime(c[4], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            h = None
        out.append({"cle": c[0], "id": c[1], "date": c[2], "titre": c[3], "heure": h, "categorie": c[5], "fin": c[6],
                    "ia": c[7], "aff": c[8], "statut": c[9], "commerciale": c[5] == rot.COMMERCIALE or bool(c[8])})
    return out


def plafond_du_jour(reg, quand, alerte, ouvert):
    if not ouvert:
        return 0
    if alerte:
        return PLAFOND_ALERTE
    pub = [r for r in reg if r["statut"] == "public"]
    if not pub:
        return PLAFOND_DEBUT
    debut = datetime.strptime(pub[0]["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    jour = quand.replace(hour=0, minute=0, second=0, microsecond=0)
    return PLAFOND_DEBUT if (jour - debut).days < PALIER_JOURS else PLAFOND_ENSUITE


def garde(reg, quand, alerte, ouvert):
    plafond = plafond_du_jour(reg, quand, alerte, ouvert)
    if plafond == 0:
        return "chaine fermee (%s absent) : 0 video par jour" % OUVERT
    faites = sum(1 for r in reg if r["date"] == quand.strftime("%Y-%m-%d"))
    if faites >= plafond:
        return "plafond du jour atteint (%d/%d%s)" % (faites, plafond, ", signal d'alerte : %s" % alerte if alerte else "")
    heures = [r["heure"] for r in reg if r["heure"]]
    if heures and (quand - max(heures)).total_seconds() < ECART_MIN:
        return "derniere video il y a %d min (moins de 4 h)" % ((quand - max(heures)).total_seconds() // 60)
    return None


def choisir(pages, reg, quand, combien, exclure=()):
    import visuels_reseaux as vr
    deja = set(r["cle"] for r in reg) | set(exclure)
    publies = [(r["cle"], r["titre"]) for r in reg]
    table = rot.lire_categories()
    cands = []
    for p in pages:
        if p["cle"] in deja or len(vr.etapes(p)) < 2 or not vr.epingle(p):
            continue
        p = dict(p, categorie=rot.categorie(p["cle"], table=table))
        if not composer(p, FINS[0], MENTIONS_IA[0], MENTIONS_AFF[0]):
            continue
        cands.append(p)
    hist = [(r["date"], r["categorie"], r["commerciale"]) for r in reg]
    pris = rot.choisir_pages(cands, hist, quand.strftime("%Y-%m-%d"), combien,
                             commerciale=lambda p: p["categorie"] == rot.COMMERCIALE or p["amazon"])
    fin = reg[-1]["fin"] if reg else None
    ia = reg[-1]["ia"] if reg else None
    aff = next((r["aff"] for r in reversed(reg) if r["aff"]), None)
    out = []
    for p in pris:
        fin, ia = rot.choisir_variante(FINS, fin), rot.choisir_variante(MENTIONS_IA, ia)
        a = None
        if p["amazon"]:
            aff = a = rot.choisir_variante(MENTIONS_AFF, aff)
        titre, desc = composer(p, fin, ia, a or MENTIONS_AFF[0])
        out.append(dict(p, titre=titre, description=desc, fin=fin, ia=ia, aff=a or ""))
    return out, len(cands)


def simuler(pages, jours_debut=PALIER_JOURS, jours_ensuite=7):
    reg, violations = [], []
    debut = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)
    if garde([], debut, None, False) is None:
        violations.append("chaine fermee qui laisse passer")
    for j in range(jours_debut + jours_ensuite):
        for k in range(3):
            quand = debut + timedelta(days=j, hours=5 * k)
            if garde(reg, quand, None, True):
                continue
            choix, _ = choisir(pages, reg, quand, 1)
            if not choix:
                print("%s : aucune page possible" % quand.strftime("%Y-%m-%d %H:%M"))
                continue
            p = choix[0]
            reg.append({"cle": p["cle"], "id": "-", "date": quand.strftime("%Y-%m-%d"), "titre": p["titre"],
                        "heure": quand, "categorie": p["categorie"], "fin": p["fin"], "ia": p["ia"], "aff": p["aff"],
                        "statut": "public", "commerciale": p["categorie"] == rot.COMMERCIALE or p["amazon"],
                        "amazon": p["amazon"], "description": p["description"]})
        jour = (debut + timedelta(days=j)).strftime("%Y-%m-%d")
        du_jour = [r for r in reg if r["date"] == jour]
        attendu = PLAFOND_DEBUT if j < jours_debut else PLAFOND_ENSUITE
        print("%s (%d/%d) : %s" % (jour, len(du_jour), attendu, " | ".join(r["categorie"] for r in du_jour)))
        if len(du_jour) > attendu:
            violations.append("%s : %d videos pour un plafond de %d" % (jour, len(du_jour), attendu))
        if sum(1 for r in du_jour if r["commerciale"]) > 1:
            violations.append("%s : plus d'une page commerciale" % jour)
    for a, b in zip(reg, reg[1:]):
        if a["categorie"] == b["categorie"]:
            violations.append("%s puis %s : meme categorie de suite" % (a["cle"], b["cle"]))
        if a["fin"] == b["fin"] or a["ia"] == b["ia"]:
            violations.append("%s puis %s : meme fin ou meme mention d'IA" % (a["cle"], b["cle"]))
    for r in reg:
        if INTERDIT.search(r["description"]) or r["ia"] not in r["description"] or (r["amazon"] and not r["aff"]):
            violations.append("%s : mention manquante ou « nothing to buy »" % r["cle"])
    if len(set(r["titre"] for r in reg)) != len(reg):
        violations.append("titre en double")
    print("Simulation : %d videos sur %d jours ; violations : %d" % (len(reg), jours_debut + jours_ensuite, len(violations)))
    for v in violations:
        print("  VIOLATION " + v)
    if reg:
        print("\nExemple (%s) :\nTITRE %s\n%s" % (reg[0]["cle"], reg[0]["titre"], reg[0]["description"]))
    return 1 if violations else 0


def http(methode, url, corps=None, entetes=None):
    req = urllib.request.Request(url, data=corps, method=methode, headers=entetes or {})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s sur %s : %s" % (e.code, url.split("?")[0], e.read()[:400].decode("utf-8", "replace")))
    except Exception as e:
        raise RuntimeError("reseau sur %s : %s" % (url.split("?")[0], e))


def jeton():
    v = dict((k, os.environ.get(k, "").strip()) for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"))
    manque = [k for k, x in v.items() if not x]
    if manque:
        sys.exit("ERREUR: %s absent(s) de l'environnement" % ", ".join(manque))
    r = http("POST", "https://oauth2.googleapis.com/token", urllib.parse.urlencode({
        "client_id": v["YOUTUBE_CLIENT_ID"], "client_secret": v["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": v["YOUTUBE_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"})
    if "access_token" not in r:
        sys.exit("ERREUR: jeton YouTube refuse : %s" % r)
    return r["access_token"]


def envoyer(acces, chemin_video, p, statut):
    meta = {"snippet": {"title": p["titre"], "description": p["description"], "categoryId": CATEGORIE_YT,
                        "defaultLanguage": "en", "defaultAudioLanguage": "en"},
                        # 07/11/2026 (correctif 5 de la remontee du 02/11) : plus de cle "tags" (socle § 3.2 et § 5).
            "status": {"privacyStatus": statut, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False,
                       "embeddable": True, "license": "youtube"}}
    borne = "----rsa%d" % random.randint(10 ** 8, 10 ** 9)
    corps = ("--%s\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n%s\r\n--%s\r\nContent-Type: video/mp4\r\n\r\n"
             % (borne, json.dumps(meta), borne)).encode() + open(chemin_video, "rb").read() + ("\r\n--%s--\r\n" % borne).encode()
    r = http("POST", "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status",
             corps, {"Authorization": "Bearer " + acces, "Content-Type": "multipart/related; boundary=" + borne})
    return r["id"], r.get("status", {}).get("privacyStatus", "?"), r.get("status", {}).get("uploadStatus", "?")


def inscrire(chemin, p, vid, statut, duree):
    t = maintenant()
    pt.ajouter_ligne(chemin, "# cle\tid_youtube\tdate_utc\ttitre\thorodatage_utc\tcategorie\tfin\tmention_ia\tmention_aff\tstatut\tduree_s",
                     "\t".join([p["cle"], vid, t.strftime("%Y-%m-%d"), pt.propre(p["titre"]), t.strftime("%Y-%m-%d %H:%M:%S"),
                                p["categorie"], p["fin"], p["ia"], p["aff"], statut, str(duree)]))


def releve():
    from releve_threads import heure_paris, ENTETE
    p = heure_paris(maintenant())
    date, heure = p.strftime("%Y-%m-%d"), p.strftime("%H:%M")
    if os.path.exists(JOUR) and any(l.startswith(date + ";") for l in open(JOUR, encoding="utf-8")):
        print("Releve du %s deja ecrit." % date)
        return
    h = {"Authorization": "Bearer " + jeton()}
    c = http("GET", "https://www.googleapis.com/youtube/v3/channels?part=statistics&mine=true", None, h)["items"][0]["statistics"]
    ids = [r["id"] for r in lire_registre() + lire_registre(ESSAI)][-50:]
    notes = 0
    if ids:
        for v in http("GET", "https://www.googleapis.com/youtube/v3/videos?part=statistics&id=" + ",".join(ids), None, h).get("items", []):
            s = v["statistics"]
            notes += int(s.get("likeCount", 0)) + int(s.get("commentCount", 0))
    ligne = [date, heure, "youtube", c.get("videoCount", ""), c.get("subscriberCount", ""), str(notes), c.get("viewCount", ""),
             "", "", "YouTube Data API v3 channels.statistics (videoCount, subscriberCount, viewCount) + videos.statistics (j'aime+commentaires)", ""]
    neuf = not os.path.exists(JOUR)
    with open(JOUR, "a", encoding="utf-8") as f:
        if neuf:
            f.write(ENTETE + "\n")
        f.write(";".join(ligne) + "\n")
    print(";".join(ligne))


def main():
    import visuels_reseaux as vr
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-posts", type=int, default=1)
    ap.add_argument("--attente-max", type=int, default=0)
    ap.add_argument("--simuler", action="store_true")
    ap.add_argument("--essai-prive", action="store_true")
    ap.add_argument("--releve", action="store_true")
    ap.add_argument("--fabriquer", nargs=2, metavar=("N", "DOSSIER"))
    a = ap.parse_args()
    if a.simuler:
        return simuler(pt.lire_pages())
    if a.releve:
        return releve()
    reg = lire_registre()
    if a.fabriquer:
        n, dossier = int(a.fabriquer[0]), a.fabriquer[1]
        os.makedirs(dossier, exist_ok=True)
        faux, quand = list(reg), maintenant()
        lignes = []
        for k in range(n):
            choix, _ = choisir(pt.lire_pages(), faux, quand + timedelta(days=k), 1)
            if not choix:
                break
            p = choix[0]
            sortie = os.path.join(dossier, "%02d_%s.mp4" % (k + 1, vr.slug(p["cle"])))
            d = vr.video(p, sortie)
            faux.append({"cle": p["cle"], "id": "-", "date": (quand + timedelta(days=k)).strftime("%Y-%m-%d"), "titre": p["titre"],
                         "heure": None, "categorie": p["categorie"], "fin": p["fin"], "ia": p["ia"], "aff": p["aff"],
                         "statut": "-", "commerciale": p["categorie"] == rot.COMMERCIALE or p["amazon"]})
            lignes.append("%02d\t%s\t%s\t%s s\t%s\n%s" % (k + 1, p["cle"], p["categorie"], d, p["titre"], p["description"]))
            print("%s (%s s)" % (sortie, d))
        with open(os.path.join(dossier, "LISTE.txt"), "w", encoding="utf-8") as f:
            f.write("Videos fabriquees le %s par publier_youtube.py --fabriquer, dans l'ordre de rotation. Sans son : "
                    "aucune musique, aucune licence.\n\n%s\n" % (quand.strftime("%Y-%m-%d %H:%M UTC"), "\n\n".join(lignes)))
        return 0
    if a.max_posts > PLAFOND:
        sys.exit("ERREUR: --max-posts %d refuse, plafond %d par passage" % (a.max_posts, PLAFOND))
    ouvert = os.path.exists(OUVERT)
    alerte = (pt.lire_lignes(ALERTE) or [None])[-1]
    quand = maintenant()
    if a.essai_prive:
        if pt.lire_lignes(ESSAI):
            sys.exit("ERREUR: une video d'essai existe deja (%s) ; pas de seconde" % ESSAI)
        refus = None
    else:
        refus = garde(reg, quand, alerte, ouvert)
        if refus and not a.dry_run:
            print("GARDE : passage refuse, %s. Rien n'est envoye." % refus)
            return
    etat_susp, e_susp = su.etat_de(SUSP)
    if etat_susp != "libre":
        print("Suspension : %s" % su.phrase(etat_susp, e_susp))
    if etat_susp == "suspendu" and not a.dry_run:
        print("::warning::Chaine YouTube SUSPENDUE (refus de type blocage) : aucun appel a Google. %s" % su.phrase(etat_susp, e_susp))
        return
    a_faire, nb = choisir(pt.lire_pages(), reg, quand, 1)
    print("Pages candidates : %d ; registre : %d ; plafond du jour : %d ; a envoyer : %d%s"
          % (nb, len(reg), plafond_du_jour(reg, quand, alerte, ouvert), len(a_faire), " (garde : %s)" % refus if refus else ""))
    if not a_faire:
        print("Rien a envoyer.")
        return
    p = a_faire[0]
    if a.dry_run:
        print("---- %s [%s] ----\nTITRE %s\n%s" % (p["cle"], p["categorie"], p["titre"], p["description"]))
        return
    if a.attente_max > 0 and not a.essai_prive:
        pause = random.randint(0, a.attente_max)
        print("Attente au hasard avant envoi : %d s" % pause)
        time.sleep(pause)
    sortie = os.path.join(tempfile.mkdtemp(), vr.slug(p["cle"]) + ".mp4")
    duree = vr.video(p, sortie)
    statut = "private" if a.essai_prive else "public"
    essai = etat_susp == "essai"
    if essai:
        su.prendre_essai(SUSP)
        print("::warning::Essai UNIQUE apres suspension : %s" % su.phrase(etat_susp, e_susp))
    try:
        vid, statut_lu, envoi = envoyer(jeton(), sortie, p, statut)
    except RuntimeError as e:
        print("ECHEC %s : %s" % (p["cle"], e), file=sys.stderr)
        note_echec(p["cle"], str(e))
        if str(e).startswith("HTTP 4") or ALERTE_MOTS.search(str(e)):
            pt.ajouter_ligne(ALERTE, "# Signal d'alerte YouTube : tant que ce fichier existe, 1 video par jour au plus. "
                                     "Supprimer le fichier leve l'alerte.",
                             "%s\t%s" % (maintenant().strftime("%Y-%m-%d %H:%M:%S"), pt.propre(str(e))[:400]))
        motif_b = su.blocage(str(e))
        if motif_b:
            s = su.poser(SUSP, "youtube", "%s : %s" % (p["cle"], motif_b))
            print("::error::BLOCAGE YouTube, chaine suspendue (refus n°%d), prochain essai %s : %s"
                  % (s["refus"], s["prochain_essai"], motif_b))
        sys.exit(1)
    if essai:
        su.lever(SUSP, "essai reussi : %s envoye (%s)" % (p["cle"], vid))
    inscrire(ESSAI if a.essai_prive else REG, p, vid, statut_lu, duree)
    print("POSTED %s [%s] %s s -> https://www.youtube.com/watch?v=%s (statut %s, envoi %s)"
          % (p["cle"], p["categorie"], duree, vid, statut_lu, envoi))


if __name__ == "__main__":
    sys.exit(main())
