#!/usr/bin/env python3
"""Releve quotidien des chiffres Instagram du compte, par l'API officielle (instagram_business_manage_insights). Stdlib seule.

Ecrit le 29/10/2026, sur le modele de releve_threads.py. Lance par .github/workflows/instagram.yml apres la publication,
une fois par jour (le premier passage du jour ecrit, les suivants ne font rien).
- _releves/releve_instagram.csv : une ligne par jour, colonnes de un document interne. releve_reseaux.py, sur
  l'ordinateur du propriétaire, la recopie dans un document interne.
- _releves/releve_instagram_publications.csv : une ligne par jour et par publication du registre (vues, portee,
  j'aime, commentaires, enregistrements, partages).
Lecture seule : ce script ne publie, ne modifie et ne supprime rien.
"""
import json, os, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

from releve_threads import heure_paris, ENTETE

API = "https://graph.instagram.com/v23.0"
REG = "_releves/publies_instagram.tsv"
JOUR = "_releves/releve_instagram.csv"
DETAIL = "_releves/releve_instagram_publications.csv"
METRIQUES = ["views", "reach", "likes", "comments", "saved", "shares"]


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
        if "total_value" in m:
            out[m["name"]] = m["total_value"].get("value")
        elif m.get("values"):
            out[m["name"]] = sum(v.get("value") or 0 for v in m["values"])
    return out


def main():
    jeton = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not jeton:
        sys.exit("ERREUR: INSTAGRAM_ACCESS_TOKEN absent")
    p = heure_paris(datetime.now(timezone.utc))
    date, heure = p.strftime("%Y-%m-%d"), p.strftime("%H:%M")
    if os.path.exists(JOUR) and any(l.startswith(date + ";") for l in open(JOUR, encoding="utf-8")):
        print("Releve du %s deja ecrit." % date)
        return
    erreurs = []
    moi = appel("/me", {"fields": "user_id,followers_count,media_count", "access_token": jeton})
    uid = os.environ.get("INSTAGRAM_USER_ID", "").strip() or moi.get("user_id")
    compte = {}
    try:
        compte = valeurs(appel("/%s/insights" % uid, {"metric": "reach,views", "period": "day",
                                                      "metric_type": "total_value", "access_token": jeton}))
    except RuntimeError as e:
        erreurs.append("compte : %s" % e)
    registre = [l.rstrip("\n").split("\t") for l in open(REG, encoding="utf-8")
                if l.strip() and not l.startswith("#")] if os.path.exists(REG) else []
    neuf = not os.path.exists(DETAIL)
    notes = 0
    with open(DETAIL, "a", encoding="utf-8") as f:
        if neuf:
            f.write("date;cle;id_instagram;" + ";".join(METRIQUES) + "\n")
        for c in registre:
            try:
                v = valeurs(appel("/%s/insights" % c[1], {"metric": ",".join(METRIQUES), "access_token": jeton}))
            except RuntimeError as e:
                erreurs.append("%s : %s" % (c[0], e))
                continue
            notes += sum(v.get(k) or 0 for k in ("likes", "comments", "saved", "shares"))
            f.write("%s;%s;%s;%s\n" % (date, c[0], c[1], ";".join(str(v.get(m, "")) for m in METRIQUES)))
    ligne = [date, heure, "instagram", str(moi.get("media_count", len(registre))), str(moi.get("followers_count", "")),
             str(notes), str(compte.get("views", "")), "", "",
             "graph.instagram.com /me (followers_count, media_count) + insights du compte (views, reach=%s, jour) "
             "+ insights par publication (j'aime+commentaires+enregistrements+partages)" % compte.get("reach", "?"),
             '"%s"' % " | ".join(erreurs).replace('"', "'") if erreurs else ""]
    neuf = not os.path.exists(JOUR)
    with open(JOUR, "a", encoding="utf-8") as f:
        if neuf:
            f.write(ENTETE + "\n")
        f.write(";".join(ligne) + "\n")
    print(";".join(ligne))


if __name__ == "__main__":
    main()
