#!/usr/bin/env python3
"""Publie sur Bluesky les epingles de feed.xml ET de feed_archive.xml. Stdlib seule.

REGLE DE SELECTION (deterministe, une seule source de verite = le registre)
- Candidats = pins de feed_archive.xml UNION pins de feed.xml (meme cle "pin-N" ; en cas de doublon, l'item de feed.xml l'emporte).
- Un pin dont la cle est au registre (_releves/publies_bluesky.tsv) n'est JAMAIS republie.
- NOUVEAUX = pins de feed.xml, hors registre, absents de la liste gelee _releves/arriere_bluesky.txt (fixee au premier passage).
  Ils partent en premier, du plus ancien au plus recent (date puis numero).
- ARRIERE = tout autre candidat hors registre (archive + pins gelees). Ils partent ensuite, PLUS ANCIEN D'ABORD
  (numero de pin croissant), au plus --backlog-per-run (defaut 5) par passage.
- Plafond dur --max-posts (defaut 9) pour l'ensemble. Le plafond s'applique apres avoir ecarte les pins impubliables
  (texte impossible a ecrire dans la limite) : ceux-ci sont journalises "SKIP" avec la raison et ne bloquent pas la file.

FINS QUI TOURNENT (29/10/2026, un document interne) : les 170 premieres
publications finissaient toutes par la meme phrase ; Meta et Pinterest comptent le contenu repetitif parmi les
signaux de spam. La fin est maintenant tiree de ENDINGS (jamais la meme deux fois de suite), suivie, si la page
porte un lien Amazon, d'une mention d'affiliation tiree de MENTIONS_AFF (meme regle). Regle du propriétaire du 16/09/2026 :
la mention d'IA et la mention d'affiliation ne se retirent jamais. Le registre porte depuis ce jour trois colonnes
de plus : categorie, fin, mention d'affiliation (vide si aucune).
CATEGORIES (pages du site) : rotation_publications.choisir_pages, comme Threads -- jamais deux pages de la meme
categorie le meme jour ni deux de suite, une seule page commerciale par jour.
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

HOST = "https://bsky.social"
FEED = "feed.xml"
ARCHIVE = "feed_archive.xml"
REG = "_releves/publies_bluesky.tsv"
# 10/11/2026 (chef, poste reseaux) : un refus de type BLOCAGE suspend la chaine (suspension.py) ; plus aucun appel
# avant le prochain essai ; un seul essai ; succes = levee. Origine : Instagram bloque par Meta (4/2207051) du 08/11.
SUSP = "_releves/suspension_bluesky.json"
LAST = "_releves/derniere_publication_bluesky.txt"
ECHECS = "_releves/echecs_bluesky.tsv"   # une ligne par echec : le motif reste dans le depot, pas seulement sur stderr du runner
WEB = "https://bsky.app/profile/rolleraesthetic.bsky.social/post/"
ARR = "_releves/arriere_bluesky.txt"   # pins deja dans le flux au premier passage (l'arriere)
NETWORK = "bluesky"
ENDINGS = ["Free beginner's guide: rollerskateaesthetic.com · Written with AI from a skater's notes.",
           "More in the free guide at rollerskateaesthetic.com · Drafted with AI from a skater's notes.",
           "Full page: rollerskateaesthetic.com · AI-written from notes by a skater.",
           "Guide (free, no sign-up): rollerskateaesthetic.com · Made with AI from real skating notes."]
ENDING = ENDINGS[0]   # fin unique des 170 premieres publications (jusqu'au 28/10/2026)
MENTIONS_AFF = ["This page contains affiliate links.", "Some links on this page are affiliate links.",
                "The page includes affiliate links."]
# budget du corps : la plus longue fin + la plus longue mention + separateurs, pour que toute combinaison tienne
FIN_MAX = max(len(e) for e in ENDINGS) + 1 + max(len(m) for m in MENTIONS_AFF)
LINK_TEXT = "rollerskateaesthetic.com"
MAX_CHARS = 290
MAX_BLOB = 950 * 1024
BACKLOG_PER_RUN = 5
# 26/10/2026 : les 162 epingles sont toutes publiees (passage du 25/10 : « nouveaux: 0 ») et feed.xml est vide
# (pause Pinterest). Une fois les epingles epuisees, on prend les pages du sitemap qui n'ont jamais eu d'epingle,
# cle « page:<chemin> » au meme registre, au plus PAGES_PER_RUN par passage. Texte : l'idee de la page
# (publier_threads.idee, une ou deux phrases du paragraphe d'ouverture) puis ENDING.
PAGES_PER_RUN = 2
JUNK = re.compile(r"free beginner|free guide|no sign-up|sign-up|sign up|nothing to buy|written with ai|affiliate|\bAI\b|—\s*Cass|\bCass\.?$", re.I)
from controle_fins_flux import INTERDIT   # une seule regle « nothing to buy » pour tout le depot
from publier_threads import avec_src   # 07/11/2026 : ?src=<reseau> (correctif 6, N.8)
import rotation_publications as rot
import suspension as su
AMAZON = re.compile(r'href="https?://(?:www\.)?amazon\.')


LAST_ERR = [""]
UA = "Mozilla/5.0 (compatible; RollerAestheticBot/1.0; +https://rollerskateaesthetic.com/)"


def die(msg, code=2):
    LAST_ERR[0] = msg
    print("ERREUR: " + msg, file=sys.stderr)
    sys.exit(code)


def note_echec(key, motif):
    """Ajoute une ligne a ECHECS (horodatage UTC, cle, motif complet), append + fsync comme le registre."""
    os.makedirs("_releves", exist_ok=True)
    neuf = not os.path.exists(ECHECS)
    with open(ECHECS, "a", encoding="utf-8") as f:
        if neuf:
            f.write("# horodatage_utc\tcle\tmotif\n")
        f.write("%s\t%s\t%s\n" % (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), key,
                                  motif.replace("\t", " ").replace("\n", " ")))
        f.flush(); os.fsync(f.fileno())


def ecrire_last(posted, failures):
    with open(LAST, "w", encoding="utf-8") as f:
        f.write("# cle\turi\turl_web\tthumb (derniere execution, %s ; echecs: %d)\n"
                % (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), failures) + "\n".join(posted) + "\n")


def read_feed(path=FEED):
    try:
        root = ET.parse(path).getroot()
    except Exception as e:
        die("%s illisible: %s" % (path, e))
    pins = []
    for it in root.iter("item"):
        guid = (it.findtext("guid") or "").strip()
        link = (it.findtext("link") or "").strip()
        m = re.search(r"pin-(\d+)\s*$", guid) or re.search(r"pin[_-](\d+)", (it.find("enclosure").get("url") if it.find("enclosure") is not None else ""))
        if not m or not link:
            die("%s: item sans cle de pin ou sans lien: guid=%r" % (path, guid))
        enc = it.find("enclosure")
        try:
            d = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:
            d = datetime.fromtimestamp(0, timezone.utc)
        pins.append({"key": "pin-" + m.group(1), "n": int(m.group(1)), "title": (it.findtext("title") or "").strip(),
                     "desc": (it.findtext("description") or "").strip(), "link": link,
                     "image": enc.get("url") if enc is not None else None, "date": d})
    pins.sort(key=lambda p: (p["date"], p["n"]))
    keys = [p["key"] for p in pins]
    if len(set(keys)) != len(keys):
        die("cles de pin en double dans %s" % path)
    return pins


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def clean_sentences(desc):
    return [s for s in sentences(desc) if not JUNK.search(s)]


def shorten(sent, budget):
    if len(sent) <= budget:
        return sent
    best = None
    for m in re.finditer(r",\s|;\s|\s—\s|:\s", sent):
        cut = sent[:m.start()].rstrip(" ,;:—")
        if len(cut) + 1 <= budget and len(cut) >= 40:
            best = cut
    return (best + ".") if best else None


def title_sentence(title):
    t = title.strip()
    if not t:
        return ""
    t = t[0].upper() + t[1:]
    if t[-1] not in ".!?":
        t += "."
    return t


def make_body(p):
    """Le corps du texte (sans la fin), dans le budget de la plus longue fin possible."""
    if p.get("body"):
        return p["body"]
    budget = MAX_CHARS - FIN_MAX - 2
    ts = title_sentence(p["title"])
    if not ts:
        return None
    cs = clean_sentences(p["desc"])
    if cs and len(ts) + 1 + len(cs[0]) <= budget:
        return ts + " " + cs[0]
    if len(ts) <= budget:
        return ts
    return shorten(ts, budget)


def make_text(p, ending=ENDING, aff=None):
    body = make_body(p)
    if not body:
        return None
    return body + "\n\n" + ending + ((" " + aff) if aff else "")


def page_amazon(link):
    """La page de destination porte-t-elle un lien Amazon ? (fichier local du depot)"""
    m = re.match(r"https?://[^/]+/(.*)$", link or "")
    f = os.path.join(m.group(1).strip("/"), "index.html") if m else ""
    return bool(f) and os.path.isfile(f) and bool(AMAZON.search(open(f, encoding="utf-8").read()))


def card_desc(p):
    out = ""
    for s in clean_sentences(p["desc"]):
        if len(out) + len(s) + 1 > 280:
            break
        out = (out + " " + s).strip()
    return out or p["title"]


def facets(text):
    pre = text.rfind(LINK_TEXT)
    if pre < 0:
        die("lien absent du texte")
    bs = len(text[:pre].encode("utf-8"))
    return [{"index": {"byteStart": bs, "byteEnd": bs + len(LINK_TEXT.encode("utf-8"))},
             "features": [{"$type": "app.bsky.richtext.facet#link", "uri": "https://rollerskateaesthetic.com/?src=bluesky"}]}]


def page_candidates(reg, pins):
    """Pages sans epingle. Ecartees aussi : celles qui reprennent l'image d'une epingle, ou dont plus de la moitie
    des mots se retrouvent dans une epingle (meme contenu deja publie sous une autre adresse)."""
    import publier_threads as pt
    pin_links = set(p["link"] for p in pins)
    pin_images = set(os.path.basename(p["image"] or "") for p in pins) - {""}
    pin_texts = [(p["key"], p["title"] + " " + p["desc"]) for p in pins]
    out = []
    for pg in pt.lire_pages():
        key = "page:" + pg["cle"]
        if key in reg or pg["url"] in pin_links:
            continue
        i = pt.idee(pg, MAX_CHARS - FIN_MAX - 2)
        if not i:
            print("SKIP %s: aucune phrase complete dans la limite" % key, file=sys.stderr)
            continue
        src = open(os.path.join(pg["cle"], "index.html"), encoding="utf-8").read()
        og = re.search(r'property="og:image" content="([^"]+)"', src)
        if og and os.path.basename(og.group(1)) in pin_images:
            print("SKIP %s: image deja publiee avec une epingle (%s)" % (key, os.path.basename(og.group(1))), file=sys.stderr)
            continue
        proche = pt.trop_proche(i, pin_texts + [(x["key"], x["desc"]) for x in out])
        if proche:
            print("SKIP %s: %s" % (key, proche), file=sys.stderr)
            continue
        h1 = re.search(r"<h1>(.*?)</h1>", src, re.S)
        out.append({"key": key, "n": 0, "title": pt.texte_html(h1.group(1)) if h1 else pg["cle"], "desc": i,
                    "link": pg["url"], "image": og.group(1) if og else None, "date": pg["date"],
                    "body": i, "amazon": pg["amazon"], "categorie": rot.categorie(pg["cle"])})
    return out


def read_lines(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return [l.rstrip("\n") for l in f if l.strip() and not l.startswith("#")]


def http(method, url, body=None, headers=None, raw=None):
    h = dict(headers or {})
    h.setdefault("User-Agent", UA)
    data = raw
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read(), r.headers
    except urllib.error.HTTPError as e:
        die("HTTP %s sur %s: %s" % (e.code, url, e.read()[:300].decode("utf-8", "replace")), 3)
    except Exception as e:
        die("reseau %s: %s" % (url, e), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-posts", type=int, default=9)
    ap.add_argument("--backlog-per-run", type=int, default=BACKLOG_PER_RUN)
    a = ap.parse_args()

    pins = read_feed(FEED)
    feed_keys = set(p["key"] for p in pins)
    by_key = dict((p["key"], p) for p in pins)
    if os.path.exists(ARCHIVE):
        for p in read_feed(ARCHIVE):
            by_key.setdefault(p["key"], p)
    else:
        print("AVERTISSEMENT: %s absent, candidats limites a %s" % (ARCHIVE, FEED), file=sys.stderr)
    allp = sorted(by_key.values(), key=lambda p: (p["date"], p["n"]))
    table = rot.lire_categories()
    for p in allp:   # categorie d'une epingle = celle de sa page de destination
        p["categorie"] = rot.categorie(re.sub(r"^https?://[^/]+/", "", p["link"]).strip("/"), table=table)
    reg_lines = read_lines(REG)
    reg = set()
    hist = []   # (date, categorie, commerciale) de chaque publication, plus ancienne d'abord
    last_end, last_aff = None, None
    for l in reg_lines or []:
        c = l.split("\t")
        if len(c) >= 2 and c[1] == NETWORK:
            reg.add(c[0])
            cat = c[4] if len(c) >= 5 and c[4] else (by_key[c[0]]["categorie"] if c[0] in by_key else rot.categorie(c[0], table=table))
            aff = c[6] if len(c) >= 7 and c[6] else None
            hist.append((c[3] if len(c) >= 4 else "", cat, cat == rot.COMMERCIALE or bool(aff)))
            last_end = c[5] if len(c) >= 6 and c[5] in ENDINGS else ENDING
            last_aff = aff or last_aff
    arr_lines = read_lines(ARR)
    first_run = not reg and arr_lines is None
    arriere = set(feed_keys) if first_run else set(arr_lines or [])
    if first_run and not a.dry_run:
        os.makedirs("_releves", exist_ok=True)
        with open(ARR, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(arriere)) + "\n")
    def postable(p):
        if make_text(p):
            return True
        print("SKIP %s: impossible de raccourcir le titre/conseil a une limite de phrase (texte non ecrit, pas de carte)" % p["key"], file=sys.stderr)
        return False
    cand = [p for p in allp if p["key"] not in reg]
    new = [p for p in cand if p["key"] in feed_keys and p["key"] not in arriere and postable(p)]
    back_all = sorted((p for p in cand if not (p["key"] in feed_keys and p["key"] not in arriere)), key=lambda p: p["n"])
    back_all = [p for p in back_all if postable(p)]
    back = back_all[:max(0, a.backlog_per_run)]
    # 29/10/2026 : la rotation des categories vaut aussi pour les epingles (ordre de preference inchange)
    todo = rot.choisir_pages(new + back, hist, datetime.now(timezone.utc).strftime("%Y-%m-%d"), max(0, a.max_posts),
                             commerciale=lambda p: p["categorie"] == rot.COMMERCIALE or page_amazon(p["link"]))
    pins = allp
    print("Candidats: %d pins (flux %d, archive+flux %d); registre: %d; premiere execution: %s; nouveaux: %d; arriere disponible: %d; arriere retenu: %d; a publier: %d; arriere restant apres ce passage: %d"
          % (len(allp), len(feed_keys), len(allp), len(reg), first_run, len(new), len(back_all), len(back), len(todo),
             len(back_all) - len([p for p in todo if p in back])))
    if not todo:
        pg = page_candidates(reg, allp)
        todo = rot.choisir_pages(pg, hist, datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                 max(0, min(PAGES_PER_RUN, a.max_posts)),
                                 commerciale=lambda p: p["categorie"] == rot.COMMERCIALE or p["amazon"])
        print("Epingles epuisees : pages du site sans epingle disponibles: %d ; retenues apres rotation des categories: %d (%s)"
              % (len(pg), len(todo), ", ".join(p["categorie"] for p in todo)))
    if not todo:
        print("Rien a publier.")
        return

    jwt = did = None
    etat_susp, e_susp = su.etat_de(SUSP)
    if etat_susp != "libre":
        print("Suspension : %s" % su.phrase(etat_susp, e_susp))
    if etat_susp == "suspendu" and not a.dry_run:
        print("::warning::Chaine Bluesky SUSPENDUE (refus de type blocage) : aucun appel a Bluesky. %s" % su.phrase(etat_susp, e_susp))
        return
    essai = etat_susp == "essai" and not a.dry_run
    if not a.dry_run:
        h, pw = os.environ.get("BLUESKY_HANDLE"), os.environ.get("BLUESKY_APP_PASSWORD")
        if not h or not pw:
            die("BLUESKY_HANDLE / BLUESKY_APP_PASSWORD absents de l'environnement")
        if essai:
            su.prendre_essai(SUSP)
            print("::warning::Essai UNIQUE apres suspension : %s" % su.phrase(etat_susp, e_susp))
        try:
            out, _ = http("POST", HOST + "/xrpc/com.atproto.server.createSession", {"identifier": h, "password": pw})
        except SystemExit:
            motif_b = su.blocage(LAST_ERR[0])
            if motif_b:
                s = su.poser(SUSP, "bluesky", "ouverture de session : %s" % motif_b)
                print("::error::BLOCAGE Bluesky, chaine suspendue (refus n°%d), prochain essai %s" % (s["refus"], s["prochain_essai"]))
            raise
        s = json.loads(out)
        jwt, did = s["accessJwt"], s["did"]

    failures = 0
    posted = []
    for p in todo:
        last_end = rot.choisir_variante(ENDINGS, last_end)
        if "amazon" not in p:
            p["amazon"] = page_amazon(p["link"])
        aff = None
        if p["amazon"]:
            aff = last_aff = rot.choisir_variante(MENTIONS_AFF, last_aff)
        p.setdefault("categorie", rot.categorie(p["key"]))
        text = make_text(p, last_end, aff)
        if text and INTERDIT.search(text):
            text = None
        if not text:
            print("ECHEC %s: impossible de raccourcir le conseil a une limite de phrase" % p["key"], file=sys.stderr)
            failures += 1
            if not a.dry_run:
                note_echec(p["key"], "texte impossible a raccourcir")
            continue
        assert text.endswith(last_end + ((" " + aff) if aff else "")) and len(text) <= MAX_CHARS
        if a.dry_run:
            print("---- %s [%s] (%s) ----\ntexte (%d car.):\n%s\npage: %s\nimage: %s\ncarte: %s | %s\n"
                  % (p["key"], p["categorie"], "nouveau" if p in new else ("page" if p["key"].startswith("page:") else "arriere, plus ancien d'abord"),
                     len(text), text, p["link"], p["image"], p["title"], card_desc(p)))
            continue
        # 07/11/2026 (correctif 6, N.8) : ?src=bluesky sur la carte et la facette.
        ext = {"uri": avec_src(p["link"], "bluesky"), "title": p["title"], "description": card_desc(p)}
        thumb = "thumb=absent raison=inconnue"
        try:
            local = os.path.join("pins", os.path.basename(p["image"] or ""))
            if p["image"] and os.path.isfile(local):
                with open(local, "rb") as f:
                    img = f.read()
                ct = "image/png" if img[:4] == b"\x89PNG" else ("image/jpeg" if img[:2] == b"\xff\xd8" else "image/png")
                src = "fichier local " + local
            else:
                img, hd = http("GET", p["image"])
                ct = hd.get("Content-Type", "image/png").split(";")[0]
                src = "http " + str(p["image"])
            if len(img) > MAX_BLOB:
                thumb = "thumb=absent raison=image trop lourde (%d o)" % len(img)
            else:
                out, _ = http("POST", HOST + "/xrpc/com.atproto.repo.uploadBlob", headers={"Authorization": "Bearer " + jwt, "Content-Type": ct}, raw=img)
                ext["thumb"] = json.loads(out)["blob"]
                thumb = "thumb=ok"
                print("vignette ok (%d o, %s, %s)" % (len(img), ct, src))
        except SystemExit:
            thumb = "thumb=absent raison=" + LAST_ERR[0].replace("\t", " ").replace("\n", " ")[:250]
        except Exception as e:
            thumb = "thumb=absent raison=exception %s" % str(e)[:200]
        print(thumb)
        rec = {"$type": "app.bsky.feed.post", "text": text, "facets": facets(text), "langs": ["en"],
               "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
               "embed": {"$type": "app.bsky.embed.external", "external": ext}}
        # Un refus de Bluesky ne tue plus le passage : on l'ecrit et l'epingle suivante part (meme tolerance que la vignette).
        try:
            out, _ = http("POST", HOST + "/xrpc/com.atproto.repo.createRecord", {"repo": did, "collection": "app.bsky.feed.post", "record": rec},
                          headers={"Authorization": "Bearer " + jwt})
            uri = json.loads(out)["uri"]
        except SystemExit:
            motif = LAST_ERR[0]
        except Exception as e:
            motif = "reponse illisible: %s" % str(e)[:250]
        else:
            motif = None
        if motif is not None:
            failures += 1
            print("ECHEC %s: %s" % (p["key"], motif), file=sys.stderr)
            note_echec(p["key"], motif)
            ecrire_last(posted, failures)
            motif_b = su.blocage(motif)
            if motif_b:
                s = su.poser(SUSP, "bluesky", "%s : %s" % (p["key"], motif_b))
                print("::error::BLOCAGE Bluesky, chaine suspendue (refus n°%d), prochain essai %s : %s"
                      % (s["refus"], s["prochain_essai"], motif_b))
                break
            time.sleep(2)
            continue
        if essai:
            su.lever(SUSP, "essai reussi : %s publie (%s)" % (p["key"], uri))
            essai = False
        with open(REG, "a", encoding="utf-8") as f:
            f.write("%s\t%s\t%s\t%s\t%s\t%s\t%s\n" % (p["key"], NETWORK, uri, datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                                      p["categorie"], last_end, aff or ""))
            f.flush(); os.fsync(f.fileno())
        web = WEB + uri.rstrip("/").split("/")[-1]
        posted.append("%s\t%s\t%s\t%s" % (p["key"], uri, web, thumb))
        print("POSTED %s\n  URI: %s\n  WEB: %s" % (p["key"], uri, web))
        ecrire_last(posted, failures)
        time.sleep(2)
    if not a.dry_run:
        ecrire_last(posted, failures)
    if failures:
        die("%d pin(s) non publies" % failures, 1)


if __name__ == "__main__":
    main()
