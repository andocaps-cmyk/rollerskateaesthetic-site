# -*- coding: utf-8 -*-
"""SUSPENSION D'UNE CHAINE DE PUBLICATION APRES UN REFUS DE TYPE BLOCAGE — une seule implementation, deux copies
declarees identiques octet pour octet :
  - le dossier de travail local/<dossier interne>/moteur_publication/suspension.py   (moteur de publication unique, poste reseaux, Windows)
  - depot andocaps-cmyk/rollerskateaesthetic-site, suspension.py (chaines GitHub Instagram, Threads, YouTube, Bluesky)
Toute correction se fait dans l'une PUIS se recopie dans l'autre ; l'empreinte SHA-256 des deux doit etre la meme
(commande : python suspension.py empreinte). Bibliotheque standard seule (Windows ET GitHub Actions).

Ecrit le 10/11/2026 par un agent du chef des chefs de projets, sur la remontee du projet Pinterest Roller du 10/11/2026
~14 h 45 (<fichier local>) : le compte Instagram cassrollerskateaesthetic est
refuse par Meta depuis le 08/11/2026 18:53 UTC (code 4, sous-code 2207051, « action is blocked ») et la chaine
retentait jusqu'a 3 fois par jour, parce qu'un refus ne comptait pas dans le plafond du jour.

LA REGLE (un document interne § 6, regle i) : un refus de plateforme de type BLOCAGE suspend la chaine du compte et
remonte ; il ne se retente pas. Pendant la suspension, un passage sort SANS appeler la plateforme (aucune cle lue).

CE QUI EST UN BLOCAGE (fonction blocage) :
  - Meta, codes lus le 10/11/2026 sur la page officielle
    https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/error-codes :
      code 4 / sous-code 2207051 « We restrict certain activity to protect our community » (publication suspectee de
      spam ; la page renvoie a « Let us know if you can determine that the publishing actions is not spam ») ;
      code 25 / sous-code 2207050 « The Instagram account is restricted » (compte inactif, en controle ou restreint :
      se connecter a l'application Instagram et faire ce qu'elle demande) ;
    code 368 (« temporarily blocked for policies violations ») ⟨NON MESURE ce jour : code connu de la Graph API,
    page non relue le 10/11/2026⟩ ;
  - toute autre reponse NON transitoire (is_transient different de true) dont le texte contient un mot de blocage
    (restrict, spam, suspend, blocked, bloqu, violat, abuse, takedown, checkpoint) — la liste du depot du site
    (publier_threads.ALERTE_MOTS) plus takedown et checkpoint ; c'est une heuristique, pas une page lue.
  N'EST PAS un blocage : 2207042 (plafond quotidien de publication, « try again the following day »), un quota
  YouTube, un jeton mort (190, 401), une erreur de transport, une reponse marquee is_transient=true.

LE DELAI (pourquoi 72 h, puis le double) :
  - la page officielle des erreurs ne donne AUCUNE duree pour 2207051 ;
  - la page officielle des limites de debit (https://developers.facebook.com/docs/graph-api/overview/rate-limiting,
    lue le 10/11/2026) dit, pour le code 4 : « Continuing to make calls will continue to increase your call count,
    which will increase the time before calls will be successful again » et « When the limit has been reached, stop
    making API calls » ; c'est la seule phrase officielle lue sur le fait de retenter pendant un blocage ;
  - source tierce (Vista Social, support.vistasocial.com, article 5462397210011, lu le 10/11/2026) : restriction
    « temporary and will be lifted automatically », eviter toute activite « a few days », contacter le support si
    l'erreur persiste apres 2 a 3 jours. Non officiel.
  D'ou : aucun appel pendant 72 h apres le refus ; puis UN seul essai reel ; s'il est refuse encore, 144 h, puis
  288 h, puis 336 h (14 jours) au plus entre deux essais. Un essai reussi leve la suspension tout seul.
  La levee explicite (python suspension.py lever FICHIER --par "...") leve tout de suite, quel que soit le delai.

LE FICHIER D'ETAT : un fichier JSON par compte (jamais partage entre deux chaines : deux chaines GitHub qui ecrivent
le meme fichier se marchent dessus au rebase). Il n'est jamais supprime : la levee le marque « actif: false » et
garde l'historique.

Usage :
  python suspension.py etat FICHIER [FICHIER...]       etat lisible (code 0 libre, 3 suspendu, 4 essai permis)
  python suspension.py lever FICHIER --par "qui et pourquoi"
  python suspension.py poser FICHIER --cle CLE --motif "..." [--le 2026-11-10T01:52:11Z] [--refus N]
  python suspension.py autotest                         epreuve sans reseau (code 0 si tout passe)
  python suspension.py empreinte                        SHA-256 de ce fichier (les deux copies doivent l'egaler)
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys

DELAIS_H = [72, 144, 288, 336]          # apres le 1er refus, le 2e, le 3e, puis tous les suivants
ENTRE_DEUX_ESSAIS_H = 24                 # un essai pris et reste sans issue (ni succes ni blocage) n'est refait qu'apres 24 h
MOTS_BLOCAGE = re.compile(r"restrict|spam|suspend|blocked|bloqu|violat|abuse|takedown|checkpoint", re.I)
BLOCAGES_META = {
    (4, 2207051): "Meta 4/2207051 : publication suspectee de spam, « action is blocked » (page officielle des erreurs)",
    (25, 2207050): "Meta 25/2207050 : compte Instagram restreint, a ouvrir dans l'application (page officielle des erreurs)",
}
PAS_BLOCAGE_META = {(9, 2207042)}       # plafond quotidien : quota, pas blocage


def maintenant():
    return dt.datetime.now(dt.timezone.utc)


def _iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lit_date(s):
    if not s:
        return None
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def _json_dans(texte):
    """Le premier objet JSON contenu dans un texte d'erreur (« HTTP 403 sur /x : {...} »), ou None."""
    if isinstance(texte, dict):
        return texte
    texte = str(texte)
    i = texte.find("{")
    while i != -1:
        try:
            return json.JSONDecoder().raw_decode(texte[i:])[0]
        except ValueError:
            i = texte.find("{", i + 1)
    return None


def blocage(reponse):
    """Rend le motif si la reponse (dict JSON ou texte d'erreur) est un refus de type blocage, sinon None."""
    j = _json_dans(reponse)
    err = j.get("error") if isinstance(j, dict) else None
    if isinstance(err, dict):
        try:
            code = int(err.get("code")) if err.get("code") is not None else None
        except (TypeError, ValueError):
            code = None
        try:
            sous = int(err.get("error_subcode")) if err.get("error_subcode") is not None else None
        except (TypeError, ValueError):
            sous = None
        if (code, sous) in BLOCAGES_META:
            return BLOCAGES_META[(code, sous)]
        if (code, sous) in PAS_BLOCAGE_META or code == 190:
            return None
        if code == 368:
            return "Meta 368 : bloque temporairement pour infraction aux regles"
        if err.get("is_transient") is True:
            return None
        texte = " ".join(str(err.get(k, "")) for k in ("message", "error_user_title", "error_user_msg", "type"))
        m = MOTS_BLOCAGE.search(texte)
        if m:
            return "refus non transitoire, mot « %s » : %s" % (m.group(0), texte.strip()[:200])
        return None
    if isinstance(j, dict):                                   # Bluesky : {"error": "AccountTakedown", "message": ...}
        nom = str(j.get("error", ""))
        if nom in ("AccountTakedown", "AccountSuspended", "AccountDeactivated", "RepoTakendown", "RepoSuspended"):
            return "Bluesky %s : %s" % (nom, str(j.get("message", ""))[:200])
    texte = str(reponse)
    if re.search(r"is_transient\W+true", texte, re.I):
        return None
    if re.search(r"\b(401|429|5\d\d)\b", texte[:40]):         # jeton, debit, serveur : pas un blocage de compte
        return None
    m = MOTS_BLOCAGE.search(texte)
    if m:
        return "refus de la plateforme, mot « %s » : %s" % (m.group(0), texte.strip()[:200])
    return None


# ------------------------------------------------------------------ etat
def lire(fichier):
    try:
        with open(fichier, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _ecrire(fichier, etat):
    d = os.path.dirname(os.path.abspath(fichier))
    os.makedirs(d, exist_ok=True)
    tmp = fichier + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, fichier)


def etat_de(fichier, quand=None):
    """('libre', e) ; ('suspendu', e) : ne rien appeler ; ('essai', e) : un seul essai permis (prendre_essai d'abord)."""
    quand = quand or maintenant()
    e = lire(fichier)
    if not e.get("actif"):
        return "libre", e
    p = _lit_date(e.get("prochain_essai"))
    if p and quand >= p:
        return "essai", e
    return "suspendu", e


def prendre_essai(fichier, quand=None):
    """Note qu'un essai part maintenant ; repousse le suivant de 24 h, pour qu'un essai sans issue ne se refasse pas a
    chaque passage. Un succes leve (lever), un nouveau blocage repose (poser)."""
    quand = quand or maintenant()
    e = lire(fichier)
    e["essai_pris_le"] = _iso(quand)
    e["prochain_essai"] = _iso(quand + dt.timedelta(hours=ENTRE_DEUX_ESSAIS_H))
    e.setdefault("historique", []).append({"le": _iso(quand), "quoi": "essai"})
    _ecrire(fichier, e)
    return e


def poser(fichier, cle, motif, quand=None, refus=None):
    """Pose ou prolonge la suspension apres un refus de type blocage. Rend l'etat ecrit."""
    quand = quand or maintenant()
    e = lire(fichier)
    if e.get("actif"):
        n = int(e.get("refus", 0)) + 1
    else:
        n = 1
        e = {"cle": cle, "historique": e.get("historique", [])}
        e["depuis"] = _iso(quand)
    if refus is not None:
        n = int(refus)
    delai = DELAIS_H[min(n, len(DELAIS_H)) - 1]
    e.update(cle=cle, actif=True, refus=n, dernier_refus=_iso(quand), motif=str(motif)[:600],
             prochain_essai=_iso(quand + dt.timedelta(hours=delai)), delai_h=delai,
             regle="aucun appel avant prochain_essai ; puis un seul essai ; levee : python suspension.py lever <fichier>")
    e.pop("essai_pris_le", None)
    e.setdefault("historique", []).append({"le": _iso(quand), "quoi": "refus %d" % n, "motif": str(motif)[:300]})
    _ecrire(fichier, e)
    return e


def lever(fichier, par, quand=None):
    quand = quand or maintenant()
    e = lire(fichier)
    if not e:
        return e
    e["actif"] = False
    e["leve_le"] = _iso(quand)
    e["leve_par"] = str(par)[:300]
    e.setdefault("historique", []).append({"le": _iso(quand), "quoi": "levee", "par": str(par)[:300]})
    _ecrire(fichier, e)
    return e


def phrase(etat, e):
    if etat == "libre":
        return "libre" + (" (levee le %s : %s)" % (e.get("leve_le"), e.get("leve_par")) if e.get("leve_le") else "")
    return "%s — %s ; suspendue depuis %s, %s refus, dernier %s ; prochain essai %s ; motif : %s" % (
        "SUSPENDUE" if etat == "suspendu" else "ESSAI PERMIS", e.get("cle"), e.get("depuis"), e.get("refus"),
        e.get("dernier_refus"), e.get("prochain_essai"), str(e.get("motif", ""))[:200])


# ------------------------------------------------------------------ epreuve
def autotest():
    import tempfile
    ok = True

    def verifie(nom, cond):
        nonlocal ok
        print("%s %s" % ("OK   " if cond else "ECHEC", nom))
        ok = ok and cond

    reel = ('HTTP 403 sur /17841457015831355/media_publish : {"error":{"message":"Application request limit reached",'
            '"type":"OAuthException","is_transient":false,"code":4,"error_subcode":2207051,"error_user_title":'
            '"action is blocked","error_user_msg":"We restrict certain activity to protect our community. Tell us if you '
            'think we made a mistake.","fbtrace_id":"AZt12UH4xr3-TD43KPu9anc"}}')
    verifie("refus reel du 10/11/2026 01:52 (4/2207051) = blocage", bool(blocage(reel)))
    verifie("meme refus en dict = blocage", bool(blocage(json.loads(reel[reel.index("{"):]))))
    verifie("2207050 compte restreint = blocage", bool(blocage({"error": {"code": 25, "error_subcode": 2207050, "message": "x"}})))
    verifie("2207042 plafond quotidien != blocage", blocage({"error": {"code": 9, "error_subcode": 2207042,
                                                                       "message": "maximum number of posts"}}) is None)
    verifie("jeton mort 190 != blocage", blocage({"error": {"code": 190, "message": "Error validating access token"}}) is None)
    verifie("is_transient true != blocage", blocage({"error": {"code": 4, "is_transient": True, "message": "blocked"}}) is None)
    verifie("transport != blocage", blocage("reseau sur /x : timed out") is None)
    verifie("HTTP 429 != blocage", blocage("HTTP 429 sur /x : rate limited, spam") is None)
    verifie("Bluesky AccountTakedown = blocage", bool(blocage('HTTP 400 sur https://bsky.social/xrpc/x: {"error":"AccountTakedown","message":"m"}')))
    verifie("Threads texte « restricted » = blocage", bool(blocage('HTTP 400 sur /x/threads_publish : {"error":{"code":10,"message":"Your account is restricted"}}')))
    d = tempfile.mkdtemp()
    f = os.path.join(d, "suspension_essai.json")
    t0 = _lit_date("2026-11-10T01:52:11Z")
    verifie("fichier absent = libre", etat_de(f, t0)[0] == "libre")
    poser(f, "instagram", blocage(reel), t0)
    verifie("apres refus : suspendu", etat_de(f, t0 + dt.timedelta(hours=1))[0] == "suspendu")
    verifie("71 h apres : suspendu", etat_de(f, t0 + dt.timedelta(hours=71))[0] == "suspendu")
    verifie("72 h apres : essai permis", etat_de(f, t0 + dt.timedelta(hours=72))[0] == "essai")
    t1 = t0 + dt.timedelta(hours=73)
    prendre_essai(f, t1)
    verifie("essai pris : suspendu jusqu'a +24 h", etat_de(f, t1 + dt.timedelta(hours=1))[0] == "suspendu")
    poser(f, "instagram", "re-refus", t1)
    e = lire(f)
    verifie("2e refus : delai 144 h", e["refus"] == 2 and e["delai_h"] == 144 and etat_de(f, t1 + dt.timedelta(hours=143))[0] == "suspendu")
    for k in range(3, 7):
        poser(f, "instagram", "refus %d" % k, t1)
    verifie("6e refus : delai plafonne a 336 h", lire(f)["delai_h"] == 336)
    lever(f, "autotest", t1)
    verifie("levee : libre", etat_de(f, t1)[0] == "libre")
    poser(f, "instagram", "nouveau", t1)
    verifie("nouvel incident apres levee : refus 1, 72 h", lire(f)["refus"] == 1 and lire(f)["delai_h"] == 72)
    verifie("historique garde", len(lire(f)["historique"]) == 9)
    print("AUTOTEST", "REUSSI" if ok else "ECHEC")
    return 0 if ok else 1


def main(a):
    if not a:
        print(__doc__)
        return 2
    if a[0] == "autotest":
        return autotest()
    if a[0] == "empreinte":
        with open(os.path.abspath(__file__), "rb") as f:
            print(hashlib.sha256(f.read()).hexdigest())
        return 0
    if a[0] == "etat" and len(a) >= 2:
        pire = 0
        for f in a[1:]:
            et, e = etat_de(f)
            print("%s : %s" % (f, phrase(et, e)))
            pire = max(pire, {"libre": 0, "suspendu": 3, "essai": 4}[et])
        return pire
    if a[0] == "lever" and len(a) >= 4 and a[2] == "--par":
        e = lever(a[1], a[3])
        print("leve" if e else "rien a lever (fichier absent)")
        return 0
    if a[0] == "poser" and "--cle" in a and "--motif" in a:
        le = _lit_date(a[a.index("--le") + 1]) if "--le" in a else None
        refus = int(a[a.index("--refus") + 1]) if "--refus" in a else None
        e = poser(a[1], a[a.index("--cle") + 1], a[a.index("--motif") + 1], le, refus)
        print(phrase(*etat_de(a[1])))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
