#!/usr/bin/env python3
"""
GARDE DES CHAINES DE PUBLICATION AUTOMATIQUES DU DEPOT DU SITE.

CE QUE FAIT CE FICHIER, POUR QUI N'A RIEN LU
--------------------------------------------
Le depot de code du site porte plusieurs chaines de publication automatique (les fichiers de
`site/.github/workflows/`). Au 15/09/2026 il y en a cinq, et l'echec d'une seule d'entre elles
est signale a quelqu'un : la fournee, et encore, par ricochet -- la surveillance quotidienne ne
regarde pas son EXECUTION, elle regarde la date du flux qu'elle ecrit. Les quatre autres peuvent
echouer chaque jour sans que personne le sache.

Cette garde repond a cela en trois controles, et elle est construite pour qu'UNE CHAINE AJOUTEE
DEMAIN soit couverte sans reecriture, ou que son absence de couverture soit criee.

LES TROIS CONTROLES
-------------------
A. RECENSEMENT (hors reseau). Les chaines presentes sur le disque sont exactement celles que le
   catalogue declare. Une chaine ajoutee sans etre declaree -> rouge, nommee. Une chaine declaree
   qui a disparu du disque -> rouge, nommee. Une chaine declaree sans surveillant -> rouge, nommee.
   C'est le controle qui interdit qu'un ajout passe en silence.

B. ECHEC D'EXECUTION (reseau, API GitHub). Les chaines sont enumerees PAR L'API, jamais par une
   liste ecrite ici : c'est ce qui les couvre toutes, y compris celles qui n'existaient pas quand
   cette garde a ete ecrite. Rouge des qu'une execution recente d'une chaine quelconque conclut a
   l'echec -- la DERNIERE execution, et aussi toute execution des `HEURES_FENETRE_ECHECS` dernieres
   heures, parce qu'un echec suivi d'un succes ne se lit plus nulle part (mesure du 17/09/2026 :
   l'echec du 13/09 de `fournee.yml` etait rendu « au vert » par cette garde) --, et rouge aussi
   quand une chaine a ete DESACTIVEE (GitHub eteint tout seul les chaines
   a horaire apres 60 jours sans activite du depot : c'est une mort silencieuse).

C. SILENCE D'UNE CHAINE A HORAIRE (reseau, API GitHub). Une chaine qui porte un `schedule:` dans
   son fichier et dont la derniere execution remonte a plus de 48 heures est rouge. Une chaine qui
   ne tourne plus du tout n'echoue jamais : sans ce controle, son silence se lit comme un succes.
   Une chaine SANS `schedule:` (declenchee seulement par un envoi ou a la main : `liens-amazon.yml`,
   `pied-de-page.yml`) n'est jamais jugee sur son silence : ne pas tourner est son etat normal.

⛔ FUSION DU 18/10/2026 (lot 4-E du rattrapage, poste 4). Les deux exemplaires de cette garde avaient
   diverge : le depot (`.github/garde_chaines_de_publication.py`) portait les ajouts du 30/09/2026
   (fenetre ramenee a 26 h, exclusion de ses propres executions passees, chaines « deleted » ignorees)
   que la boite n'avait pas ; la boite portait la correction du 09/10/2026 (phrase « la derniere
   execution est verte » construite sur l'etat reel) que le depot n'avait pas — le message faux
   tournait donc encore en production, mesure par le banc adapte a 26 h le 18/10/2026. Cet exemplaire
   est la version du depot plus la correction du 09/10 ; il doit etre recopie tel quel dans le depot.

⛔ LA REGLE QUI GOUVERNE TOUS LES CODES DE SORTIE
--------------------------------------------------
UN SILENCE NE DOIT JAMAIS POUVOIR PASSER POUR UNE SURVEILLANCE. Donc :
  - sans jeton GitHub, la garde ne rend PAS 0 : elle rend 2, « je ne peux pas conclure ».
  - le mode `--recensement-seul` ne conclut rien sur les echecs et le dit en toutes lettres ;
    il existe pour qu'un appel sans reseau soit un choix ecrit sur la ligne de commande, jamais
    un repli silencieux.

CODES DE SORTIE
---------------
  0  Rien a signaler par les controles qui ont effectivement tourne.
  1  Au moins un defaut nomme.
  2  La garde elle-meme ne peut pas conclure (fichier manquant, jeton absent, API illisible).
     Un 2 n'est pas un vert. Il se traite comme un rouge par qui le recoit.

USAGE
-----
    python3 <instrument local>
    python3 ... --recensement-seul        # controle A uniquement, ne conclut rien sur B et C
    python3 ... --racine <chemin>         # racine du dossier de travail (defaut : dossier courant)
    python3 ... --faux-api <dossier>      # lit l'API dans des fichiers JSON, pour l'epreuve

JETON. Lu dans GITHUB_TOKEN, puis GH_TOKEN, puis (ajoute le 24/09/2026, dossier « Le jeton
GitHub existait deja sur le disque ») dans le fichier `SOUS_CHEMIN_SECRET_GITHUB`
(`<fichier local>` par defaut) : le texte d'ordres d'une tache
programmee ne porte jamais la valeur du jeton. Le depot `andocaps-cmyk/rollerskateaesthetic-site` est
prive : mesure du 16/09/2026, une requete sans jeton sur son API rend 404 et non 401. Un 404 ne
se lit donc JAMAIS comme « le depot n'existe pas » quand le jeton manque.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEPOT = os.environ.get("GITHUB_REPOSITORY", "andocaps-cmyk/rollerskateaesthetic-site")
# ⛔ UN SEUL FICHIER, DEUX LIEUX D'EXECUTION. Cette garde tourne depuis le dossier de travail
# du propriétaire, ou depuis les serveurs de GitHub a l'interieur du depot lui-meme, ou les chemins ne sont
# pas les memes. Les deux variables d'environnement ci-dessous existent pour ca, et pour qu'il n'y
# ait JAMAIS deux copies de cette logique a maintenir : une copie amputee est le defaut mesure du
# 11/08/2026, et deux copies divergent toujours.
SOUS_CHEMIN_WORKFLOWS = Path(
    os.environ.get("GARDE_CHEMIN_WORKFLOWS", ".github/workflows")
)
SOUS_CHEMIN_CATALOGUE = Path(
    os.environ.get(
        "GARDE_CHEMIN_CATALOGUE",
        ".github/CATALOGUE_chaines_de_publication.tsv",
    )
)
# ⛔ AJOUTE LE 24/09/2026, en traitant le dossier d'entree « Le jeton GitHub existait deja sur le
# disque ». Le texte d'ordres d'une tache programmee ne porte JAMAIS la valeur du jeton : cette
# garde doit donc savoir le lire elle-meme sur le disque quand GITHUB_TOKEN et GH_TOKEN sont
# absents de l'environnement. Chemin configurable pour la meme raison que les deux precedents :
# ce fichier n'existe pas a l'interieur du depot GitHub, seulement sur le disque de travail.
SOUS_CHEMIN_SECRET_GITHUB = Path(
    os.environ.get(
        "GARDE_CHEMIN_SECRET_GITHUB",
        "SECRET_github_token.txt",
    )
)

# Age maximal tolere pour la derniere execution d'une chaine a horaire (controle C).
# 48 h et non 24 h : une chaine quotidienne peut sauter un passage et se rattraper, et
# `surveillance.py` du meme depot a deja retenu ce meme seuil pour la meme raison, mesuree
# les 15/08 et 21/08/2026.
HEURES_MAX_SILENCE = 48

# Fenetre, en jours, sur laquelle le controle B relit les executions PASSEES d'une chaine, et pas
# seulement la derniere.
# ⛔ MOTIF, ET IL EST MESURE LE 17/09/2026. L'execution n°122 de `fournee.yml`, du 13/09/2026 a
# 01 h 24 TU, a conclu a l'echec ; les dix-huit executions suivantes ont reussi. Cette garde,
# lancee le 17/09/2026 avant ce correctif, ecrivait « [OK] Chaine au vert — fournee.yml,
# Execution n°140 » : elle ne lisait que `runs?per_page=1`, donc la seule derniere execution.
# Un echec suivi d'un succes etait invisible pour elle, et c'est exactement le defaut que le
# dossier « echec-releve-pinterest-sans-proprietaire » nomme : un echec qui n'arrive a personne.
# POURQUOI SEPT JOURS ET PAS QUARANTE-HUIT HEURES. Le seuil de 48 h du controle C suppose un
# passage quotidien. Cette garde n'est branchee sur aucun declencheur au 17/09/2026 —
# `GABARIT_WORKFLOW_echec_de_chaine.yml` n'est pose dans aucun depot — donc elle ne tourne que
# quand quelqu'un la lance. Une fenetre calee sur un passage quotidien qui n'existe pas laisserait
# passer l'echec qu'elle doit attraper. Sept jours est le prix declare : une fois la garde branchee
# tous les jours, un echec deja vu sera renomme pendant sept jours au lieu d'un seul.
# CE QUE CETTE FENETRE NE FAIT PAS : un echec plus ancien que sept jours n'est pas nomme. La borne
# est ecrite ici et se releve en changeant ce seul chiffre.
#
# ⛔ RAMENEE A 26 HEURES LE 30/09/2026. La garde est branchee chaque jour depuis le 24/09/2026
# (`echec-de-chaine.yml`, 12 h 30 UTC) : le prix declare ci-dessus s'est paye. Du 24 au 29/09 elle
# a ete rouge chaque soir sur des echecs deja nommes la veille (fournee du 24/09, releve Pinterest)
# et elle envoyait donc un courriel chaque jour meme quand toutes les chaines etaient vertes. 26 h
# = un passage quotidien + 2 h de retard possible du cron GitHub : chaque echec est nomme une fois.
HEURES_FENETRE_ECHECS = 26

# ⛔ AJOUTE LE 30/09/2026. La garde ne relit pas ses propres executions passees : chacun de ses
# rouges passes est deja un rouge d'une autre chaine, nomme ce jour-la. Sans cette exclusion, un
# seul rouge la faisait retomber en rouge tous les jours suivants (mesure : executions n°1 a 5,
# 24 au 28/09/2026, renommees par l'execution n°6). Le fichier de la garde est lu dans la variable
# GITHUB_WORKFLOW_REF que GitHub pose dans chaque execution ; hors GitHub, rien n'est exclu.
#
# ⛔ ELARGI LE 23/10/2026 (restes du 23/10). Hors GitHub, « rien n'est exclu » faisait rougir la
# garde lancee a la main sur sa propre derniere execution rouge (« CHAINE EN ECHEC —
# echec-de-chaine.yml », rejeu local du 23/10/2026) : une fois rouge, elle ne pouvait plus se lire
# verte. Le fichier propre vaut donc `echec-de-chaine.yml` par defaut (GARDE_FICHIER_PROPRE le
# change), et la garde ne juge plus AUCUNE conclusion de ses propres executions, ni la derniere ni
# les passees. Elle juge encore, sur elle-meme, la desactivation et le silence (controle C).
# PRIX DECLARE : un plantage de la garde elle-meme (code 2) n'est plus nomme par elle ; il reste
# le courriel d'echec de GitHub et le controle du silence.
FICHIER_PROPRE = (
    Path(os.environ.get("GITHUB_WORKFLOW_REF", "").split("@")[0]).name
    or os.environ.get("GARDE_FICHIER_PROPRE", "echec-de-chaine.yml")
)

# Conclusions d'execution qui valent echec. `cancelled` en fait partie : une execution annulee
# n'a pas fait le travail, et rien d'autre ne le signalerait.
# ⛔ SAUF, DEPUIS LE 23/10/2026, une execution PASSEE annulee quand une execution PLUS RECENTE de la
# meme chaine a conclu « success » : c'est l'annulation normale de la regle `concurrency` quand
# plusieurs poussees se suivent, et le travail a ete fait par l'execution suivante. Mesure :
# execution n°33 de `echec-de-chaine.yml` (22/10/2026, 21 h 55 UTC), rouge sur cinq seules
# annulations de `publier.yml`. Une DERNIERE execution annulee reste un echec : rien ne l'a refaite.
CONCLUSIONS_ECHEC = {"failure", "timed_out", "startup_failure", "cancelled", "action_required"}

ECHECS: list[str] = []
INCONCLUSIONS: list[str] = []


def echec(titre: str, detail: str) -> None:
    ECHECS.append(f"{titre}\n    {detail}")
    print(f"[ECHEC]  {titre}\n         {detail}")


def inconclusion(titre: str, detail: str) -> None:
    INCONCLUSIONS.append(f"{titre}\n    {detail}")
    print(f"[NE CONCLUT PAS] {titre}\n                 {detail}")


def ok(titre: str, detail: str = "") -> None:
    print(f"[OK]     {titre}" + (f"\n         {detail}" if detail else ""))


# ── Lecture de l'API, ou de son faux temoin ──────────────────────────────────────────────
def lire_jeton(racine: Path) -> str | None:
    """Rend le jeton GitHub : d'abord GITHUB_TOKEN, puis GH_TOKEN, puis le fichier de secrets du
    projet sur le disque. Ajoute le 24/09/2026 : le texte d'ordres d'une tache programmee ne
    porte jamais la valeur du jeton, et le poste 4 a mesure le 16/09/2026 que ce fichier existe
    deja sur le disque avec les droits necessaires plutot que de rouvrir un geste au propriétaire."""
    jeton = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if jeton:
        return jeton
    # 21/10/2026 (coffre le coffre local) : un chemin GARDE_CHEMIN_SECRET_GITHUB posé exprès garde sa
    # priorité ; sinon la variable posée par _lanceurs\lance.ps1, puis le fichier, puis la quarantaine.
    if "GARDE_CHEMIN_SECRET_GITHUB" not in os.environ:
        v = (os.environ.get("GITHUB_TOKEN_ROLLERSKATEAESTHETIC_PUSH") or "").strip()
        if v:
            return v
    fichier = racine / SOUS_CHEMIN_SECRET_GITHUB
    if not fichier.is_file():
        return None
    lu = fichier.read_text(encoding="utf-8").strip()
    return lu or None


def lire_api(chemin: str, faux: Path | None, nom_fichier: str, jeton: str | None = None) -> dict | None:
    """Rend l'objet JSON, ou None si la lecture n'a pas pu conclure (l'appelant tranche)."""
    if faux is not None:
        fichier = faux / nom_fichier
        if not fichier.exists():
            inconclusion(
                f"Faux temoin absent — {nom_fichier}",
                f"{fichier} n'existe pas. L'epreuve ne peut rien dire.",
            )
            return None
        return json.loads(fichier.read_text(encoding="utf-8"))

    if not jeton:
        return None  # l'appelant a deja verifie le jeton ; garde-fou
    requete = urllib.request.Request(
        f"https://api.github.com{chemin}",
        headers={
            "Authorization": f"Bearer {jeton}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "garde-chaines-de-publication",
        },
    )
    try:
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as erreur:
        detail = f"HTTP {erreur.code} sur {chemin}."
        if erreur.code == 404:
            detail += (
                " ⛔ Sur un depot PRIVE, 404 est aussi la reponse a un jeton sans droit de"
                " lecture sur les executions. Ne pas lire ce 404 comme « le depot n'existe pas »."
            )
        inconclusion("L'API GitHub n'a pas repondu utilement", detail)
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as erreur:
        inconclusion(
            "L'API GitHub est injoignable",
            f"{type(erreur).__name__}: {erreur}. Le reseau n'a pas repondu — ce n'est PAS un vert.",
        )
        return None


# ── A. RECENSEMENT ───────────────────────────────────────────────────────────────────────
def controle_recensement(racine: Path) -> tuple[set[str], dict[str, dict]] | None:
    dossier = racine / SOUS_CHEMIN_WORKFLOWS
    catalogue = racine / SOUS_CHEMIN_CATALOGUE

    if not dossier.is_dir():
        inconclusion(
            "Le dossier des chaines est INTROUVABLE",
            f"{dossier} n'existe pas. La garde ne sait pas ce qu'elle devrait recenser.",
        )
        return None
    if not catalogue.is_file():
        inconclusion(
            "Le catalogue des chaines est INTROUVABLE",
            f"{catalogue} n'existe pas. Sans lui, aucun ajout ne peut etre detecte.",
        )
        return None

    sur_disque = {f.name for f in dossier.iterdir() if f.suffix in (".yml", ".yaml") and f.is_file()}

    declarees: dict[str, dict] = {}
    for numero, ligne in enumerate(catalogue.read_text(encoding="utf-8").splitlines(), 1):
        if not ligne.strip() or ligne.startswith("#"):
            continue
        champs = ligne.split("\t")
        if len(champs) < 5:
            inconclusion(
                f"Ligne {numero} du catalogue illisible",
                f"5 colonnes attendues, {len(champs)} trouvee(s) : {ligne!r}",
            )
            return None
        declarees[champs[0].strip()] = {
            "nom": champs[1].strip(),
            "declencheur": champs[2].strip(),
            "surveillant": champs[3].strip(),
            "depuis": champs[4].strip(),
        }

    if not declarees:
        inconclusion(
            "Le catalogue des chaines est VIDE",
            f"{catalogue} ne porte aucune ligne de chaine. Un catalogue vide accepte tout.",
        )
        return None

    for fichier in sorted(sur_disque - set(declarees)):
        echec(
            f"CHAINE NON RECENSEE — {fichier}",
            f"Elle tourne dans le depot et ne figure pas dans {SOUS_CHEMIN_CATALOGUE}. "
            "Ajouter sa ligne au catalogue, avec le nom de ce qui signale son echec.",
        )
    for fichier in sorted(set(declarees) - sur_disque):
        echec(
            f"CHAINE DECLAREE ET ABSENTE DU DISQUE — {fichier}",
            "Le catalogue la surveille, le depot ne la porte plus. Soit elle a ete supprimee et "
            "sa ligne doit partir, soit le dossier lu n'est pas celui du depot publie.",
        )
    sans_surveillant = sorted(
        f for f, d in declarees.items()
        if f in sur_disque and d["surveillant"].lower() in ("", "aucun", "-")
    )
    for fichier in sans_surveillant:
        echec(
            f"CHAINE SANS SURVEILLANT DECLARE — {fichier}",
            "Son echec ne serait signale a personne. Ce rouge s'eteint quand la colonne "
            "« surveillant » de sa ligne nomme ce qui attrape son echec.",
        )
    couvertes = sorted(f for f in sur_disque if f in declarees and f not in sans_surveillant)
    if couvertes:
        ok(f"{len(couvertes)} chaine(s) recensee(s) et pourvue(s) d'un surveillant", ", ".join(couvertes))
    return sur_disque, declarees


# ── B et C. ECHEC D'EXECUTION ET SILENCE ─────────────────────────────────────────────────
def controle_executions(racine: Path, sur_disque: set[str], faux: Path | None, jeton: str | None) -> None:
    liste = lire_api(f"/repos/{DEPOT}/actions/workflows?per_page=100", faux, "workflows.json", jeton)
    if liste is None:
        return
    chaines = liste.get("workflows", [])
    if not chaines:
        inconclusion(
            "L'API ne rend AUCUNE chaine",
            f"Reponse lue, 0 chaine pour {DEPOT}. Le disque en porte {len(sur_disque)}. "
            "Une reponse vide n'est pas une preuve d'absence d'echec.",
        )
        return

    vues_par_api = set()
    for chaine in chaines:
        fichier = Path(chaine.get("path", "")).name
        vues_par_api.add(fichier)
        nom = chaine.get("name", fichier)
        etat = chaine.get("state", "")

        # ⛔ AJOUTE LE 30/09/2026. Une chaine dont le fichier a ete retire du depot garde son
        # historique chez GitHub avec l'etat « deleted ». Ce retrait est un choix ecrit dans
        # l'historique du depot, pas une mort silencieuse : on ne la juge plus. (Cas reel :
        # `pinterest-releve.yml`, en echec 401 du 17 au 27/09/2026, retiree le 30/09/2026.)
        if etat == "deleted":
            vues_par_api.discard(fichier)
            print(f"[RETIREE] {fichier} ({nom}) — fichier retire du depot, historique ignore.")
            continue

        if etat != "active":
            echec(
                f"CHAINE DESACTIVEE — {fichier} ({nom})",
                f"Etat rendu par l'API : {etat!r}. Une chaine desactivee n'echoue jamais : "
                "elle ne tourne plus, et son silence se lit comme un succes.",
            )

        executions = lire_api(
            f"/repos/{DEPOT}/actions/workflows/{chaine['id']}/runs?per_page=100",
            faux,
            f"runs_{chaine['id']}.json",
            jeton,
        )
        if executions is None:
            inconclusion(
                f"Executions illisibles — {fichier}",
                "L'etat de cette chaine reste inconnu apres ce passage.",
            )
            continue
        runs = executions.get("workflow_runs", [])
        if not runs:
            echec(
                f"CHAINE SANS AUCUNE EXECUTION — {fichier} ({nom})",
                "Elle est dans le depot et n'a jamais tourne. Rien ne dira jamais qu'elle echoue.",
            )
            continue

        derniere = runs[0]
        conclusion = derniere.get("conclusion")
        numero = derniere.get("run_number")
        adresse = derniere.get("html_url", "")
        horodatage = derniere.get("created_at", "")

        if etat != "active":
            # Le rouge de la desactivation a deja ete pose. Ne pas ecrire « au vert » sur une
            # chaine eteinte : sa derniere execution peut etre verte et ne rien dire d'aujourd'hui.
            print(
                f"         (derniere execution connue de {fichier} : n°{numero}, "
                f"conclusion « {conclusion} », du {horodatage})"
            )
        elif fichier == FICHIER_PROPRE:
            print(
                f"[PROPRE] {fichier} — la garde ne juge pas ses propres conclusions "
                f"(derniere : n°{numero}, « {conclusion} »)."
            )
        elif conclusion in CONCLUSIONS_ECHEC:
            echec(
                f"CHAINE EN ECHEC — {fichier} ({nom})",
                f"Execution n°{numero} du {horodatage}, conclusion « {conclusion} ». {adresse}",
            )
        elif conclusion is None:
            ok(f"Chaine en cours d'execution — {fichier}", f"Execution n°{numero}, pas encore conclue.")
        else:
            ok(f"Chaine au vert — {fichier}", f"Execution n°{numero}, conclusion « {conclusion} ».")

        # ── B bis. ECHEC RECENT DEJA RECOUVERT PAR UN SUCCES ──────────────────────────
        # Un echec suivi d'un succes n'apparait plus dans la derniere execution. Sans ce
        # balayage, il ne serait nomme par rien : ni par le bloc ci-dessus, ni par le controle
        # du silence, puisque la chaine tourne. Les executions sont rendues de la plus recente
        # a la plus ancienne ; runs[0] est deja jugee ci-dessus, on relit les suivantes.
        limite = datetime.now(timezone.utc) - timedelta(hours=HEURES_FENETRE_ECHECS)
        for rang, passee in enumerate([] if fichier == FICHIER_PROPRE else runs[1:], 1):
            date_brute = passee.get("created_at", "")
            if not date_brute:
                inconclusion(
                    f"Execution passee sans date — {fichier}",
                    f"Execution n°{passee.get('run_number')} rendue sans `created_at`. "
                    "Elle ne peut etre ni retenue ni ecartee de la fenetre.",
                )
                continue
            try:
                quand = datetime.fromisoformat(date_brute.replace("Z", "+00:00"))
            except ValueError:
                inconclusion(
                    f"Date d'execution passee illisible — {fichier}",
                    f"Valeur rendue : {date_brute!r} sur l'execution "
                    f"n°{passee.get('run_number')}.",
                )
                continue
            if quand < limite:
                break  # les suivantes sont plus anciennes encore
            if passee.get("conclusion") == "cancelled" and any(
                plus_recente.get("conclusion") == "success" for plus_recente in runs[:rang]
            ):
                print(
                    f"[ANNULEE] {fichier} — execution n°{passee.get('run_number')} annulee, "
                    "refaite par une execution plus recente au vert : pas un echec."
                )
                continue
            if passee.get("conclusion") in CONCLUSIONS_ECHEC:
                # ⛔ CORRIGE LE 09/10/2026, dossier d'entree « message-faux-dans-la-garde-des-
                # chaines-de-publication », mesure du 19/09/2026 a 01h04 UTC. La phrase qui suit
                # affirmait TOUJOURS que « la derniere execution de cette chaine est verte »,
                # sans jamais regarder la conclusion reelle de `derniere` (calculee plus haut dans
                # cette meme boucle). Elle etait vraie dans le cas qui a motive ce controle (un
                # echec recouvert par un succes) et fausse des qu'une chaine enchaine plusieurs
                # echecs : la derniere execution etait alors ELLE AUSSI en echec, deja signalee
                # juste au-dessus comme « CHAINE EN ECHEC », et la phrase le dementait dans la
                # meme sortie. Le texte est maintenant construit a partir de l'etat reel de
                # `derniere`, pour les quatre cas possibles (verte, en echec, en cours, chaine
                # desactivee) plutot que de supposer le premier.
                if etat != "active":
                    titre_bis = f"ECHEC RECENT NON RECOUVERT — CHAINE DESACTIVEE — {fichier} ({nom})"
                    etat_dernier = (
                        f"La chaine est desactivee (etat « {etat} »), deja signale ci-dessus : "
                        "cet echec passe ne se recouvre d'aucune execution active plus recente."
                    )
                elif conclusion in CONCLUSIONS_ECHEC:
                    titre_bis = f"ECHEC RECENT NON RECOUVERT — ECHECS CONSECUTIFS — {fichier} ({nom})"
                    etat_dernier = (
                        f"La derniere execution de cette chaine (n°{numero}) est ELLE AUSSI en "
                        f"echec (conclusion « {conclusion} », deja signalee ci-dessus comme "
                        "CHAINE EN ECHEC) : ce rouge n'est pas isole, il s'ajoute a un echec "
                        "toujours visible."
                    )
                elif conclusion is None:
                    titre_bis = f"ECHEC RECENT NON RECOUVERT — DERNIERE EXECUTION EN COURS — {fichier} ({nom})"
                    etat_dernier = (
                        f"La derniere execution de cette chaine (n°{numero}) est en cours, pas "
                        "encore conclue : ce rouge n'est donc pas encore recouvert par un succes."
                    )
                else:
                    titre_bis = f"ECHEC RECENT DEJA RECOUVERT PAR UN SUCCES — {fichier} ({nom})"
                    etat_dernier = (
                        "La derniere execution de cette chaine est verte, donc ce rouge ne se "
                        "voit nulle part ailleurs."
                    )
                echec(
                    titre_bis,
                    f"Execution n°{passee.get('run_number')} du {date_brute}, conclusion "
                    f"« {passee.get('conclusion')} ». {passee.get('html_url', '')} "
                    f"{etat_dernier} Fenetre relue : {HEURES_FENETRE_ECHECS} heures.",
                )

        # ── C. SILENCE ────────────────────────────────────────────────────────────────
        fichier_local = racine / SOUS_CHEMIN_WORKFLOWS / fichier
        a_un_horaire = (
            fichier_local.is_file()
            and re.search(r"^\s*schedule\s*:", fichier_local.read_text(encoding="utf-8"), re.M)
        )
        if a_un_horaire and horodatage:
            try:
                depuis = datetime.now(timezone.utc) - datetime.fromisoformat(
                    horodatage.replace("Z", "+00:00")
                )
            except ValueError:
                inconclusion(
                    f"Date d'execution illisible — {fichier}",
                    f"Valeur rendue : {horodatage!r}. Le controle du silence ne peut pas conclure.",
                )
                continue
            if depuis > timedelta(hours=HEURES_MAX_SILENCE):
                echec(
                    f"CHAINE A HORAIRE MUETTE — {fichier} ({nom})",
                    f"Elle porte un `schedule:` et n'a plus tourne depuis "
                    f"{int(depuis.total_seconds() // 3600)} h (seuil {HEURES_MAX_SILENCE} h). "
                    f"Derniere execution le {horodatage}. Un declencheur qui ne part plus "
                    "ne produit aucun echec a signaler.",
                )

    for fichier in sorted(sur_disque - vues_par_api):
        echec(
            f"CHAINE SUR LE DISQUE ET INCONNUE DE L'API — {fichier}",
            "Le fichier local n'est pas arrive jusqu'a GitHub : la copie locale du depot n'est "
            "pas celle qui tourne, et la chaine n'est surveillee par rien.",
        )
    for fichier in sorted(vues_par_api - sur_disque):
        echec(
            f"CHAINE CHEZ GITHUB ET ABSENTE DU DISQUE — {fichier}",
            "Elle tourne chez GitHub et le dossier local ne la porte pas : le recensement du "
            "controle A ne peut donc pas la voir.",
        )


# ── D. SUSPENSIONS OUVERTES (ajoute le 10/11/2026, poste reseaux du chef) ────────────────
# Une chaine de publication qui recoit un refus de type BLOCAGE (Instagram 4/2207051 du 08/11/2026) se
# suspend elle-meme (`suspension.py` a la racine du depot, fichiers `_releves/suspension_<reseau>.json`) :
# son passage qui recoit le refus sort en echec UNE fois, et les passages suivants sortent au vert SANS
# appeler la plateforme. Le controle B voit donc cet echec pendant ses 26 heures, puis plus rien : le
# signal est donne une fois, au lieu d'un rouge chaque jour tant que le compte reste bloque.
# Ce bloc ne fait echouer RIEN : il dit, a chaque passage, quelles chaines sont suspendues et jusqu'a
# quand, pour que l'incident reste lisible ici tant qu'il est ouvert.
def lister_suspensions(racine: Path) -> None:
    for fichier in sorted((racine / "_releves").glob("suspension_*.json")):
        try:
            e = json.loads(fichier.read_text(encoding="utf-8"))
        except (OSError, ValueError) as erreur:
            inconclusion(f"Fichier de suspension illisible — {fichier.name}", f"{type(erreur).__name__}: {erreur}")
            continue
        if e.get("actif"):
            print(
                f"[SUSPENDUE] {e.get('cle')} — depuis {e.get('depuis')}, {e.get('refus')} refus, dernier "
                f"{e.get('dernier_refus')} ; prochain essai unique {e.get('prochain_essai')} ; aucun appel a la "
                f"plateforme d'ici la. Motif : {str(e.get('motif', ''))[:200]} ({fichier.name})"
            )
        else:
            print(f"[SUSPENSION LEVEE] {e.get('cle')} — le {e.get('leve_le')} : {e.get('leve_par')} ({fichier.name})")


def main() -> None:
    arguments = sys.argv[1:]
    recensement_seul = "--recensement-seul" in arguments

    racine = Path.cwd()
    if "--racine" in arguments:
        racine = Path(arguments[arguments.index("--racine") + 1]).resolve()
    faux = None
    if "--faux-api" in arguments:
        faux = Path(arguments[arguments.index("--faux-api") + 1]).resolve()

    print("=" * 78)
    print(
        "GARDE DES CHAINES DE PUBLICATION — "
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC — racine {racine}"
    )
    print("=" * 78)

    resultat = controle_recensement(racine)
    if resultat is None:
        print("-" * 78)
        print("⛔ CODE 2 — la garde n'a pas pu recenser. Ce n'est PAS un vert.")
        raise SystemExit(2)
    sur_disque, _ = resultat

    if recensement_seul:
        print("-" * 78)
        print(
            "⛔ MODE RECENSEMENT SEUL. Les controles B (echec d'execution) et C (silence d'une "
            "chaine a horaire) N'ONT PAS TOURNE. Ce passage ne dit RIEN de l'etat des executions."
        )
    elif faux is None and lire_jeton(racine) is None:
        print("-" * 78)
        print(
            "⛔ CODE 2 — aucun jeton dans GITHUB_TOKEN, GH_TOKEN, ni dans "
            f"{SOUS_CHEMIN_SECRET_GITHUB}. Le depot est prive : sans jeton, les executions sont "
            "illisibles et la garde ne peut rien conclure. Pour un passage hors reseau assume, "
            "appeler avec --recensement-seul."
        )
        raise SystemExit(2)
    else:
        controle_executions(racine, sur_disque, faux, lire_jeton(racine))

    lister_suspensions(racine)
    print("-" * 78)
    if INCONCLUSIONS:
        print(f"{len(INCONCLUSIONS)} point(s) sur lesquels la garde NE CONCLUT PAS :")
        for point in INCONCLUSIONS:
            print(f"  - {point}")
    if ECHECS:
        print(f"\n{len(ECHECS)} DEFAUT(S) NOMME(S) :")
        for defaut in ECHECS:
            print(f"  - {defaut}")
        raise SystemExit(1)
    if INCONCLUSIONS:
        print("\n⛔ CODE 2 — aucun defaut nomme, mais des points restent inconnus. Pas un vert.")
        raise SystemExit(2)
    if recensement_seul:
        print(
            "Aucun defaut AU RECENSEMENT : les chaines du disque sont toutes declarees et toutes "
            "pourvues d'un surveillant. ⛔ Cette ligne ne dit RIEN de l'etat des executions."
        )
    else:
        print("Aucun defaut. Toutes les chaines recensees sont couvertes et aucune n'est en echec.")


if __name__ == "__main__":
    main()
