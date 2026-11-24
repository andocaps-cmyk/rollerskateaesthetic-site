#!/usr/bin/env python3
"""Rotation des categories et des mentions, commune a Threads (publier_threads.py) et Bluesky (publier_reseaux.py).
Stdlib seule, aucun modele.

Ecrit le 29/10/2026 (prompts un document interne et
un document interne). Lecon de Pinterest (un document interne) et
regle anti-spam de Meta lue le 28/10 : une fin identique sur chaque publication, et des series de pages du meme
sujet, sont des « signaux de contenu repetitif ».

CATEGORIES : chaque page /skate/ ou /guide/ recoit une categorie, tiree de son adresse et de son titre par les
mots-cles de REGLES appliques a l'adresse (le titre ajoutait du bruit au premier classement) (premiere regle qui correspond ; « divers » sinon). Le classement est ecrit dans
_releves/categories_threads.tsv (cle, categorie) : `python3 rotation_publications.py` le reecrit. Une ligne du
fichier l'emporte sur le calcul : on corrige une page mal classee en changeant sa ligne a la main. Une page neuve
absente du fichier est classee a la volee.

REGLE DE CHOIX (choisir_pages) :
- jamais deux publications de la meme categorie le meme jour ;
- jamais la meme categorie que la publication precedente, meme d'un jour a l'autre ;
- a egalite, la categorie la moins publiee jusqu'ici ; puis la page la plus ancienne ;
- une seule page « commerciale » par jour (guide d'achat, ou page qui porte la mention d'affiliation).

MENTIONS (choisir_variante) : la mention d'IA et la mention d'affiliation tournent parmi des formulations de meme
sens, sans jamais reprendre deux fois de suite la meme. Regle du propriétaire du 16/09/2026 : aucune des deux ne se retire.
"""
import os, re, sys

FICHIER = "_releves/categories_threads.tsv"

# (categorie, motif sur « adresse + titre » en minuscules). L'ordre compte : la premiere qui correspond gagne.
REGLES = [
    ("guide-achat", r"^guide/"),
    ("freiner", r"\bstop|brake|plough|plow|powerslide|slow(s)? (you )?down|pizza|\bv-is-for|hockey|t-stop"),
    ("chutes-protections", r"\bfall|get-up|get up|kneeling|protective|helmet|pads|danger|adrenaline"),
    ("figures-sauts", r"jump|spin|danc|eagle|arabesque|barrel|moonwalk|shuffle|crazy-legs|shoot-the-duck|downtown|"
                      r"catwalk|strut|routine|flow|dribble|ballerina|bounce|trick"),
    ("tourner", r"turn|edge|crossover|mohawk|transition|curve|steer|parallel"),
    ("materiel", r"wheel|bearing|boot|lace|strap|frame|plate|brake-pad|clean|dry-your|wash|smell|tool|bag|size|socks|"
                 r"rocker|liner|gear|skates-are|inline-skates|quads-were|six-wheels|new-gear"),
    ("corps", r"feet|foot|cramp|ankle|knee|stretch|glute|hip|back(?!wards)|pronation|cross-training|injur|arch|"
              r"tension|body|leg\b|legs|tire"),
    ("dehors", r"rain|wet|city|street|road|hill|curb|rail|tram|outdoor|outside|rough|grass|white-lines|ground|"
               r"descent|aquaplan"),
    ("equilibre-posture", r"balance|weight|posture|wobbl|stride|push|glide|backwards|lean|arms|footprint|navel|"
                          r"hands|one-skate|side-by-side|steps"),
]
COMMERCIALE = "guide-achat"


def classer(cle, titre=""):
    texte = (cle + " " + titre).lower()
    for cat, motif in REGLES:
        if re.search(motif, texte):
            return cat
    return "divers"


def lire_categories():
    if not os.path.exists(FICHIER):
        return {}
    out = {}
    with open(FICHIER, encoding="utf-8") as f:
        for l in f:
            c = l.rstrip("\n").split("\t")
            if len(c) >= 2 and not l.startswith("#"):
                out[c[0]] = c[1]
    return out


def categorie(cle, titre="", table=None):
    cle = cle[len("page:"):] if cle.startswith("page:") else cle
    t = lire_categories() if table is None else table
    return t.get(cle) or classer(cle, titre)


def choisir_variante(variantes, precedente):
    """La variante qui suit `precedente` dans la liste (jamais la meme deux fois de suite)."""
    if precedente in variantes:
        return variantes[(variantes.index(precedente) + 1) % len(variantes)]
    return variantes[0]


def choisir_pages(candidats, historique, aujourdhui, combien, commerciale=None):
    """candidats : pages dans l'ordre de preference (plus ancienne d'abord), chacune avec « categorie ».
    historique : publications passees, plus ancienne d'abord, chacune (date AAAA-MM-JJ, categorie, commerciale).
    commerciale(page) -> bool ; par defaut, la categorie guide-achat.
    Rend au plus `combien` pages qui respectent la regle de choix (voir en tete)."""
    commerciale = commerciale or (lambda p: p["categorie"] == COMMERCIALE)
    compte = {}
    for _, cat, _ in historique:
        compte[cat] = compte.get(cat, 0) + 1
    du_jour = [h for h in historique if h[0] == aujourdhui]
    cats_jour = set(h[1] for h in du_jour)
    com_jour = any(h[2] for h in du_jour)
    derniere = historique[-1][1] if historique else None
    pris = []
    for _ in range(combien):
        ok = [p for p in candidats if p not in pris and p["categorie"] not in cats_jour and p["categorie"] != derniere
              and not (com_jour and commerciale(p))]
        if not ok:
            break
        rang = dict((p["categorie"], i) for i, p in reversed(list(enumerate(ok))))
        cat = min(rang, key=lambda c: (compte.get(c, 0), rang[c]))
        p = next(p for p in ok if p["categorie"] == cat)
        pris.append(p)
        cats_jour.add(cat)
        derniere = cat
        compte[cat] = compte.get(cat, 0) + 1
        com_jour = com_jour or commerciale(p)
    return pris


def main():
    import publier_threads as pt
    pages = pt.lire_pages()
    anciennes = lire_categories()
    lignes = []
    for p in pages:
        lignes.append((p["cle"], anciennes.get(p["cle"]) or classer(p["cle"])))
    os.makedirs("_releves", exist_ok=True)
    with open(FICHIER, "w", encoding="utf-8", newline="\n") as f:
        f.write("# cle\tcategorie (rotation_publications.py ; une ligne corrigee a la main l'emporte sur le calcul)\n")
        for cle, cat in lignes:
            f.write("%s\t%s\n" % (cle, cat))
    compte = {}
    for _, c in lignes:
        compte[c] = compte.get(c, 0) + 1
    print("%d pages classees dans %s : %s" % (len(lignes), FICHIER,
                                               ", ".join("%s %d" % kv for kv in sorted(compte.items(), key=lambda kv: -kv[1]))))


if __name__ == "__main__":
    sys.exit(main())
