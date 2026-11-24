#!/usr/bin/env python3
"""
SURVEILLANCE QUOTIDIENNE DE LA CHAINE DE PUBLICATION — tourne sur les serveurs de GitHub.

CE QUE FAIT CE FICHIER, POUR QUI N'A RIEN LU
--------------------------------------------
Il verifie chaque jour que la chaine qui mene une epingle du depot jusqu'au compte Pinterest
n'est cassee nulle part, et il SORT EN ERREUR des qu'un maillon lache. Une execution rouge
chez GitHub envoie un courriel toute seule au proprietaire du depot : c'est la seule alerte
du dispositif qui ne depende d'aucune machine allumee.

POURQUOI IL EXISTE, ET C'EST UNE MESURE, PAS UNE PRECAUTION
------------------------------------------------------------
Le planificateur de taches de l'application Claude cesse de declencher quoi que ce soit apres
24 a 30 heures de fonctionnement de Windows. C'est le un bogue connu de l'outil local, ferme
« non planifie » : il n'y a pas de correctif et il n'y en aura pas. La surveillance qui vivait
la-bas s'arretait donc des que le proprietaire s'absentait, et rien ne le signalait — la liste
des taches a l'air normale, avec un prochain passage annonce qui n'arrive jamais.

Constate le 21/08/2026 : plus rien n'avait tourne depuis le 19/08, soit trois jours sans
releve de publication, et personne ne l'a su avant d'aller regarder.

CE QU'IL SURVEILLE, ET POURQUOI CHACUN
---------------------------------------
1. LE FLUX DU SITE PORTE LA SORTIE QUE LE CALENDRIER ATTEND. Depuis le 19/10/2026, `build_feed.py`
   ne sort que le lundi, le mardi, le jeudi et le vendredi ; la sortie du jour n'est exigee qu'une
   fois que `fournee.yml` a reussi aujourd'hui. Si le flux est plus vieux, la fournee n'a pas pousse.
2. LE RESERVOIR N'EST PAS VIDE. La fin de matiere est le seul defaut qui arrive a zero en
   silence : le compte cesse de publier et le premier signe serait constate des jours plus tard.
3. PINTEREST A INGERE DANS LES DERNIERES 48 HEURES, plus 24 h par jour sans sortie. C'est le
   DERNIER METRE, et c'est le seul maillon que le depot ne voit pas : le 21/08/2026, deux
   epingles fabriquees et publiees sur le site n'etaient sur aucun tableau.
4. LES PAGES DU SITE RENDENT LEUR CONTENU. ⛔ Verifie sur le CONTENU et JAMAIS sur le code HTTP :
   ce site rend 200 sur toute adresse, y compris inexistante. Un controle par code de reponse
   passerait au vert sur un site entierement vide.
5. LE NOMBRE DE PAGES PORTANT UN LIEN D'AFFILIATION NE BAISSE PAS. C'est le seul chiffre du
   depot qui touche l'encaissement.

CE QU'IL NE FAIT PAS, ET C'EST VOULU
-------------------------------------
Il ne repare rien, il n'ecrit dans aucun fichier et il ne pousse rien. Un surveillant qui
corrige masque ce qu'il corrige.

USAGE
-----
    python3 surveillance.py            # controle complet
    python3 surveillance.py --hors-ligne   # saute les controles qui sortent sur le reseau
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import shutil
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOMAINE = "https://rollerskateaesthetic.com"
FLUX_PINTEREST = "https://www.pinterest.com/rollerskateaesthetic/feed.rss"

# ⛔ PLANCHER DU NOMBRE DE PAGES PORTANT UN LIEN D'AFFILIATION.
# Il se MONTE a la main dans le geste qui equipe des pages, jamais tout seul : un plancher qui
# se recalcule sur l'etat du jour ne peut pas detecter une baisse, puisqu'il la suit.
# Valeur au 22/08/2026, mesuree sur le depot publie.
PLANCHER_LIENS = 32

# Nombre de pages du site tirees du flux et lues en entier a chaque passage.
ECHANTILLON_PAGES = 3

# Age maximal tolere pour la derniere ingestion Pinterest. Deux jours, parce que l'ingestion a
# deja saute une journee et s'est rattrapee le lendemain a la meme minute, deux fois : le
# 15/08 et le 21/08/2026. Un seuil de 24 h aurait crie deux fois pour rien.
HEURES_MAX_INGESTION = 48

ECHECS: list[str] = []
AVERTISSEMENTS: list[str] = []


def echec(titre: str, detail: str) -> None:
    ECHECS.append(f"{titre}\n    {detail}")
    print(f"[ECHEC]  {titre}\n         {detail}")


def avertir(titre: str, detail: str) -> None:
    AVERTISSEMENTS.append(f"{titre}\n    {detail}")
    print(f"[ALERTE] {titre}\n         {detail}")


def ok(titre: str, detail: str = "") -> None:
    print(f"[OK]     {titre}" + (f"\n         {detail}" if detail else ""))


def lire_url(url: str, timeout: int = 30) -> str:
    requete = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; surveillance-rollerskateaesthetic)"},
    )
    with urllib.request.urlopen(requete, timeout=timeout) as reponse:
        return reponse.read().decode("utf-8", errors="replace")


# ── 1. LE FLUX DU SITE EST DATE D'AUJOURD'HUI ────────────────────────────────────────────
def sortie_attendue(jour):
    """La plus recente sortie que le flux DOIT porter ce jour-la, ou None s'il n'en attend aucune.

    ⛔ AJOUTE LE 22/10/2026. Jusque-la ce controle exigeait une sortie datee du jour meme ; depuis le
    19/10/2026, `build_feed.py` ne publie que quatre jours par semaine, et le controle a rougi pour
    rien le mercredi 21/10. La regle du calendrier vit dans `build_feed.py` (`fenetre`) et elle est
    LUE ici, jamais recopiee : deux copies d'une meme regle divergent, c'est le defaut du 21/10.
    """
    sys.path.insert(0, str(HERE))
    import build_feed
    choisies = build_feed.fenetre(build_feed.lire_csv(), jour)
    return max(r["_pub"] for r in choisies).date() if choisies else None


def fournee_du_jour_aboutie(aujourdhui: date) -> bool | None:
    """Vrai si une execution de `fournee.yml` a reussi aujourd'hui (UTC). None si on ne peut pas le
    savoir : hors de GitHub, sans jeton, ou API injoignable.

    ⛔ AJOUTE LE 22/10/2026 : L'HEURE NE SUFFIT PAS. La fournee est programmee a 10 h UTC mais GitHub
    la retarde de plusieurs heures (passee a 14 h 35 et 14 h 46 UTC les 20 et 21/10/2026), et la
    surveillance aussi (16 h 00 UTC le 21/10). Rien ne garantit donc que la surveillance passe apres
    la fournee ; seule la fin reelle de la fournee dit que la sortie du jour est due.
    """
    depot = os.environ.get("GITHUB_REPOSITORY")
    jeton = os.environ.get("GITHUB_TOKEN")
    if not depot or not jeton:
        return None
    url = (
        f"https://api.github.com/repos/{depot}/actions/workflows/fournee.yml/runs"
        f"?status=success&created=%3E%3D{aujourdhui.isoformat()}&per_page=1"
    )
    requete = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {jeton}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            return json.load(reponse).get("total_count", 0) > 0
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None


def controle_flux_du_site(
    aujourdhui: date | None = None,
    fournee_faite: bool | None = None,
    chemin: Path | None = None,
) -> list[str]:
    """Rend la liste des adresses d'epingles du flux, pour l'echantillon du controle 4."""
    aujourdhui = aujourdhui or datetime.now(timezone.utc).date()
    chemin = chemin or HERE / "feed.xml"
    if not chemin.exists():
        echec("Le flux du site est INTROUVABLE", f"{chemin} n'existe pas dans le depot.")
        return []

    brut = chemin.read_text(encoding="utf-8")
    dates = [parsedate_to_datetime(d) for d in re.findall(r"<pubDate>([^<]+)</pubDate>", brut)]
    liens = re.findall(r"<link>([^<]+)</link>", brut)
    liens_epingles = [l for l in liens if "/skate/" in l]

    if not dates:
        # Pause volontaire (26/10/2026, domaine bloque par Pinterest) : voir PAUSE_PINTEREST dans build_feed.py.
        if (HERE / "_releves" / "PAUSE_PINTEREST.txt").exists():
            ok("Flux du site vide VOLONTAIREMENT : pause Pinterest (_releves/PAUSE_PINTEREST.txt)")
            return liens_epingles
        if sortie_attendue(aujourdhui) is None:
            ok("Flux du site vide, et c'est le calendrier : aucune epingle en vol aujourd'hui")
        else:
            echec("Le flux du site est VIDE", "Aucun <pubDate> dans feed.xml — plus rien ne partira.")
        return liens_epingles

    plus_recente = max(dates)
    attendue = sortie_attendue(aujourdhui)
    # La sortie du jour n'est due qu'une fois la fournee du jour reussie ; avant, ou si on ne peut
    # pas le savoir, le calendrier de la veille fait foi. Une fournee qui n'a pas tourne du tout
    # se voit le lendemain ; une fournee rouge, le jour meme, par son propre courriel d'echec.
    if attendue == aujourdhui and not fournee_faite:
        print("         (fournee du jour pas encore reussie, ou etat inconnu : "
              "le calendrier de la veille fait foi)")
        attendue = sortie_attendue(aujourdhui - timedelta(days=1))
    if attendue is None:
        ok(f"Flux du site — aucune sortie attendue aujourd'hui ({aujourdhui:%A}), "
           f"{len(dates)} epingle(s) encore en vol")
    elif plus_recente.date() < attendue:
        retard = (attendue - plus_recente.date()).days
        echec(
            f"Le flux du site est PERIME de {retard} jour(s) de sortie",
            f"Derniere sortie datee du {plus_recente.date()}, le calendrier en attend une du {attendue}. "
            "La fournee quotidienne n'a pas pousse : regarder l'execution de fournee.yml.",
        )
    else:
        ok(f"Flux du site a jour — {len(dates)} epingle(s) en vol, plus recente du {plus_recente.date()}")
    return liens_epingles


# ── 2. LE RESERVOIR N'EST PAS VIDE ───────────────────────────────────────────────────────
def controle_reservoir() -> None:
    """Rejoue build_feed.py --fenetre dans une COPIE, pour ne rien reecrire dans le depot."""
    with tempfile.TemporaryDirectory() as bac:
        copie = Path(bac) / "site"
        shutil.copytree(HERE, copie, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        resultat = subprocess.run(
            [sys.executable, "build_feed.py", "--fenetre"],
            cwd=copie, capture_output=True, text=True,
        )
    sortie = (resultat.stdout or "") + (resultat.stderr or "")
    if resultat.returncode != 0:
        echec(
            "RESERVOIR VIDE ou flux impossible a construire",
            sortie.strip().replace("\n", "\n    ") or "Aucun message rendu par build_feed.py.",
        )
        return
    preavis = [l for l in sortie.splitlines() if "PREAVIS" in l]
    if preavis:
        avertir("Fin de matiere en approche", preavis[0].strip())
    else:
        ok("Reservoir suffisant — aucun preavis de fin de matiere")


# ── 3. PINTEREST A INGERE DANS LES DERNIERES 48 HEURES (+ 24 H PAR JOUR SANS SORTIE) ─────
def heures_max_ingestion(aujourdhui: date) -> int:
    """Pinterest ingere vers 08 h 53 GMT l'epingle sortie la VEILLE (releve du 22/10/2026 : les
    sorties du 19 et du 20/10 ingerees le 20 et le 21 a 08 h 53). Un jour sans sortie n'a donc rien
    a ingerer le lendemain : chaque jour creux depuis la derniere ingestion due allonge le seuil
    d'autant. Sans ca, chaque lundi rougit — derniere ingestion le samedi matin, ~50 h avant.

    ⛔ Les jours de sortie se lisent dans `build_feed.py`, jamais recopies ici.
    """
    sys.path.insert(0, str(HERE))
    from build_feed import CHANGEMENT_CADENCE, jours_de_sortie

    jour = aujourdhui - timedelta(days=1)
    while jour >= CHANGEMENT_CADENCE and next(jours_de_sortie(jour)) != jour:
        jour -= timedelta(days=1)
    jours_creux = (aujourdhui - (jour + timedelta(days=1))).days
    return HEURES_MAX_INGESTION + 24 * jours_creux


def controle_ingestion_pinterest(aujourdhui: date | None = None) -> None:
    """
    ⛔ UN ECHEC DE LECTURE N'EST PAS UN ECHEC D'INGESTION, et les deux ne se confondent jamais.
    Pinterest peut refuser un serveur de GitHub ; ca ne dit rien de l'etat du compte. Donc une
    lecture qui echoue rend une ALERTE, et seule une lecture REUSSIE peut rendre un ECHEC.
    """
    try:
        brut = lire_url(FLUX_PINTEREST)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as erreur:
        avertir(
            "Le flux public Pinterest n'a pas pu etre lu",
            f"{type(erreur).__name__}: {erreur}. Ca ne dit RIEN de l'etat du compte — "
            "seule une lecture reussie peut conclure.",
        )
        return

    dates = [parsedate_to_datetime(d) for d in re.findall(r"<pubDate>([^<]+)</pubDate>", brut)]
    if not dates:
        avertir(
            "Le flux public Pinterest a repondu sans aucune date",
            f"{len(brut)} octets recus, zero <pubDate>. Page de connexion ou format change.",
        )
        return

    derniere = max(dates)
    age = datetime.now(timezone.utc) - derniere
    seuil = heures_max_ingestion(aujourdhui or datetime.now(timezone.utc).date())
    if age > timedelta(hours=seuil):
        echec(
            f"DERNIER METRE ROMPU — Pinterest n'a rien ingere depuis {age.days} jour(s)",
            f"Derniere ingestion le {derniere:%Y-%m-%d a %H:%M} GMT, seuil du jour {seuil} h. "
            "Le site publie, le compte ne suit plus : les epingles fabriquees ne sont sur aucun "
            "tableau.",
        )
    else:
        ok(
            f"Pinterest a ingere il y a {int(age.total_seconds() // 3600)} h (seuil du jour {seuil} h)",
            f"Derniere ingestion le {derniere:%Y-%m-%d a %H:%M} GMT.",
        )


# ── 4. LES PAGES DU SITE RENDENT LEUR CONTENU ────────────────────────────────────────────
def controle_pages_servies(liens: list[str]) -> None:
    """⛔ Sur le CONTENU, jamais sur le code HTTP : ce site rend 200 sur toute adresse."""
    a_lire = [DOMAINE + "/"] + liens[:ECHANTILLON_PAGES]
    for adresse in a_lire:
        # ⛔ DEUX TENTATIVES AVANT DE CRIER, ET C'EST LA MOITIE QUI COMPTE. Une coupure passagere
        # du reseau du serveur qui execute ce controle ferait rougir l'execution pour un defaut
        # qui n'est pas le notre. Une alerte qui se trompe assez souvent finit par etre ignoree,
        # et le jour ou elle a raison plus personne ne la lit.
        page = None
        derniere_erreur = None
        for tentative in (1, 2):
            try:
                page = lire_url(adresse)
                break
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as erreur:
                derniere_erreur = erreur
                if tentative == 1:
                    time.sleep(5)
        if page is None:
            echec(
                f"La page ne repond pas, DEUX tentatives — {adresse}",
                f"{type(derniere_erreur).__name__}: {derniere_erreur}",
            )
            continue

        titre = re.search(r"<title>(.*?)</title>", page, re.S)
        corps = re.findall(r"<p[^>]*>(.*?)</p>", page, re.S)
        texte = re.sub(r"<[^>]+>", "", "".join(corps)).strip()

        if not titre or not titre.group(1).strip():
            echec(f"Page servie SANS TITRE — {adresse}", f"{len(page)} octets recus.")
        elif len(texte) < 200:
            echec(
                f"Page servie PRESQUE VIDE — {adresse}",
                f"Titre present mais seulement {len(texte)} caracteres de texte dans les <p>. "
                "Le deploiement Cloudflare a servi une coquille.",
            )
        else:
            ok(f"Page servie et pleine — {adresse}", f"{len(texte)} caracteres de texte.")


# ── 5. LE NOMBRE DE PAGES PORTANT UN LIEN D'AFFILIATION NE BAISSE PAS ────────────────────
def controle_liens_affiliation() -> None:
    pages = sorted((HERE / "skate").glob("*/index.html"))
    equipees = [p for p in pages if "aws/cart/add.html" in p.read_text(encoding="utf-8")]
    if len(equipees) < PLANCHER_LIENS:
        echec(
            f"LES LIENS D'AFFILIATION ONT BAISSE — {len(equipees)} page(s) equipee(s) "
            f"pour un plancher de {PLANCHER_LIENS}",
            "Des liens ont disparu du depot. C'est le seul chiffre qui touche l'encaissement.",
        )
    else:
        ok(
            f"Liens d'affiliation — {len(equipees)} page(s) equipee(s) sur {len(pages)}, "
            f"plancher {PLANCHER_LIENS}"
        )


def main() -> None:
    hors_ligne = "--hors-ligne" in sys.argv[1:]
    print("=" * 78)
    print(f"SURVEILLANCE DE LA CHAINE DE PUBLICATION — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    print("=" * 78)

    aujourdhui = datetime.now(timezone.utc).date()
    fournee_faite = None if hors_ligne else fournee_du_jour_aboutie(aujourdhui)
    liens = controle_flux_du_site(aujourdhui, fournee_faite)
    controle_reservoir()
    controle_liens_affiliation()
    if hors_ligne:
        print("[SAUTE]  Controles reseau ignores (--hors-ligne).")
    else:
        controle_ingestion_pinterest(aujourdhui)
        controle_pages_servies(liens)

    print("-" * 78)
    if AVERTISSEMENTS:
        print(f"{len(AVERTISSEMENTS)} alerte(s) — elles ne font PAS rougir l'execution :")
        for a in AVERTISSEMENTS:
            print(f"  - {a}")
    if ECHECS:
        print(f"\n{len(ECHECS)} MAILLON(S) CASSE(S) :")
        for e in ECHECS:
            print(f"  - {e}")
        print("\n⛔ L'EXECUTION EST ROUGE EXPRES. Le courriel que GitHub envoie est l'alerte.")
        raise SystemExit(1)
    print("Aucun maillon casse. La chaine tient.")


if __name__ == "__main__":
    main()
