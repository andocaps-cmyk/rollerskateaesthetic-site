#!/usr/bin/env python3
"""
PREUVE QUOTIDIENNE DU PROJET PINTEREST ROLLER — posee le 30/09/2026.

CE QUE FAIT CE FICHIER
----------------------
Une fois par jour, il envoie UN message Telegram au propriétaire avec trois lignes MESUREES :
  1. l'heure de la derniere execution REUSSIE de « Fournee quotidienne » (`fournee.yml`),
     lue dans l'API GitHub ;
  2. l'heure de la derniere execution REUSSIE de « Publication Bluesky » (`bluesky.yml`),
     lue dans l'API GitHub ;
  3. le nombre de descriptions Pinterest restant a reecrire, lu dans
     `_releves/descriptions_pinterest_restantes.txt` (fichier pousse chaque jour depuis `un document interne`
     par la tache locale `une tache locale`, script `pousser_restantes.py` du dossier).
VERT = les lignes 1 et 2 datent de moins de 26 heures. ROUGE = la premiere ligne du message dit
laquelle ne tient pas. Le nombre de la ligne 3 n'a pas de seuil ; il est donne avec sa date.
Une mesure illisible (API muette, fichier absent) est ROUGE, jamais verte.

MOTIF. Demande du propriétaire du 30/09/2026 : savoir que tout a marche, sans verifications empilees.
Ce message ne verifie aucune autre tache ni aucun autre verificateur : il lit le travail fait.

CANAL. Le message part sur le meme bot et la meme conversation Telegram que la routine
« Alerte Telegram — taches programmees en panne ». Si l'envoi echoue, le script sort en code 1 :
GitHub envoie alors son courriel d'echec, qui devient le canal de secours.

USAGE (essai hors production)
    python3 preuve_quotidienne.py --sans-envoi                     # mesure et affiche
    python3 preuve_quotidienne.py --sans-envoi --maintenant 2026-10-03T12:00:00Z
    python3 preuve_quotidienne.py --sans-envoi --restantes <fichier>
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEPOT = os.environ.get("GITHUB_REPOSITORY", "andocaps-cmyk/rollerskateaesthetic-site")
HEURES_MAX = 26  # un passage quotidien + 2 h de retard possible d'un cron GitHub
CHAINES = [("fournee.yml", "Fournée quotidienne"), ("bluesky.yml", "Publication Bluesky")]
FICHIER_RESTANTES = Path("_releves/descriptions_pinterest_restantes.txt")


def arg(nom):
    a = sys.argv[1:]
    return a[a.index(nom) + 1] if nom in a else None


def derniere_reussite(fichier, jeton):
    url = f"https://api.github.com/repos/{DEPOT}/actions/workflows/{fichier}/runs?status=success&per_page=1"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {jeton}", "Accept": "application/vnd.github+json",
        "User-Agent": "preuve-quotidienne"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            runs = json.loads(r.read().decode()).get("workflow_runs", [])
    except Exception as e:  # noqa: BLE001 — toute erreur de lecture vaut rouge
        return None, f"API GitHub illisible ({type(e).__name__}: {e})"
    if not runs:
        return None, "aucune execution reussie trouvee"
    return datetime.fromisoformat(runs[0]["updated_at"].replace("Z", "+00:00")), None


def lire_restantes(chemin):
    if not chemin.is_file():
        return None, f"{chemin} absent"
    champs = dict(l.split("=", 1) for l in chemin.read_text(encoding="utf-8").splitlines() if "=" in l)
    if not champs.get("restantes", "").strip().isdigit():
        return None, f"{chemin} sans nombre lisible"
    return champs, None


def heure(d):
    return d.strftime("%d/%m %Hh%M UTC")


def main():
    maintenant = datetime.now(timezone.utc)
    if arg("--maintenant"):
        maintenant = datetime.fromisoformat(arg("--maintenant").replace("Z", "+00:00"))
    jeton = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    lignes, rouges = [], []
    for fichier, nom in CHAINES:
        quand, erreur = derniere_reussite(fichier, jeton) if jeton else (None, "pas de jeton GitHub")
        if quand is None:
            lignes.append(f"{nom} : NON MESURÉ ({erreur})")
            rouges.append(nom)
            continue
        age = maintenant - quand
        heures = int(age.total_seconds() // 3600)
        lignes.append(f"{nom} réussie : {heure(quand)} (il y a {heures} h)")
        if age > timedelta(hours=HEURES_MAX):
            rouges.append(f"{nom} (dernière réussite il y a {heures} h, seuil {HEURES_MAX} h)")

    champs, erreur = lire_restantes(Path(arg("--restantes") or FICHIER_RESTANTES))
    if champs is None:
        lignes.append(f"Descriptions Pinterest à réécrire : NON MESURÉ ({erreur})")
        rouges.append("nombre de descriptions illisible")
    else:
        lignes.append(
            f"Descriptions Pinterest à réécrire : {champs['restantes'].strip()} "
            f"(un document interne du {champs.get('date_etat', '?').strip()}, poussé le {champs.get('pousse_le', '?').strip()})")

    # 14/10/2026, demande du propriétaire : rien sur Telegram quand tout va bien ; quand ça ne va pas, des mots
    # normaux et ce qu'il doit faire, sans détail technique. Le détail reste dans le journal de l'exécution.
    print("\n".join(lignes))
    if not rouges:
        print("VERT : aucun message envoyé (silence voulu quand tout va bien).")
        return
    arrets = [nom for _, nom in CHAINES if any(r.startswith(nom) for r in rouges)]
    if arrets:
        quoi = "La publication automatique du site Roller Skate Aesthetic ne tourne plus depuis plus d'un jour"
        quoi += " (" + ", ".join(a.lower() for a in arrets) + ")."
    else:
        quoi = "Le contrôle quotidien du site Roller Skate Aesthetic n'a pas pu lire ses chiffres."
    message = quoi + "\nCe que tu fais : rien aujourd'hui. Si ce message revient demain, ouvre une session avec le chef."
    print(message)

    if "--sans-envoi" in sys.argv:
        print("\n(--sans-envoi : rien n'est parti)")
        return
    bot, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not bot or not chat:
        print("ENVOI IMPOSSIBLE : secrets TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID absents.")
        raise SystemExit(1)
    donnees = urllib.parse.urlencode({"chat_id": chat, "text": message}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{bot}/sendMessage", donnees, timeout=30) as r:
            ok = json.loads(r.read().decode()).get("ok")
    except Exception as e:  # noqa: BLE001
        print(f"ENVOI TELEGRAM EN ECHEC : {type(e).__name__}")
        raise SystemExit(1)
    print(f"Telegram ok={ok}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
