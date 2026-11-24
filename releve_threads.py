#!/usr/bin/env python3
"""Releve quotidien des chiffres Threads du compte, par l'API officielle (permission threads_manage_insights). Stdlib seule.

Ecrit le 26/10/2026. Lance par .github/workflows/threads.yml apres la publication.
- _releves/releve_threads.csv : une ligne par jour, colonnes de un document interne (date;heure_paris;reseau;...).
  releve_reseaux.py, sur l'ordinateur du propriétaire, la recopie dans un document interne.
- _releves/releve_threads_publications.csv : une ligne par jour et par publication du registre
  (vues, j'aime, reponses, republications, citations, partages).
Lecture seule : ce script ne publie, ne modifie et ne supprime rien.
"""
import json, os, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

API = "https://graph.threads.net/v1.0"
REG = "_releves/publies_threads.tsv"
JOUR = "_releves/releve_threads.csv"
DETAIL = "_releves/releve_threads_publications.csv"
ENTETE = "date;heure_paris;reseau;billets_ou_articles;abonnes;notes_totales;viewers;page_flips;vues_mensuelles;source;erreur"
METRIQUES = ["views", "likes", "replies", "reposts", "quotes", "shares"]


def appel(chemin, params):
    url = API + chemin + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s sur %s : %s" % (e.code, chemin, e.read()[:300].decode("utf-8", "replace")))


def valeurs(reponse):
    out = {}
    for m in reponse.get("data", []):
        if "link_total_values" in m:
            out[m["name"]] = sum(x.get("value") or 0 for x in m["link_total_values"])
        elif "total_value" in m:
            out[m["name"]] = m["total_value"].get("value")
        elif m.get("values"):
            out[m["name"]] = sum(v.get("value") or 0 for v in m["values"])
    return out


def heure_paris(t):
    # heure d'ete d'Europe : du dernier dimanche de mars au dernier dimanche d'octobre, a 1 h UTC
    def dernier_dimanche(mois):
        d = datetime(t.year, mois, 31, 1, tzinfo=timezone.utc)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    ete = dernier_dimanche(3) <= t < dernier_dimanche(10)
    return t + timedelta(hours=2 if ete else 1)


def main():
    jeton = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not jeton:
        sys.exit("ERREUR: THREADS_ACCESS_TOKEN absent")
    t = datetime.now(timezone.utc)
    p = heure_paris(t)
    date, heure = p.strftime("%Y-%m-%d"), p.strftime("%H:%M")
    if os.path.exists(JOUR) and any(l.startswith(date + ";") for l in open(JOUR, encoding="utf-8")):
        print("Releve du %s deja ecrit." % date)
        return
    erreurs = []
    uid = os.environ.get("THREADS_USER_ID", "").strip() or appel("/me", {"fields": "id", "access_token": jeton})["id"]
    compte = {}
    try:
        compte = valeurs(appel("/%s/threads_insights" % uid, {"metric": "followers_count,clicks,views,likes,replies,reposts",
                                                             "access_token": jeton}))
    except RuntimeError as e:
        erreurs.append("compte : %s" % e)
    registre = [l.rstrip("\n").split("\t") for l in open(REG, encoding="utf-8")
                if l.strip() and not l.startswith("#")] if os.path.exists(REG) else []
    neuf = not os.path.exists(DETAIL)
    with open(DETAIL, "a", encoding="utf-8") as f:
        if neuf:
            f.write("date;cle;id_threads;" + ";".join(METRIQUES) + "\n")
        for c in registre:
            try:
                v = valeurs(appel("/%s/insights" % c[1], {"metric": ",".join(METRIQUES), "access_token": jeton}))
            except RuntimeError as e:
                erreurs.append("%s : %s" % (c[0], e))
                continue
            f.write("%s;%s;%s;%s\n" % (date, c[0], c[1], ";".join(str(v.get(m, "")) for m in METRIQUES)))
    notes = sum(compte.get(k) or 0 for k in ("likes", "replies", "reposts")) if compte else ""
    ligne = [date, heure, "threads", str(len(registre)), str(compte.get("followers_count", "")), str(notes),
             str(compte.get("views", "")), "", "",
             "graph.threads.net threads_insights (followers_count, views, likes+replies+reposts ; clics=%s) + insights par publication"
             % compte.get("clicks", "?"),
             '"%s"' % " | ".join(erreurs).replace('"', "'") if erreurs else ""]
    neuf = not os.path.exists(JOUR)
    with open(JOUR, "a", encoding="utf-8") as f:
        if neuf:
            f.write(ENTETE + "\n")
        f.write(";".join(ligne) + "\n")
    print(";".join(ligne))


if __name__ == "__main__":
    main()
