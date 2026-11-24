#!/usr/bin/env python3
"""
Génère site/feed.xml à partir des CSV de lots (lot 2 + lot 3).

Pourquoi un script et pas un feed écrit à la main :
un flux RSS ne sait PAS programmer à l'heure. Pinterest le relève sous 24 h et
publie tout ce qu'il y trouve (jusqu'à 200/jour, le plus ancien d'abord).
La cadence (2 épingles/jour jusqu'au 18/10/2026, puis 4 par semaine sur quatre jours
distincts, voir `CHANGEMENT_CADENCE`) se pilote donc en ne mettant dans le flux QUE ce
qu'on veut voir partir.

Usage :
    python3 build_feed.py            # les 2 premières épingles non encore publiées
    python3 build_feed.py 11 12      # ces épingles précisément
    python3 build_feed.py --all      # les 10 (à n'utiliser que si on assume la volée)
    python3 build_feed.py --fenetre  # LE MODE AUTONOME — voir plus bas

Après chaque exécution en mode manuel : redéployer le site, puis noter dans un document interne
les numéros passés dans PUBLIEES ci-dessous.

⭐ LE MODE `--fenetre`, AJOUTÉ LE 07/08/2026 — c'est lui que la GitHub Action appelle,
et il existe pour une raison précise : les trois autres modes ont besoin d'un humain.

Le problème qu'il résout : `PUBLIEES` se tient À LA MAIN, et elle ne s'incrémente
qu'après que quelqu'un a VU les épingles sur le compte public. Une tâche qui tourne
sans personne ne peut donc pas savoir où elle en est — elle republierait indéfiniment
les deux mêmes épingles.

Ce que fait `--fenetre` à la place : il ne tient AUCUN état. Le contenu du flux est
une fonction pure de la date du jour. Chaque épingle a un jour de sortie calculé une
fois pour toutes par `calendrier()` (deux par jour à partir de `DEPART_FENETRE` jusqu'au
18/10/2026, puis une par jour de sortie, quatre jours par semaine, à partir de
`CHANGEMENT_CADENCE`), et elle reste dans le flux pendant `JOURS_EN_VOL` jours.

Pourquoi deux jours et pas un : Pinterest relève le flux sous 24 h en théorie, mais la
relevée du 06/08 a pris ~28 h (voir les notes de `PUBLIEES`). Une épingle qui ne
resterait qu'un jour serait perdue à chaque fois que la relevée déborde. Deux jours
couvrent deux cycles de relevée. Le doublon est écarté par le `<guid>` stable de chaque
épingle, qui est exactement ce à quoi sert un guid en RSS 2.0.

Et les dates écrites dans le flux sont DÉTERMINISTES en mode fenêtre, pas `now` :
deux exécutions du même jour produisent un fichier identique à l'octet près, donc
`git commit` ne trouve rien, donc aucun déploiement inutile n'est déclenché.
"""

import csv
import re
import sys
from email.utils import format_datetime
from html import unescape
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

DOMAIN = "https://rollerskateaesthetic.com"
HERE = Path(__file__).resolve().parent
# Les DEUX CSV, dans l'ordre des lots. Le lot 2 y reste pour le controle d'unicite des liens :
# un lien du lot 3 qui doublerait un lien du lot 2 doit etre attrape ici, pas par un rejet Pinterest.
#
# Defaut du 04/08/2026, corrige ici : ce script ne lisait que le CSV du lot 2, dont les dix epingles
# sont toutes dans PUBLIEES. `choisir` renvoyait donc systematiquement une liste vide, le flux etait
# purge a chaque execution, et le compte n'a plus rien publie depuis le 02/08 a 18 h. Le lot 3
# n'avait jamais eu de CSV du tout.
#
# ⭐ CORRIGÉ LE 07/08/2026 : le chemin n'est plus figé sur `HERE.parent`, il se CHERCHE.
# Motif, et c'est ce qui bloquait la GitHub Action : dans le dossier de travail du propriétaire, ce
# script vit dans `site/` et les deux CSV sont un cran au-dessus, à la racine du projet ;
# dans le dépôt GitHub, le contenu de `site/` EST la racine, et il n'y a pas de cran
# au-dessus. Un chemin figé marchait donc à un seul des deux endroits.
CSV_NOMS = ["pinterest_lot2_bulk.csv", "pinterest_lot3_bulk.csv",
            "pinterest_lot4_bulk.csv", "pinterest_lot5_bulk.csv",
            "pinterest_lot6_bulk.csv", "pinterest_lot7_bulk.csv",
            "pinterest_lot8_bulk.csv", "pinterest_lot9_bulk.csv",
            "pinterest_lot10_bulk.csv", "pinterest_lot11_bulk.csv",
            "pinterest_lot12_bulk.csv", "pinterest_lot13_bulk.csv",
            "pinterest_lot14_bulk.csv", "pinterest_lot15_bulk.csv",
            "pinterest_lot16_bulk.csv", "pinterest_lot17_bulk.csv",
            "pinterest_lot18_bulk.csv", "pinterest_lot19_bulk.csv",
            "pinterest_lot20_bulk.csv", "pinterest_lot21_bulk.csv",
            "pinterest_lot22_bulk.csv", "pinterest_lot23_bulk.csv"]


def chemin_csv(nom: str) -> Path:
    for base in (HERE, HERE.parent):
        if (base / nom).is_file():
            return base / nom
    raise SystemExit(
        f"ERREUR : {nom} introuvable, ni dans {HERE} ni dans {HERE.parent} — "
        "le lot correspondant ne partirait jamais."
    )


CSV_PATHS = [chemin_csv(n) for n in CSV_NOMS]
OUT = HERE / "feed.xml"

# Épingles déjà parties — quel que soit le moyen. À tenir à jour à la main.
#
# Le lot 2 entier (11→20) y est depuis le 29/07 : il n'est pas passé par le flux mais par le
# dépôt CSV, qui a réussi. Le flux ne doit donc plus jamais le reprendre — il republierait en
# double des épingles déjà en ligne ou déjà programmées. Le flux sert au lot 3.
#
# 21 et 22 ajoutees le 05/08/2026 a 07 h 30 : VUES SUR LE COMPTE PUBLIC, en tete de
# `/rollerskateaesthetic/_created/` — « Inlines Are More Stable Than Quads » et « Your First Pads:
# You Need All Four ». Le compte est passe de 20 a 22 epingles rendues. C'est la premiere relevee
# reussie du flux RSS depuis son branchement le 04/08 : la chaine fonctionne de bout en bout.
#
# 23 et 24 ajoutees le 06/08/2026 a 14 h 40 : VUES SUR LE FLUX PUBLIC DU COMPTE
# (`pinterest.com/rollerskateaesthetic/feed.rss`, 200, 24 items) — « Skates That Hurt » et
# « Bearings: The Number on the Box Means Nothing », horodatees le 06/08 a 08 h 56 GMT, en tete du
# flux. Le compte est passe de 22 a 24 epingles. Deuxieme relevee reussie : la relevee du flux
# n'etait donc pas un coup de chance, mais elle a pris ~28 h, pas 24.
PUBLIEES: set[int] = set(range(11, 25))

# GARDE-FOU DE SENS — la regle de traduction du maitre §4 : le propriétaire ne lit pas l'anglais, donc aucune
# epingle ne part avant qu'il en ait vu le sens en francais. Ce n'est pas une autorisation, c'est un
# controle de contresens.
#
# Cette liste existe parce que le flux peut desormais etre lance par une tache programmee, SANS
# personne dans la conversation pour se souvenir de la regle. Une regle tenue par la memoire d'une
# session n'est pas une regle.
#
# 11 a 20 : lot 2, valide avant publication.
# 21, 22  : reecrites le 03/08 sur correction du propriétaire lui-meme — sa correction vaut validation.
# 23, 24  : validees par le propriétaire le 04/08. L'epingle 24 (roulements/ABEC) etait un sujet neuf.
# 25 a 30 : PAS ENCORE VUES PAR LUI. Ne rien y toucher avant.
#
# CE GARDE-FOU EST TEMPORAIRE, ET SON CRITERE DE SORTIE EST ECRIT DANS LE MAITRE §4.
# le propriétaire l'a pose le 04/08 : la traduction n'existe que le temps que un document interne se remplisse.
# Des qu'une epingle n'avance aucune affirmation roller que ce fichier ne couvre pas, elle entre
# ici sans passer par lui. Ce qui reste toujours a lui : la sensation physique, mur 4.
# 27 et 30 : AJOUTEES LE 05/08/2026 SANS REDEMANDER AU PROPRIETAIRE, et c'est le critere de sortie du
#            maitre §4 qui l'autorise — « chaque affirmation roller du texte est deja couverte par
#            un document interne ». Passage qui couvre quoi, comme la regle l'exige :
#              · 27 (roues) — §5 : « durete 78A a 85A pour l'exterieur, 95A et plus pour la piste »,
#                *« Je pense que c'est les bonnes »*, ET la raison (une roue dure transmet le grain,
#                une roue souple l'absorbe). Toutes les affirmations de l'epingle y sont.
#              · 30 (sac) — §5 : cle, lacets, pansements, gourde, chiffon, PLUS son propre ajout des
#                chaussures legeres ou tongs. Rien dans l'epingle qui ne vienne de lui.
#            L'ETAT affirmait que 25 a 30 n'avaient jamais ete vues par lui : c'etait FAUX, corrige.
# 25 : AJOUTEE LE 05/08/2026 — le propriétaire a valide le geste du depart en arriere (ecarter les TALONS puis
#      les rapprocher, regard par-dessus l'epaule). *« Ca va, c'est correct, c'est ce que tu dis. »*
#      C'etait la derniere affirmation de l'epingle que un document interne ne couvrait pas ; elle y est
#      desormais, au §5. Le delai de trois seances etait deja valide.
VALIDEES: set[int] = (set(range(11, 111)) | set(range(111, 118)) | set(range(118, 126))
                      | set(range(126, 136)) | set(range(136, 146))
                      | set(range(146, 156)) | set(range(156, 166))
                      | set(range(166, 176)) | set(range(176, 186))
                      | set(range(186, 196)) | set(range(196, 206))
                      | set(range(206, 216)) | set(range(216, 226)))
# 196 a 205 ajoutees le 28/09/2026 (lot 21, fabrique dans _a_publier_lot21/ par un agent Fable
# parallele, publie ensuite en un passage). MEME SOURCE : Asha Kirkby, ecole Skatefresh, certifiee ICP.
# Tout le lot est EN LIGNE. SUJET : CONSTRUIRE UNE SEANCE — decouper une figure et batir la seance
# dessus (196-198), avant de chausser (199), hors patins entre deux seances (200-203), fermer la
# seance (204-205). Deux resolutions ecrites dans un document interne § 2 : une seance, un geste
# (un document interne § 11, les exercices sont les morceaux d'UN geste) ; tout genou tendu est
# hors patins. Aucun mot medical (LEXIQUE_MEDICAL). Faits du propriétaire en tete des 196 et 204.
# 206 a 215 ajoutees le 28/09/2026 (fabriquees par un agent Fable parallele, publiees ensuite en un
# passage avec les lots 21 et 23). MEME SOURCE : Asha Kirkby, ecole Skatefresh, certifiee ICP. Tout
# le lot est EN LIGNE. SUJET DU LOT : LES VIRAGES EN LIGNE AU-DELA DES BASES — direction du genou
# (206, fait du propriétaire un document interne § 1 + coach), virages paralleles enchaines comme frein (207),
# niveaux des virages (208), propulsion en courbe (209), transitions et leur frustration (210, 211),
# three turn (212), rotation du haut du corps (213), mohawk comme entree du powerslide (214), flow
# (215). Resolutions ecrites dans un document interne § 2 et § 11 : aucun geste de cheville (le mot
# est absent), aucune comparaison en ligne/quad ; aucun mecanisme de virage que la source n'enonce pas.
# 216 a 225 ajoutees le 28/09/2026 (lot 23, fabrique en parallele des lots 21-22 par un agent Fable,
# publie dans le passage unique 21-22-23). SOURCE : Asha Kirkby, ecole Skatefresh (ICP), quatre videos.
# SUJET DU LOT : LE QUAD DEHORS — plus dur que la piste et ce que ca change (216-219), sols degrades
# (220-221), montee (222-223), le Turn Stop dehors (224), ou emmener ses quads (225). LES DIX EPINGLES
# S'ANNONCENT COMME DU QUAD. Le quad n'y est jamais dit stable (le propriétaire, un document interne § 1) ; le stop
# avant n'y est jamais un frein (le propriétaire, materiel § 18) ; aucun freinage en descente (le propriétaire, geste § 0).
# 186 a 195 ajoutees le 28/09/2026 (lot 20, fabrique dans _a_publier_lot20/ par un agent parallele, publie
# ensuite en un passage ; son un document interne n'a jamais ete ecrit, l'agent de reprise etant
# reste muet apres 02:18 UTC — controles refaits par l'agent de publication). MEME SOURCE : Asha Kirkby,
# ecole Skatefresh, certifiee ICP. Tout le lot est en EN LIGNE. SUJET DU LOT : LE MATERIEL ET SES REGLAGES —
# fermer ses patins et la sangle du haut (186-188, 195), deplacer ses platines : symptome, ordre, millimetres
# (189-191), grandes roues (192), rockering (193), premier jour sur de nouvelles platines (194).
# 156 a 165 ajoutees le 28/09/2026 par un agent lance depuis une session ouverte par le propriétaire, qui a
# fabrique le lot 17 en entier (bras, rester bas, transitions quad ; source Asha Kirkby).
# 146 a 155 ajoutees le 21/09/2026 par la tache `roller-fabrique-le-lot-suivant`, qui a
# fabrique le lot 16 en entier dans le meme passage (matiere, contenu, CSV, dix visuels,
# dix pages, planche contact regardee a la vignette). MEME SOURCE QUE LES LOTS 10 A 15 :
# Asha Kirkby, ecole Skatefresh, certifiee par l'Inline Certification Program. Tout le lot
# est en patin EN LIGNE.
# SUJET DU LOT : LA RUE ET LE COTE FAIBLE — les rails de tram (146-150), le virage parallele
# du cote faible (151-153), le prerequis du croisement (154), les hanches en arriere (155).
# ⛔ L'EPINGLE 149 TOUCHE AU SAUT : l'avis du propriétaire de `un document interne` § 8 (un saut est
# un choix, pas trop au debut, genoux en ressort) et celui de la source (la reception) sont
# portes ensemble, chacun attribue ; `build_csv_lot16.py` et `build_pages_lot16.py` refusent
# d'ecrire sans les deux.
# 136 a 145 ajoutees le 17/09/2026 par la tache `roller-fabrique-le-lot-suivant`, qui a
# fabrique le lot 15 en entier dans le meme passage (matiere, contenu, CSV, dix visuels,
# dix pages, planche contact regardee a la vignette et a la loupe). MEME SOURCE QUE LES
# LOTS 10 A 14 : Asha Kirkby, ecole Skatefresh, certifiee par l'Inline Certification
# Program. Tout le lot est en patin EN LIGNE.
# SUJET DU LOT : LE CORPS QUI PORTE LE PATIN — pronation et foulee, pieds et chevilles,
# cotes du corps et bas du dos, retour sur les patins apres une chute.
# ⛔ TROIS EPINGLES TOUCHENT A LA DOULEUR DU PIED (139, 140, 141) : le verdict du propriétaire de
# `un document interne` § 3 et § 12 (qualite du patin, ajustement, coque rigide) et
# celui de la source (muscle faible, tension laissee dans le pied) portent sur deux objets
# differents. L'epingle 139 porte les deux, chacun attribue, et `build_csv_lot15.py` comme
# `build_pages_lot15.py` refusent d'ecrire sans les deux.
# ⛔ AUCUNE EPINGLE NE PROMET DE SUPPRIMER UNE DOULEUR, et 145 renvoie en clair a un
# professionnel pour une douleur qui dure. Les deux scripts le verifient.
# 126 a 135 ajoutees le 15/09/2026 par la tache `roller-fabrique-le-lot-suivant`, qui a
# fabrique le lot 14 en entier dans le meme passage (matiere, contenu, CSV, dix visuels,
# dix pages, planche contact regardee a la vignette et a la loupe). MEME SOURCE QUE LES
# LOTS 10 A 13 : Asha Kirkby, ecole Skatefresh, certifiee par l'Inline Certification
# Program. Tout le lot est en patin EN LIGNE.
# ⛔⛔ SUJET DU LOT : LE CONTROLE DE LA VITESSE EN DESCENTE, et c'est le seul lot du compte
# qui touche a un sujet ou LE PROPRIETAIRE FAIT AUTORITE ET DIT L'INVERSE DE LA SOURCE SUR UN POINT.
# `un document interne` § 0 (04/08/2026) : dans une vraie descente on ne freine pas, on
# assume — et il interdit « toute epingle qui conseille de freiner pour gerer une
# descente ». La source, elle, enseigne les arrets de pente. LA RESOLUTION, ECRITE EN TETE
# DE `un document interne` ET VERIFIEE PAR SCRIPT : chacune des dix epingles ET chacune des
# dix pages porte la clause de Cass — une pente dont on doute qu'on puisse s'y arreter se
# descend en l'assumant, elle ne se freine pas. `build_csv_lot14.py` et
# `build_pages_lot14.py` refusent tous deux d'ecrire si une seule ne la porte pas. La
# source dit d'ailleurs la meme chose de son cote : « slopes should be avoided until you
# absolutely know that your methods are trustable ».
# ⛔ UNE SEULE EPINGLE TOUCHE AU FREIN AU TALON (129) et porte donc les DEUX avis, chacun
# attribue a sa source — verdict du propriétaire du 10/09/2026, `un document interne` § 11. Les
# deux scripts le verifient, et verifient aussi l'inverse : hors de 129, aucune epingle ni
# page du lot ne nomme le frein au talon. Le motif a ete corrige en `heel[\s-]*brake` : un
# "heel-brake" avec trait d'union passait a travers le motif du lot 13.
# ⛔ CE QUI TIENT LIEU DE CONTROLE DE SENS : la meme conduite qu'aux lots 8 a 13, choisie
# par le propriétaire le 22/08/2026 en connaissance du cout — « la tache continue seule ». Aucune
# affirmation du lot ne sort de ce que les fichiers SAVOIR_ROLLER couvrent ou de ce que la
# source certifiee dit du patin en ligne. Les passages a la premiere personne ne reprennent
# QUE des faits deja ecrits (elle freine en T, 08/08/2026 ; le frein au talon pas assez
# puissant, douloureux au tibia non entraine, genant dans les croisements, retire,
# 10/09/2026 ; on assume une vraie descente, 04/08/2026) : aucune sensation n'est inventee.
# 118 a 125 ajoutees le 14/09/2026 par la tache `roller-fabrique-le-lot-suivant`, qui a
# TERMINE le lot 13 commence par son propre passage du 13/09/2026 et laisse inacheve (matiere,
# contenu et script de CSV ecrits, aucun visuel, aucune page, aucun envoi). MEME SOURCE QUE LES
# LOTS 10, 11 ET 12 : Asha Kirkby, ecole Skatefresh, certifiee par l'Inline Certification
# Program. Tout le lot est en patin EN LIGNE.
# ⛔ TROIS EPINGLES TOUCHENT AU FREIN AU TALON (121, 122, 123) et portent donc les DEUX avis,
# chacun attribue a sa source — verdict du propriétaire du 10/09/2026, `un document interne` § 11.
# `build_csv_lot13.py` et `build_pages_lot13.py` refusent tous deux d'ecrire si l'un des deux
# avis manque a l'une des trois, ET si le frein au talon apparait hors de ces trois.
# ⛔ CE QUI TIENT LIEU DE CONTROLE DE SENS : la meme conduite qu'aux lots 8 a 12, choisie par
# le propriétaire le 22/08/2026 en connaissance du cout — « la tache continue seule ». Aucune affirmation
# du lot ne sort de ce que les fichiers SAVOIR_ROLLER couvrent ou de ce que la source certifiee
# dit du patin en ligne. Les passages a la premiere personne ne reprennent QUE des faits deja
# ecrits (elle freine en T, verdict du 08/08/2026 ; le frein au talon pas assez puissant,
# douloureux au tibia non entraine, genant dans les croisements, retire, 10/09/2026) : aucune
# sensation n'est inventee, ce que le mur 4 interdit.
# ⛔ AUCUNE RECONNAISSANCE CHIFFREE NE PART, controle par les deux scripts du lot.
# 111 a 117 ajoutees le 13/09/2026, session Cowork, a la place de la tache locale
# `roller-fabrique-le-lot-suivant` qui ne tourne plus (planificateur Windows mort depuis
# plusieurs jours — c'est le motif meme de cette session). MEME SOURCE QUE LES LOTS 10 ET
# 11 : Asha Kirkby, ecole Skatefresh, certifiee par l'Inline Certification Program — sauf
# 116, sa propre video QUAD, annoncee comme telle.
# ⛔⛔ CE LOT DEBLOQUE LE FREIN AU TALON, GELE DEPUIS LE 22/08/2026 : le propriétaire a tranche le
# 10/09/2026 (`un document interne` § 11) qu'une epingle qui en parle publie DEUX avis,
# jamais l'un sans l'autre — la matiere certifiee d'Asha Kirkby ET l'experience personnelle
# de Cass (nom de scene du propriétaire, `un document interne` § 6bis). `build_csv_lot12.py` et
# `build_pages_lot12.py` refusent tous deux d'ecrire si 111, 112 ou 113 ne portait que l'un
# des deux avis.
# ⛔ LE CONTROLE DE SENS ICI EST DIFFERENT DE CELUI DES LOTS 91-110 : l'epingle 111 cite
# directement le propriétaire (sous le nom de Cass) et il a relu ET VALIDE la traduction francaise le
# 13/09/2026, sans y demander de correction — ce n'est pas seulement la rarete de la
# matiere qui en tient lieu ici, c'est une lecture reelle. 112 et 113 portent la meme
# condition en note courte et n'ont pas ete relues separement, comme les lots precedents.
# 101 a 110 ajoutees le 31/08/2026 par la tache `roller-fabrique-le-lot-suivant`. MEME SOURCE
# ET MEME DISCIPLINE QUE LE LOT 10 : Asha Kirkby, ecole Skatefresh, certifiee par l'Inline
# Certification Program, qui enseigne le patin EN LIGNE — la discipline ou porte l'autorite
# du propriétaire.
# ⛔ CE QUI TIENT LIEU DE CONTROLE DE SENS ICI est la meme conduite qu'au lot 10, choisie par
# le propriétaire le 22/08/2026 en connaissance du cout : « la tache continue seule ». La regle qui la
# porte est dans un document interne, § « une page publiee sans le propriétaire n'a pas besoin de sa
# sensation » — la rarete de la matiere satisfait la regle a la place.
# ⛔⛔ ET UNE QUESTION EST OUVERTE POUR LE PROPRIETAIRE, ECRITE DANS un document interne LE MEME JOUR : cette source
# enseigne que le frein au talon est le PREMIER frein que tout patineur en ligne devrait
# apprendre, ce qui contredit frontalement son verdict du 08/08/2026 selon lequel il freine en
# T. Aucune des dix epingles de ce lot ne touche au freinage, et quatre videos de la source
# sont gelees. Les controles de build_csv_lot11.py et build_pages_lot11.py refusent d'ecrire
# si une epingle ou une page y revenait.
# ⛔ AUCUNE RECONNAISSANCE CHIFFREE NE PART, et le lot 11 en apporte une preuve nouvelle : les
# nombres que la source donne d'elle-meme se CONTREDISENT d'une video a l'autre — la pratique
# annoncee a trente-six ans dans une description et a quarante-trois dans une autre.
# 91 a 100 ajoutees le 24/08/2026 par la tache `roller-fabrique-le-lot-suivant`. ⭐ CE LOT
# CHANGE DE SOURCE ET DE DISCIPLINE, et c'est le premier depuis le lot 6 dans ce cas : la
# matiere vient d'Asha Kirkby, ecole Skatefresh, certifiee par l'Inline Certification
# Program, qui enseigne le patin EN LIGNE. Les lots 7, 8 et 9 venaient d'une championne de
# QUAD et devaient etre annonces comme tels parce que l'autorite du propriétaire porte sur l'en ligne ;
# ce lot-ci rencontre son autorite au lieu de l'eviter.
# ⛔ CE QUI TIENT LIEU DE CONTROLE DE SENS ICI, ET IL FAUT ETRE PRECIS : ce n'est pas le propriétaire, qui
# n'a rien relu. C'est la conduite qu'il a lui-meme choisie le 22/08/2026, en connaissance du
# cout, quand trois options lui ont ete soumises et qu'il a pris « la tache continue seule ».
# La regle qui la porte est dans un document interne, § « une page publiee sans le propriétaire n'a
# pas besoin de sa sensation » : la rarete de la matiere satisfait la regle a la place.
# ⛔ ET DEUX CONTROLES SONT ECRITS DANS build_csv_lot10.py ET build_pages_lot10.py, qui
# refusent d'ecrire si l'un d'eux tombe :
#   · aucune reconnaissance CHIFFREE ne part — ni anciennete, ni rang, ni nombre d'eleves. Ce
#     qui est verifie dehors sur le site de l'ICP est une certification, sans decompte.
#   · aucune epingle et aucune page ne touche au FREINAGE AU TAMPON, dont le verdict du propriétaire
#     est toujours en attente. Le controle existe parce que la source enseigne aussi le frein
#     au talon : le gel doit tenir sans que personne ait a s'en souvenir.
# ⛔ RIEN DE CE LOT N'ENTRE DANS LES FICHIERS SAVOIR_ROLLER COMME UN FAIT ACQUIS : ce sont des
# affirmations sourcees et attribuees, pas des faits du propriétaire.
# 81 a 90 ajoutees le 22/08/2026 par la tache `roller-fabrique-le-lot-suivant`. MEME SOURCE ET
# MEME CONDITION QUE LES LOTS 7 ET 8 : Najete Kada, videos 12, 15, 16 et 17 de la serie
# « Tuto roller », qui enseigne le patin QUAD. le propriétaire patine EN LIGNE, donc son autorite ne
# couvre pas cette matiere et le controle de sens de `savoir-roller` ne s'y applique pas. Ce
# qui en tient lieu est la CONDITION qu'il a posee le 20/08/2026 : la publication est
# autorisee a condition d'etre annoncee comme du quad. Les dix descriptions nomment la source
# et annoncent le quad, les dix pages aussi, et `build_csv_lot9.py` refuse d'ecrire le CSV si
# l'un des deux faits manque a une seule epingle.
# ⛔ ET IL AJOUTE UN CONTROLE QUE LE LOT 8 N'AVAIT PAS : aucune description et aucune page ne
# peut porter un palmares CHIFFRE. La reconnaissance constatee dehors porte sur le titre
# — championne de France de roller artistique — jamais sur un nombre de titres.
# ⚠ AUCUNE EPINGLE DE CE LOT NE TOUCHE AU FREINAGE, ce qui evite le seul verdict du propriétaire encore
# en attente : la position du frein d'un quad, a l'avant, ne se transpose pas a un patin en
# ligne, et rien sur le freinage au tampon ne se publie avant qu'il ait tranche.
# 71 a 80 ajoutees le 22/08/2026, session 100. MEME SOURCE ET MEME CONDITION QUE LE LOT 7 :
# Najete Kada, videos 8 a 13 de la serie « Tuto roller », qui enseigne le patin QUAD. le propriétaire
# patine EN LIGNE, donc son autorite ne couvre pas cette matiere et le controle de sens de
# `savoir-roller` ne s'y applique pas. Ce qui en tient lieu est la CONDITION qu'il a posee le
# 20/08/2026 : la publication est autorisee a condition d'etre annoncee comme du quad. Les dix
# descriptions nomment la source et annoncent le quad, les dix pages aussi, et
# `build_csv_lot8.py` refuse d'ecrire le CSV si l'un des deux faits manque a une seule epingle.
# ⛔ L'epingle 79 — le moonwalk — previent en plus nommement les patineurs en ligne : le pas
# repose sur un frein place a l'AVANT du patin, donc il n'existe pas sous cette forme chez eux.
# ⛔ Rien de ce lot n'entre dans les fichiers SAVOIR_ROLLER comme un fait acquis.
# 61 a 70 ajoutees le 22/08/2026, session 96. ⚠ SECOND LOT DONT LA SOURCE N'EST PAS LE PROPRIETAIRE, et
# le premier dont la source est une ENSEIGNANTE exterieure : Najete Kada, serie « Tuto roller »
# de la chaine Sladesofficial, qui enseigne le patin QUAD. le propriétaire patine EN LIGNE, donc son
# autorite ne couvre pas cette matiere et le controle de sens de `savoir-roller` ne s'y
# applique pas. Ce qui en tient lieu est la CONDITION qu'il a posee le 20/08/2026 : la
# publication est autorisee a condition d'etre annoncee comme du quad. Les dix descriptions
# nomment la source et annoncent le quad, les dix pages aussi, et `build_csv_lot7.py` refuse
# d'ecrire le CSV si l'un des deux faits manque a une seule epingle.
# ⛔ Rien de ce lot n'entre dans les fichiers SAVOIR_ROLLER comme un fait acquis.
# 51 a 60 ajoutees le 14/08/2026, session 81. ⚠ CE LOT EST LE SEUL DONT LA SOURCE N'EST PAS
# LE PROPRIETAIRE : il porte sur l'ENTRETIEN, le seul sujet ou il a dit ne pas etre cale et ou il a
# explicitement autorise des sources exterieures. Le controle de sens de la competence
# `savoir-roller` ne s'applique donc pas de la meme facon — c'est la verification des
# sources qui en tient lieu, et elles sont listees dans un document interne. Trois exceptions
# portent bien son verdict du 08/08 : 58 (il patine EN LIGNE), 59 (il freine EN T),
# 60 (son chausson est en SYNTHETIQUE).
# 41 a 50 ajoutees le 07/08/2026, session 68. Les dix sortent de deux recoltes menees
# aupres du propriétaire le meme jour — la ville (`un document interne` § 16) et la pluie
# avec le sol mouille (§ 17). Elles ne demandent donc PAS de controle de sens supplementaire :
# le critere de sortie de la competence `savoir-roller` en dispense quand chaque affirmation
# du texte vient de lui, et ici aucune ne vient d'ailleurs.
# 26 et 28 ajoutees le 06/08/2026, session 53, APRES controle de sens du propriétaire sur le francais des
# deux textes, fait dans la conversation. Sa reponse : les deux passent. Ce qui lui a ete montre
# et pourquoi : pour la 26, la phrase « les croises viennent apres, jamais avant », seul enonce du
# texte qui ne soit couvert par aucun fait de un document interne ; pour la 28, l'inversion du sens
# de circulation en cours de seance et la main levee a l'entree, qui viennent de sources
# exterieures et non de lui.
#
# 29 ajoutee le meme jour SANS controle de sens du propriétaire, et c'est regulier :
# la regle du critere de sortie (competence savoir-roller, §7) dispense du controle quand chaque
# affirmation roller du texte est deja couverte par un document interne. C'est le cas ici, verifie
# ligne a ligne en session 52 : « un geste par sceance » et « on passe a la suite quand c'est
# automatique » viennent du §11, et les trois gestes nommes aussi. Le controle de sens existe
# parce qu'le propriétaire ne lit pas l'anglais ; il n'a rien a arbitrer sur un texte qui ne dit que ce
# qu'il a deja etabli.
# 166 a 175 ajoutees le 28/09/2026 (fabriquees en parallele, publiees dans le passage unique 18-19-20).
# SUJET DU LOT : LE QUAD EN PISTE — le stop avant comme point d'appui immobile (166-168, [le propriétaire]
# un document interne § 18), premiers pas de danse (169-171), premier spin (172-174),
# Crazy Legs (175) ; source 169-175 : Asha Kirkby, Skatefresh (ICP), tutoriels quad. LES DIX
# EPINGLES S'ANNONCENT COMME DU QUAD. Aucune ne presente le stop avant comme un frein.
# 176 a 185 ajoutees le 28/09/2026 (fabriquees par un agent Fable parallele, publiees ensuite en un
# passage). MEME SOURCE : Asha Kirkby, ecole Skatefresh, certifiee ICP. Tout le lot est en EN LIGNE.
# SUJET DU LOT : LES CARRES EN LIGNE — ce qu'elles sont (176, 177), la carre exterieure (178),
# leur effondrement a la fatigue sur la distance (179-182), les quatre defauts (183, 185), deux
# pieds au sol avant un (184, fait du propriétaire, un document interne § 11). Deux resolutions ecrites
# dans un document interne § 2 : aucun geste de cheville (un document interne § 1), aucune comparaison
# en ligne/quad.

# Le <link> se lit dans la colonne `Link` du CSV — une page /skate/<slug>/ par épingle.
#
# Il ne se calcule PLUS depuis une table d'ancres. L'ancienne table faisait pointer 11, 12 et 13
# sur `https://rollerskateaesthetic.com/#first` : trois liens identiques pour Pinterest, qui ne
# distingue pas deux URL par leur fragment. C'est exactement ce qui a fait rejeter 4 lignes du
# dépôt CSV du 28/07 (`Duplicate Pin link`), et le flux aurait refait la même faute.
#
# Deux contraintes, toutes deux satisfaites par la colonne `Link` :
#   - le lien doit être sous le domaine revendiqué, sinon Pinterest rejette le flux entier
#     (« Links in the RSS feed are not under the claimed domain ») ;
#   - il doit être unique d'une épingle à l'autre, fragment non compris.


# ── Les trois constantes du mode `--fenetre`. Elles se règlent ici et nulle part ailleurs. ──
#
# DEPART_FENETRE est le jour de sortie des DEUX PREMIÈRES épingles encore à publier, dans
# l'ordre de leur numéro. Il est fixé au 06/08/2026 pour une raison de continuité, et pas
# par commodité : le flux servi par le domaine ce jour-là portait déjà 25 et 27, et un
# départ plus tardif les aurait fait disparaître du flux avant que Pinterest ne les relève.
# Avec cette valeur, le premier passage de l'Action ajoute 26 et 28 sans rien retirer.
#
# ⚠ NE PAS DÉPLACER CETTE DATE APRÈS COUP. Tout le calendrier de sortie en découle : la
# reculer republierait des épingles déjà parties, l'avancer en sauterait.
#
# ⛔⛔ ET LE PIÈGE À CONNAÎTRE AVANT DE TOUCHER À `PUBLIEES` : en mode `--fenetre`, elle est
# GELÉE. Le calendrier est calculé sur la liste des épingles validées qui n'y sont pas, dans
# l'ordre de leur numéro. Ajouter 25 à 30 dans `PUBLIEES` au fur et à mesure qu'elles sortent
# — le geste qui était juste en mode manuel — décalerait tout le calendrier d'un cran à chaque
# fois et republierait sans fin les mêmes épingles.
#
# ➡️ LA MANŒUVRE CORRECTE LE JOUR OÙ DES ÉPINGLES 31 ET SUIVANTES ARRIVENT, et elle se fait
# d'un seul geste : porter 25 à 30 dans `PUBLIEES`, ajouter les nouvelles à `VALIDEES`, ET
# régler `DEPART_FENETRE` sur le jour où la nouvelle série doit commencer à sortir. Les trois
# ensemble ou aucun des trois.
DEPART_FENETRE = date(2026, 8, 6)
# ⛔ CADENCE CHANGEE LE 18/10/2026 (Claude Code, prompt « nettoyage et cadence Pinterest »).
# Jusqu'au 18/10/2026 inclus : 2 epingles par jour, 7 jours sur 7, soit 14 par semaine. A partir
# du 19/10/2026 : UNE epingle par jour de sortie, quatre jours de sortie par semaine (lundi,
# mardi, jeudi, vendredi), soit 4 par semaine. Motif, mesure : la courbe d'impressions du compte
# est tombee a zero le 23-24/09/2026 et y reste ; le conseil exterieur pour un compte neuf est de
# 3 a 5 par semaine (`un document interne` § 2) ; decision du propriétaire le 18/10 : « on publie
# quatre fois trop ». Consequence assumee : l'arriere (53 epingles au 18/10) met trois fois et
# demie plus longtemps a s'ecouler. C'est l'effet recherche.
#
# COMMENT LE CHANGEMENT PRESERVE LE RESERVOIR, et c'est la partie delicate :
#   - les 2 x 74 = 148 premieres epingles de la file (n° 25 a 172) gardent EXACTEMENT la date que
#     l'ancienne formule leur donnait (DEPART_FENETRE + indice // 2) : rien de deja sorti ne
#     ressort, rien n'est saute ;
#   - les suivantes (n° 173 et au-dela) prennent, dans l'ordre, les jours de sortie a partir de
#     CHANGEMENT_CADENCE, un numero par jour de sortie ;
#   - `calendrier()` est la SEULE formule, et `build_feed_archive.py` la lit au lieu de la recopier.
# Preuve prise le 18/10/2026 en deroulant `fenetre()` jour par jour sur tout l'horizon : meme
# ensemble que la file, aucun doublon, aucun trou (voir la documentation du projet).
PAR_JOUR_AVANT_CHANGEMENT = 2
CHANGEMENT_CADENCE = date(2026, 10, 19)          # un lundi
JOURS_DE_SORTIE = (0, 1, 3, 4)                   # lundi, mardi, jeudi, vendredi (date.weekday())
JOURS_EN_VOL = 2

# ⭐ REPRISES — quatre epingles sorties au flux (53 et 54 le 20/08/2026, 67 et 68 le 27/08/2026)
# que Pinterest n'a JAMAIS creees : aucun identifiant sur le compte au releve du 18/10/2026, alors
# que leurs pages existent (`un document interne` § 1, releve
# `RELEVE_EPINGLES.csv`). Elles repassent dans le flux EN TETE de la nouvelle file, une par jour de
# sortie, donc sur quatre jours distincts, et elles prennent la place de quatre epingles : elles
# passent DANS la cadence de quatre par semaine, pas a cote. Leur <guid> porte un suffixe : un
# lecteur RSS (Pinterest compris) tient un item deja vu par son guid, et ces quatre guids ont deja
# ete servis en aout. Le catalogue Flipboard (`build_feed_archive.py`) ne les reprend PAS : il les
# porte deja depuis aout sous leur guid d'origine.
#
# 122 et 126 AJOUTEES LE 18/10/2026 AU SOIR, pour une autre raison : le retrait des doublons (geste ②
# du meme prompt) a supprime UN exemplaire de chaque paire identique, et pour les deux paires creees a
# UNE SECONDE d'ecart (24/09 et 26/09/2026, `no-single-stop-works-everywhere` et
# `one-trustable-flat-stop-before-any-slope`) Pinterest a retire LES DEUX : la jumelle conservee
# repond 404 et n'est plus dans aucun tableau. Les quatre paires du 29/08 (55 s d'ecart) ont garde
# leur jumelle. Ces deux pages n'ont donc plus d'epingle ; elles repassent par le flux comme les
# quatre autres. Registre : `REGISTRE_ECRITURES_PINTEREST.tsv`, 18:54:27 et 18:54:33.
REPRISES: list[int] = [53, 54, 67, 68, 122, 126]
SUFFIXE_REPRISE = "-reprise-2026-10"

# ⭐ APPEL AU GUIDE GRATUIT DANS CHAQUE DESCRIPTION — decide par le propriétaire le 14/09/2026.
#
# LE MOTIF EST UNE MESURE, PAS UNE INTUITION : 2,2 k vues mensuelles sur le profil Pinterest
# (lues le 14/09/2026) contre UN SEUL clic sortant Pinterest -> site sur trente jours
# (22/07-21/08, `un document interne` § 2). Le goulot n'est donc pas le nombre de vues, c'est le clic.
# Rien dans une epingle ne disait au lecteur ce qu'il y a de l'autre cote du lien.
#
# Cette ligne le dit. Elle est vraie : la page d'accueil du site EST le guide complet, elle
# est publique, sans inscription et sans rien a acheter.
#
# ⛔ ELLE S'AJOUTE ICI ET NULLE PART AILLEURS. `item()` est le seul entonnoir par lequel
# passe toute epingle ingeree par Pinterest — flux du jour compris. Ecrire cette ligne a la
# main dans un CSV la ferait vivre le temps d'un lot, et le lot suivant naitrait sans elle.
#
# HISTORIQUE DES DECISIONS DU PROPRIETAIRE SUR CETTE FIN, A GARDER :
#   - 14/09/2026 : un appel au guide gratuit dans chaque description (motif ci-dessus) ;
#   - 16/09/2026 : chaque publication porte la mention d'IA, sur Pinterest aussi ;
#   - 27/09/2026 : le guide passe AVANT la mention d'IA, parce que l'etiquette IA fait baisser
#     l'envie de cliquer et ne doit pas etre la derniere chose lue avant l'appel au clic ; « from
#     a skater's notes » rendait la part humaine que l'etiquette fait perdre.
# Ces trois decisions donnaient une phrase FIXE de 115 caracteres, la meme sur toutes les epingles :
#   " Free beginner's guide, no sign-up, nothing to buy: rollerskateaesthetic.com. Written with AI from a skater's notes."
#
# ⛔ RETIREE LE 22/10/2026 (Claude Code, prompt « relance de la vente »), pour deux raisons :
#   1. elle est la cause la plus probable de l'arret de distribution du 23-24/09/2026 (2 495 vues
#      mensuelles le 29/09, 688 le 22/10 ; 0 impression sur 155 epingles de la serie API). Pinterest
#      nomme ce motif dans ses regles communautaires : du contenu repetitif « in an attempt to make
#      money » (`un document interne` § 5, entree du 18/10) ;
#   2. « nothing to buy » contredisait l'objectif pose par le propriétaire le 22/10/2026 : au moins 100 € de
#      ventes Amazon avant le 31/10/2026.
# A LA PLACE, `fin_epingle()` tire la fin de la PAGE DE DESTINATION elle-meme : elle dit ce que le
# lecteur y trouve (le guide d'achat lie, les produits, le quiz), en trois formulations au moins par
# cas, choisies par le numero de l'epingle — deterministe, donc le flux reste identique a l'octet
# pres d'un passage a l'autre. La mention d'IA reste, sous sa forme la plus courte.
# Les 20 epingles « modifiees » et les 20 « temoins » de `EPREUVE_UNIFORMITE_2026-10-18.tsv` sont
# deja sur le compte : ce changement ne les touche pas (il ne vaut que pour les items du flux).
APPEL_GUIDE = " Free guide on the site, no sign-up."   # ancien appel, garde pour l'historique, plus utilise
MENTION_IA = " Made with AI."

# {g} = texte du lien vers le guide d'achat, tel qu'il est ecrit sur la page.
FINS_AMAZON = (
    "What to get for it is on the page.",
    "The gear that goes with it is listed on the page.",
    "The page shows what to buy for it.",
)
FINS_GUIDE = (
    "Gear for it on the page: {g}",
    "Linked on the page: {g}",
    "What to get for it, on the page: {g}",
)
# Cinq et non trois : plus de la moitie des epingles en attente au 22/10/2026 menent au quiz.
FINS_QUIZ = (
    "Still choosing skates? The page links a five-question quiz.",
    "On the page: a five-question quiz to pick your skates.",
    "The page links a quiz that matches you to the right skates.",
    "Not sure which skates to buy? There is a short quiz on the page.",
    "Five questions on the page tell you which skates fit how you ride.",
)
# Page sans lien d'achat ni quiz : la fin reprend son titre (h1).
FINS_PAGE = (
    "On the page: {t}.",
    "The full page: {t}.",
    "More on the page: {t}.",
)

# 29/10/2026 (prompt un document interne) : une page qui porte un lien
# Amazon le dit dans la fin de l'epingle, en trois formulations tirees par le numero de l'epingle
# (decalees de FINS_AMAZON pour ne pas former de couples fixes). Regle du propriétaire du 16/09/2026 : la
# mention d'IA et la mention d'affiliation ne se retirent jamais.
MENTIONS_AFFILIATION = (
    " This page contains affiliate links.",
    " Some links on this page are affiliate links.",
    " The page includes affiliate links.",
)

LIEN_GUIDE = re.compile(r'<!-- lien-guide -->\s*<div class="gear-note">.*?<a href="([^"]+)">(.*?)</a>', re.S)


def fin_epingle(n: int, lien: str) -> str:
    """La fin de description de l'epingle `n`, tiree de sa page de destination (voir plus haut)."""
    chemin = HERE / lien[len(DOMAIN):].strip("/") / "index.html"
    if not chemin.is_file():
        raise SystemExit(f"ERREUR épingle {n} : page de destination {chemin} absente du dépôt.")
    html = chemin.read_text(encoding="utf-8")
    if re.search(r"tag=(rollerskateae|rskatext|rskacart|rskakit)-20", html):   # 25/10/2026 : trois identifiants par emplacement
        phrase = FINS_AMAZON[n % len(FINS_AMAZON)] + MENTIONS_AFFILIATION[(n // 3) % len(MENTIONS_AFFILIATION)]
    elif (m := LIEN_GUIDE.search(html)) and "/guide/" in m.group(1):
        texte = unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip().rstrip(".")
        phrase = FINS_GUIDE[n % len(FINS_GUIDE)].format(g=texte)
        if phrase[-1] not in "?!":   # un titre de guide finit parfois par « ? »
            phrase += "."
    elif m and "/tools/skate-quiz/" in m.group(1):
        phrase = FINS_QUIZ[n % len(FINS_QUIZ)]
    else:
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        titre = unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip().rstrip(".") if h1 else ""
        if not titre:
            raise SystemExit(f"ERREUR épingle {n} : ni lien d'achat, ni quiz, ni h1 sur {chemin}.")
        phrase = FINS_PAGE[n % len(FINS_PAGE)].format(t=titre)
    return " " + phrase + MENTION_IA


def couper_a_la_phrase(texte: str, maxi: int) -> str:
    """Coupe a la fin de la derniere phrase entiere qui tient dans `maxi` caracteres."""
    if len(texte) <= maxi:
        return texte
    court = texte[:maxi]
    fin = max(court.rfind(". "), court.rfind("! "), court.rfind("? "))
    if fin == -1:
        fin = court.rfind(" ")
        return court[:fin].rstrip(",;:") + "."
    return court[:fin + 1]


# Epingles dont la description etait deja trop longue pour recevoir l'appel : `main()` les
# nomme en fin de passage. Ce n'est pas une erreur bloquante, c'est une dette a payer en
# raccourcissant ces descriptions-la.
SANS_APPEL: list[int] = []


def numero(media_url: str) -> int:
    m = re.search(r"pin_(\d+)_", media_url)
    if not m:
        raise ValueError(f"numéro d'épingle introuvable dans {media_url!r}")
    return int(m.group(1))


def fichier(media_url: str) -> str:
    return media_url.rsplit("/", 1)[-1]


def lire_csv() -> list[dict]:
    lignes: list[dict] = []
    for chemin in CSV_PATHS:
        if not chemin.is_file():
            raise SystemExit(f"ERREUR : {chemin} absent — le lot correspondant ne partirait jamais.")
        with chemin.open(encoding="utf-8-sig", newline="") as f:
            lignes += [r for r in csv.DictReader(f) if r.get("Media URL")]
    for r in lignes:
        r["_n"] = numero(r["Media URL"])
        r["_png"] = fichier(r["Media URL"])
    return sorted(lignes, key=lambda r: r["_n"])


def jours_de_sortie(depuis: date):
    """Les jours de sortie de la nouvelle cadence, dans l'ordre, a partir de `depuis` inclus."""
    j = depuis
    while True:
        if j.weekday() in JOURS_DE_SORTIE:
            yield j
        j += timedelta(days=1)


def calendrier(lignes: list[dict]) -> list[tuple[dict, date, str]]:
    """LA formule du calendrier de sortie. Fonction pure de la liste des epingles.

    Rend, dans l'ordre de sortie, des triplets (epingle, jour de sortie, guid). Chaque epingle
    validee et non encore dans `PUBLIEES` y figure exactement une fois sous son guid d'origine ;
    chaque numero de `REPRISES` y figure une seconde fois, sous un guid suffixe, dans la file de
    la nouvelle cadence. `build_feed_archive.py` lit cette fonction : la regle vit ici et nulle
    part ailleurs.
    """
    ordre = [r for r in lignes if r["_n"] in VALIDEES and r["_n"] not in PUBLIEES]
    par_numero = {r["_n"]: r for r in ordre}
    n_avant = PAR_JOUR_AVANT_CHANGEMENT * (CHANGEMENT_CADENCE - DEPART_FENETRE).days
    plan: list[tuple[dict, date, str]] = []
    # Ancienne cadence, inchangee : indice // 2 jours apres le depart, jusqu'a la veille du changement.
    for i, r in enumerate(ordre[:n_avant]):
        plan.append((r, DEPART_FENETRE + timedelta(days=i // PAR_JOUR_AVANT_CHANGEMENT),
                     f"rollerskateaesthetic-pin-{r['_n']}"))
    # Nouvelle cadence : les reprises d'abord, puis la suite de la file, un numero par jour de sortie.
    file = [(par_numero[n], f"rollerskateaesthetic-pin-{n}{SUFFIXE_REPRISE}")
            for n in REPRISES if n in par_numero]
    file += [(r, f"rollerskateaesthetic-pin-{r['_n']}") for r in ordre[n_avant:]]
    for (r, guid), jour in zip(file, jours_de_sortie(CHANGEMENT_CADENCE)):
        plan.append((r, jour, guid))
    return plan


def fenetre(lignes: list[dict], aujourdhui: date) -> list[dict]:
    """Les épingles dont le jour de sortie tombe dans les `JOURS_EN_VOL` derniers jours.

    Aucun état n'est lu ni écrit : deux appels le même jour rendent exactement la même
    liste, et les mêmes dates de publication. C'est ce qui permet à une tâche automatique
    de tourner sans personne pour tenir `PUBLIEES` à jour.

    Chaque element rendu est une COPIE de la ligne du CSV, portant `_pub` (horodatage de
    sortie) et `_guid` : une reprise et sa premiere sortie sont deux items distincts.
    """
    plus_ancien = aujourdhui - timedelta(days=JOURS_EN_VOL - 1)
    choisies: list[dict] = []
    for r, jour, guid in calendrier(lignes):
        if plus_ancien <= jour <= aujourdhui:
            c = dict(r)
            # Midi UTC : une heure fixe, pour que le fichier ne dépende pas de l'heure du passage.
            c["_pub"] = datetime.combine(jour, time(12, 0), tzinfo=timezone.utc)
            c["_guid"] = guid
            choisies.append(c)
    return sorted(choisies, key=lambda r: (r["_pub"], r["_n"]))


# ⛔ PAUSE PINTEREST — posee le 26/10/2026 par l'agent de remise en route du chef. Le domaine
# rollerskateaesthetic.com est BLOQUE par Pinterest depuis le 25/10/2026 (courriel pinbot « We blocked
# your website on Pinterest », motif : regles anti-spam). Tant que ce fichier existe, le mode --fenetre
# ecrit un flux VIDE : Pinterest ne recoit plus aucune epingle neuve vers le domaine bloque.
# RALLUMER : supprimer (ou renommer) `_releves/PAUSE_PINTEREST.txt` dans le depot et pousser ; la
# fournee suivante reprend le calendrier au jour courant (les sorties des jours de pause ne sont pas
# rattrapees par ce mode : leur jour est passe). Ne rallumer qu'apres levee ecrite du blocage.
PAUSE_PINTEREST = HERE / "_releves" / "PAUSE_PINTEREST.txt"


def choisir(lignes: list[dict], args: list[str]) -> list[dict]:
    if "--fenetre" in args:
        if PAUSE_PINTEREST.exists():
            print(f"PAUSE PINTEREST — {PAUSE_PINTEREST.name} present : flux ecrit vide, aucune epingle envoyee.")
            return []
        return fenetre(lignes, datetime.now(timezone.utc).date())
    if "--all" in args:
        return lignes
    demandes = [int(a) for a in args if a.isdigit()]
    if demandes:
        non_validees = sorted(set(demandes) - VALIDEES)
        if non_validees:
            raise SystemExit(
                f"ARRET — epingles {non_validees} demandees mais non validees par le proprietaire. "
                "Le choix explicite n'exempte pas du controle de sens."
            )
        return [r for r in lignes if r["_n"] in demandes]
    restant = [r for r in lignes if r["_n"] not in PUBLIEES]
    prets = [r for r in restant if r["_n"] in VALIDEES]
    bloques = [r for r in restant if r["_n"] not in VALIDEES]
    if not prets and bloques:
        raise SystemExit(
            "ARRET — rien de validable a publier. Les epingles restantes "
            + ", ".join(str(r["_n"]) for r in bloques[:5])
            + " n'ont pas eu leur controle de sens par le proprietaire (regle de traduction, maitre §4). "
            "Lui presenter le francais de un document interne, puis les ajouter a VALIDEES."
        )
    return prets[:2]


def item(r: dict, quand: datetime, declaration_ia: bool = False) -> str:
    n = r["_n"]
    url_png = f"{DOMAIN}/pins/{r['_png']}"
    lien = (r.get("Link") or "").strip()
    if not lien.startswith(DOMAIN):
        raise SystemExit(
            f"ERREUR épingle {n} : Link absent ou hors du domaine revendiqué ({lien!r}). "
            "Pinterest rejetterait le flux entier."
        )
    # length est obligatoire dans la spec RSS 2.0 : on met la vraie taille du fichier.
    chemin = HERE / "pins" / r["_png"]
    if not chemin.is_file():
        raise SystemExit(f"ERREUR : {chemin} absent — le flux pointerait dans le vide.")
    taille = chemin.stat().st_size

    # Pinterest coupe une description a 500 caracteres. On n'ajoute l'appel que s'il tient
    # EN ENTIER : une phrase tronquee au milieu vaut moins que pas de phrase du tout, et une
    # troncature silencieuse est exactement le genre de defaut qu'on ne revoit jamais.
    description = (r["Description"] or "").strip()
    # L'ancienne phrase « Illustration generated with AI. » fait doublon avec la fin obligatoire.
    description = re.sub(r"\s*Illustration generated with AI\.\s*", " ", description).strip()
    # ⛔ DEPUIS LE 16/09/2026 (le propriétaire) : CHAQUE publication porte la mention d'IA, sur Pinterest aussi.
    # Depuis le 22/10/2026 la fin varie d'une epingle a l'autre (`fin_epingle()`). Le plafond de 500
    # caracteres ne se negocie pas : c'est la description qui cede, coupee a la fin de sa derniere
    # phrase entiere, jamais la fin.
    fin = fin_epingle(n, lien)
    if len(description) + len(fin) > 500:
        SANS_APPEL.append(n)   # tenue pour information : la description a ete raccourcie
        description = couper_a_la_phrase(description, 500 - len(fin))
    description += fin


    return f"""    <item>
      <title>{escape(r['Title'])}</title>
      <link>{escape(lien)}</link>
      <guid isPermaLink="false">{escape(r.get("_guid") or f"rollerskateaesthetic-pin-{n}")}</guid>
      <description>{escape(description)}</description>
      <enclosure url="{escape(url_png)}" type="image/png" length="{taille}"/>
      <media:content url="{escape(url_png)}" medium="image" type="image/png"/>
      <pubDate>{format_datetime(quand)}</pubDate>
    </item>"""


def main() -> None:
    lignes = lire_csv()

    # Contrôle d'unicité — il ne se voit pas ligne à ligne, seulement en les comparant.
    vus: dict[str, int] = {}
    for r in lignes:
        lien = (r.get("Link") or "").strip()
        if lien in vus:
            raise SystemExit(
                f"ERREUR : épingles {vus[lien]} et {r['_n']} partagent le lien {lien!r}. "
                "Pinterest les traiterait comme la même épingle (`Duplicate Pin link`)."
            )
        vus[lien] = r["_n"]

    choisies = choisir(lignes, sys.argv[1:])

    # Un flux vide s'ECRIT, il ne se saute pas. Corrige un defaut du 03/08/2026 : le script
    # sortait ici sans rien reecrire quand il n'y avait rien a publier, et feed.xml gardait les
    # items 11 et 12 du 29/07. `un document interne` affirmait que lancer ce script purgeait le flux —
    # c'etait faux, et Pinterest aurait republie ces deux epingles au branchement du flux.
    maintenant = datetime.now(timezone.utc)
    items = "\n".join(item(r, r.get("_pub") or maintenant) for r in choisies)

    # L'appel au guide ne se constate pas a l'oeil sur un flux de deux items : on le dit.
    if SANS_APPEL:
        print(
            f"⚠ DESCRIPTION RACCOURCIE sur {len(SANS_APPEL)} epingle(s) pour loger la fin tiree de la page "
            f"dans la limite Pinterest de 500 caracteres : "
            + ", ".join(str(x) for x in SANS_APPEL)
        )
    else:
        print(f"Fin tiree de la page ajoutee sur les {len(choisies)} epingle(s) du flux.")

    # En mode fenêtre, `lastBuildDate` doit être déterministe lui aussi, sinon le fichier
    # change à chaque passage et déclenche un déploiement pour rien. On prend la plus récente
    # des dates de sortie ; s'il n'y a plus rien à publier, minuit UTC du jour.
    dates_sorties = [r["_pub"] for r in choisies if r.get("_pub")]
    if "--fenetre" in sys.argv[1:]:
        maintenant = max(dates_sorties) if dates_sorties else datetime.combine(
            maintenant.date(), time(0, 0), tzinfo=timezone.utc
        )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Roller Skate Aesthetic</title>
    <link>{DOMAIN}/</link>
    <description>Beginner roller skating tips, gear guides and skate aesthetic.</description>
    <language>en-us</language>
    <lastBuildDate>{format_datetime(maintenant)}</lastBuildDate>
    <atom:link href="{DOMAIN}/feed.xml" rel="self" type="application/rss+xml"/>
{items}
  </channel>
</rss>
"""
    OUT.write_text(xml, encoding="utf-8")
    if choisies:
        nums = ", ".join(str(r["_n"]) for r in choisies)
        print(f"feed.xml écrit — {len(choisies)} épingle(s) : {nums} — {OUT.stat().st_size} octets")
    else:
        print(f"feed.xml PURGÉ — 0 épingle, rien à publier — {OUT.stat().st_size} octets")

    # ⛔ LE RESERVOIR VIDE DOIT CRIER — ajoute le 14/08/2026, session 81, sur une remontee du
    # chef. Defaut corrige : ce script ecrivait un flux vide, sortait a zero, l'Action passait
    # au VERT et Cloudflare deployait un flux sans aucune epingle. Rien ne s'allumait nulle
    # part, et le premier signe aurait ete un compte qui ne publie plus — constate des jours
    # plus tard, par hasard. Un compte a rebours qui arrive a zero en silence est pire qu'une
    # panne : une panne, on la voit.
    #
    # La forme est celle des controles du haut de ce fichier : on sort en erreur. L'ecriture
    # du flux, elle, a DEJA eu lieu au-dessus — on ne saute pas la purge, on echoue apres.
    if "--fenetre" in sys.argv[1:]:
        # Ce qui reste a sortir APRES aujourd'hui, lu dans le calendrier lui-meme (reprises comprises) ;
        # avant le 18/10/2026 c'etait « les numeros superieurs au plus grand du jour », ce qui ne
        # savait pas compter une reprise.
        aujourdhui = datetime.now(timezone.utc).date()
        reste = [guid for _, jour, guid in calendrier(lignes) if jour > aujourdhui]
        # ⛔ CORRIGE LE 22/10/2026 : depuis la cadence de quatre jours par semaine (19/10/2026), la
        # fenetre est VIDE chaque dimanche (samedi et dimanche ne sont pas des jours de sortie, et
        # JOURS_EN_VOL = 2) alors que le reservoir est plein. L'ancien test « 0 epingle aujourd'hui »
        # aurait fait rougir la fournee tous les dimanches, a partir du 25/10/2026. Le reservoir est
        # vide quand il ne reste RIEN au calendrier, pas quand la fenetre du jour est vide.
        if not choisies and not reste:
            raise SystemExit(
                "RESERVOIR VIDE — 0 epingle a publier aujourd'hui, et il n'y a plus de matiere "
                "validee en attente. Le flux a ete purge, mais plus rien ne partira tant qu'un "
                "nouveau lot n'est pas fabrique et ajoute a VALIDEES. "
                "⛔ CETTE SORTIE FAIT ROUGIR LA GITHUB ACTION EXPRES : c'est le seul endroit du "
                "dispositif ou la fin de matiere devient visible sans que personne ne regarde."
            )
        if len(reste) <= len(JOURS_DE_SORTIE) * 3:
            semaines = len(reste) / len(JOURS_DE_SORTIE)
            print(f"⚠ PREAVIS DE FIN DE MATIERE : il reste {len(reste)} epingle(s) validee(s) "
                  f"apres celles du jour, soit environ {semaines:.1f} semaine(s) de publication "
                  f"a {len(JOURS_DE_SORTIE)} par semaine. Fabriquer le lot suivant maintenant.")


if __name__ == "__main__":
    main()
