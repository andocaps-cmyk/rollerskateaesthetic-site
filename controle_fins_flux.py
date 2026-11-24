#!/usr/bin/env python3
"""controle_fins_flux.py -- attrape la recidive de la « fin uniforme » des epingles Pinterest.

ERREUR QUI L'A FAIT NAITRE (22/10/2026) : le 18/10 la phrase de fin uniforme a ete retiree de 20 epingles
existantes, mais le generateur (site/build_feed.py, constante FIN_OBLIGATOIRE_PINTEREST) a continue de la coller
sur chaque epingle neuve jusqu'au 22/10 (corrige commit ed18cc0 : fin variable). On avait corrige la SORTIE, pas la SOURCE.

METHODE (simple, explicable) : pour chaque <item> du flux RSS, on prend la description (balises retirees,
entites decodees, espaces normalises) et ses N derniers caracteres (defaut 60 = --longueur). Si une meme queue de
N caracteres apparait sur plus de --seuil (defaut 30 %) des items : code 1. Une fin partagee de moins de N
caracteres (ex. « Made with AI. », 14 car.) ne peut pas declencher, car les N derniers caracteres incluent alors
du texte propre a l'epingle. Code 1 aussi si « nothing to buy » apparait dans une description (insensible a la casse).
Code 0 sinon ; code 2 si flux illisible ou sans item.

USAGE : controle_fins_flux.py FLUX.xml|URL [--seuil 0.30] [--longueur 60] [--depuis AAAA-MM-JJ]
        controle_fins_flux.py --texte "TEXTE A PUBLIER"   (code 1 si le texte porte « nothing to buy »)

29/10/2026 : « nothing to buy » est REFUSE PARTOUT, sur tous les items, y compris ceux d'avant --depuis
(feed_archive.xml a ete regenere sans la phrase ce jour-la), et dans tout texte passe par --texte.
publier_reseaux.py (Bluesky) et publier_threads.py importent INTERDIT d'ici : une seule regle.

BRANCHE LE 22/10/2026 dans .github/workflows/fournee.yml, juste apres la generation des flux. Deux corrections
faites au branchement, sur la mesure du flux reel :
 - une fin n'est « uniforme » que si au moins 2 items la partagent. Le flux du jour (build_feed.py --fenetre)
   ne porte souvent qu'UN item : 1/1 = 100 % rendait le controle rouge chaque jour, sur un flux sain.
 - --depuis AAAA-MM-JJ : ne lit que les items dont la pubDate est ce jour ou apres. feed_archive.xml (Flipboard)
   garde ses 162 anciens articles tels quels, tous avec l'ancienne fin ; on ne les reecrit pas, on controle
   seulement ce que le generateur ajoute depuis la correction de la source (22/10/2026). Zero item apres le
   filtre = rien a controler = vert (code 0), pas une erreur de lecture.

CE QUI LE RENDRAIT FAUX OU INUTILE : un flux ou la description n'est plus dans <description> (ex. content:encoded) ;
un changement de generateur qui colle la fin dans un autre champ (titre, lien).
CE QU'IL NE VOIT PAS : une fin commune de MOINS de N caracteres (volontairement) ; une fin « variable » mais
tiree d'un lot de 3 phrases (3 variantes sur 40 items = 33 % chacune -> passe en rouge seulement si > seuil) ;
une uniformite de DEBUT ou de milieu de description ; la distribution reelle par Pinterest (seul le flux est lu) ;
un flux de moins de 4 items (le pourcentage n'y veut rien dire : un avertissement est imprime).
"""
import argparse, collections, html, re, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

INTERDIT = re.compile(r"nothing\s+to\s+buy", re.I)


def charger(src):
    if re.match(r"https?://", src):
        with urllib.request.urlopen(src, timeout=30) as r:
            return r.read()
    with open(src, "rb") as f:
        return f.read()


def nettoyer(t):
    t = html.unescape(t or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("flux", nargs="?")
    ap.add_argument("--texte", help="controle un texte seul : code 1 s'il porte « nothing to buy »")
    ap.add_argument("--seuil", type=float, default=0.30)
    ap.add_argument("--longueur", type=int, default=60)
    ap.add_argument("--depuis", help="AAAA-MM-JJ : ne controler que les items publies ce jour ou apres")
    # 07/11/2026 : nombre minimal d'items qui partagent la meme queue pour passer en rouge (defaut 2 = comportement
    # d'avant). Ne le 06/11/2026, feed_archive.xml --depuis 2026-10-22 portait 6 items ; la rotation de 5 fins
    # de build_feed.py (FINS_QUIZ) a redonne la fin du 29/10 au 06/11, donc 2/6 = 33 % > 30 % : rouge sur un flux
    # sain (fournee rouge le 06/11 a 17 h 03 et 21 h 25 UTC, rien pousse). Avec 5 fins qui tournent, 2/7 = 29 % : la
    # meme mesure redevient verte au 7e item ; le rouge ne venait que de la petite taille de l'echantillon. Une fin
    # vraiment uniforme (le defaut du 22/10) donne 3 items identiques au 3e passage, attrape avec --minimum 3.
    ap.add_argument("--minimum", type=int, default=2,
                    help="nombre minimal d'items partageant la queue pour passer en rouge (defaut 2)")
    a = ap.parse_args()
    if a.texte is not None:
        if INTERDIT.search(a.texte):
            print("ROUGE : le texte porte « nothing to buy ».")
            return 1
        print("VERT : pas de « nothing to buy ».")
        return 0
    if not a.flux:
        ap.error("FLUX ou --texte requis")
    try:
        racine = ET.fromstring(charger(a.flux))
    except Exception as ex:
        print(f"ERREUR DE LECTURE : {ex}")
        return 2
    items = list(racine.iter("item"))
    tous = [nettoyer(i.findtext("description")) + " " + nettoyer(i.findtext("title")) for i in items]
    interdits = [k for k, d in enumerate(tous, 1) if INTERDIT.search(d)]
    if interdits:
        print(f"ROUGE : « nothing to buy » dans {len(interdits)} item(s) (toutes dates), items {interdits[:10]}"
              f"{'...' if len(interdits) > 10 else ''}.")
        return 1
    if a.depuis:
        borne = datetime.strptime(a.depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        garde = []
        for i in items:
            try:
                d = parsedate_to_datetime(i.findtext("pubDate"))
            except Exception:
                continue
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            if d >= borne:
                garde.append(i)
        print(f"--depuis {a.depuis} : {len(garde)} item(s) sur {len(items)} retenus.")
        if not garde:
            print("VERT : aucun item depuis cette date, rien a controler.")
            return 0
        items = garde
    # 25/10/2026 : un flux PURGE (0 item) est un etat voulu de build_feed.py (cadence : rien a
    # publier ce jour), pas un flux casse. La fournee du 25/10 (cf902f2) a echoue ici sur 0 item
    # et n'a pas pousse le flux purge. Un flux dont les items n'ont PAS de description reste rouge.
    if not items:
        print("VERT : flux vide (0 item), rien a controler.")
        return 0
    descs = [nettoyer(i.findtext("description")) for i in items]
    descs = [d for d in descs if d]
    if not descs:
        print("ERREUR : aucun item avec description")
        return 2
    n = len(descs)
    if n < 4:
        print(f"AVERTISSEMENT : {n} item(s) seulement, le pourcentage est peu parlant.")
    rouge = False
    queues = collections.Counter(d[-a.longueur:] for d in descs if len(d) >= a.longueur)
    if queues:
        queue, c = queues.most_common(1)[0]
        part = c / n
        print(f"{n} items ; queue la plus frequente ({a.longueur} car.) : {c}/{n} = {part:.0%} (seuil {a.seuil:.0%})")
        print(f"  queue : {queue!r}")
        if c >= max(2, a.minimum) and part > a.seuil:
            print(f"ROUGE : meme fin de {a.longueur}+ caracteres sur {part:.0%} des items (> {a.seuil:.0%}).")
            rouge = True
    nb = [i for i, d in enumerate(descs, 1) if INTERDIT.search(d)]
    if nb:
        print(f"ROUGE : « nothing to buy » dans {len(nb)} description(s), items {nb[:10]}{'...' if len(nb) > 10 else ''}.")
        rouge = True
    if not rouge:
        print("VERT : aucune fin uniforme, pas de « nothing to buy ».")
    return 1 if rouge else 0


if __name__ == "__main__":
    sys.exit(main())
