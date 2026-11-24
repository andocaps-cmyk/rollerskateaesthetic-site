#!/usr/bin/env python3
"""
Génère site/feed_archive.xml : le CATALOGUE ENTIER des épingles déjà sorties,
dans un second flux RSS, destiné à une plateforme AUTRE que Pinterest.

À QUOI IL SERT, ET POURQUOI IL EXISTE SÉPARÉMENT DE `build_feed.py`
------------------------------------------------------------------
`feed.xml` est une fenêtre roulante de deux jours (deux épingles par jour jusqu'au
18/10/2026, une par jour de sortie et quatre jours par semaine ensuite). C'est
volontaire : un flux RSS ne sait pas programmer à l'heure, donc la cadence de
publication se pilote en ne mettant dans le flux QUE ce qui doit partir ce jour-là.
Ce dispositif est réglé pour Pinterest et il ne se touche pas.

Conséquence : une seconde plateforme branchée sur `feed.xml` recevrait deux épingles
par jour et RIEN du catalogue déjà en ligne. Elle démarrerait vide alors que plus de
cent épingles existent déjà, fabriquées et payées.

Ce script écrit donc un SECOND fichier, `feed_archive.xml`, qui porte toutes les
épingles validées dont le jour de sortie est déjà passé. Une plateforme qui le relève
récupère le catalogue d'un coup, puis suit la même cadence que Pinterest ensuite.

⛔ CE QU'IL NE FAIT PAS, ET C'EST LA MOITIÉ QUI COMPTE
------------------------------------------------------
Il n'écrit jamais `feed.xml`, il ne modifie ni `DEPART_FENETRE`, ni `CHANGEMENT_CADENCE`,
ni `JOURS_EN_VOL`, ni `PUBLIEES`, ni `VALIDEES`. Il importe `build_feed.py` et lit son
`calendrier()` au lieu de recopier sa logique : une règle vit dans un seul fichier.
Si `build_feed.py` change, ce script suit sans être modifié.

⛔ AUCUNE ÉPINGLE NE SORT ICI AVANT D'ÊTRE SORTIE SUR PINTEREST
---------------------------------------------------------------
Le filtre est strict : une épingle n'entre dans ce flux que si son jour de sortie
calculé est aujourd'hui ou avant. Motif, et il n'est pas cosmétique : si une épingle
paraissait ailleurs AVANT de paraître sur Pinterest, le second compte deviendrait la
source d'origine aux yeux des moteurs de recherche, et le site — qui est l'actif que
le projet monétise — passerait pour la copie. Le second canal suit, il ne précède pas.

CALENDRIER DES ÉPINGLES DÉJÀ PUBLIÉES (11 à 24)
------------------------------------------------
Elles sont parties avant que le mode fenêtre n'existe, donc leur vraie date de sortie
n'est enregistrée nulle part sous forme exploitable. On leur attribue ici des dates
DÉTERMINISTES en remontant le temps depuis `DEPART_FENETRE`, à la même cadence de deux
par jour et dans l'ordre de leur numéro. Ces dates sont approchées d'un jour ou deux,
et c'est sans conséquence : elles ne servent qu'à ordonner le catalogue dans un lecteur
de flux, jamais à décider de ce qui part.

USAGE
-----
    python3 build_feed_archive.py            # tout le catalogue déjà sorti
    python3 build_feed_archive.py --max 50   # les 50 plus récentes seulement

Le fichier produit est déterministe : deux exécutions le même jour rendent un fichier
identique à l'octet près, donc `git commit` ne trouve rien et aucun déploiement inutile
n'est déclenché. C'est la même propriété que le mode `--fenetre` de `build_feed.py`,
et elle existe pour la même raison.
"""

import sys
from datetime import date, datetime, time, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import build_feed as bf

HERE = Path(__file__).resolve().parent
OUT = HERE / "feed_archive.xml"


def calendrier(lignes: list[dict]) -> list[tuple[dict, date]]:
    """Associe à chaque épingle validée son jour de sortie, passé ou futur.

    Les épingles déjà parties avant le mode fenêtre reçoivent des dates antérieures à
    `DEPART_FENETRE` ; les autres reçoivent exactement la date que `build_feed.py`
    leur donne. Les deux séries sont calculées d'une seule formule pour qu'aucun trou
    ni recouvrement ne puisse apparaître entre elles.
    """
    # Depuis le 18/10/2026 : la formule des dates vit dans `build_feed.calendrier()` (cadence
    # changee ce jour-la, 2 par jour puis 4 par semaine). Ici on ne recopie rien : on la lit.
    # Les REPRISES de `build_feed.py` (un second passage de quatre epingles jamais creees par
    # Pinterest) sont ecartees : le catalogue porte deja ces articles depuis aout sous leur guid
    # d'origine, et un lecteur qui les reverrait sous un autre guid les recevrait en double.
    deja = [r for r in lignes if r["_n"] in bf.VALIDEES and r["_n"] in bf.PUBLIEES]
    plan: list[tuple[dict, date]] = []
    for position, r in enumerate(deja):
        decalage = (position - len(deja)) // bf.PAR_JOUR_AVANT_CHANGEMENT
        plan.append((r, bf.DEPART_FENETRE + timedelta(days=decalage)))
    for r, jour, guid in bf.calendrier(lignes):
        if guid.endswith(bf.SUFFIXE_REPRISE):
            continue
        plan.append((r, jour))
    return plan


def main() -> None:
    args = sys.argv[1:]
    plafond = None
    if "--max" in args:
        plafond = int(args[args.index("--max") + 1])

    lignes = bf.lire_csv()
    aujourdhui = datetime.now(timezone.utc).date()

    sorties = [(r, jour) for r, jour in calendrier(lignes) if jour <= aujourdhui]
    if not sorties:
        raise SystemExit(
            "ARRET — aucune epingle n'est encore sortie sur Pinterest, il n'y a rien a "
            "archiver. Ce flux ne precede jamais le flux principal."
        )

    # Le plus récent en tête : c'est l'ordre qu'attendent les lecteurs de flux et les
    # plateformes qui ingèrent du RSS.
    sorties.sort(key=lambda t: (t[1], t[0]["_n"]), reverse=True)
    if plafond is not None:
        sorties = sorties[:plafond]

    # Minuit UTC et non midi : une epingle du jour datee de midi porterait un horodatage
    # encore dans le futur pour un lecteur qui releve le matin, et plusieurs plateformes
    # ignorent purement et simplement un item date du futur. Minuit est toujours passe, et
    # il reste deterministe — c'est la propriete qui evite les deploiements inutiles.
    items = "\n".join(
        bf.item(r, datetime.combine(jour, time(0, 0), tzinfo=timezone.utc), declaration_ia=True)
        for r, jour in sorties
    )
    derniere = datetime.combine(sorties[0][1], time(0, 0), tzinfo=timezone.utc)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Roller Skate Aesthetic — full archive</title>
    <link>{bf.DOMAIN}/</link>
    <description>Beginner roller skating tips, gear guides and skate aesthetic. Full archive feed.</description>
    <language>en-us</language>
    <lastBuildDate>{format_datetime(derniere)}</lastBuildDate>
    <atom:link href="{bf.DOMAIN}/feed_archive.xml" rel="self" type="application/rss+xml"/>
{items}
  </channel>
</rss>
"""
    OUT.write_text(xml, encoding="utf-8")
    nums = [r["_n"] for r, _ in sorties]
    print(
        f"feed_archive.xml ecrit — {len(sorties)} epingle(s), "
        f"de la n°{min(nums)} a la n°{max(nums)} — {OUT.stat().st_size} octets"
    )


if __name__ == "__main__":
    main()
