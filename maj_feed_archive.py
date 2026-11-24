#!/usr/bin/env python3
"""
Met a jour feed_archive.xml SANS reecrire les articles deja presents.

Pourquoi un script a part : build_feed_archive.py reconstruit tout le catalogue avec le
texte COURANT de build_feed.py. Or ce texte a evolue depuis le 21/09 (mention d'IA, fin de
description) : regenere tel quel, chacun des articles deja lus par Flipboard changerait
de description. Ici, les <item> deja presents dans le fichier du depot sont gardes
tels quels (identifies par leur <guid>) ; seuls les articles dont le guid manque sont
ajoutes, avec le texte que build_feed_archive.py leur donne (et, depuis le 29/10/2026, ceux qui portent
encore « nothing to buy »). Le filtre « date <=
aujourd'hui » reste celui de build_feed_archive.py : aucun article futur n'entre.

Idempotent : deux executions le meme jour rendent le meme fichier, donc aucun commit.
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "feed_archive.xml"
ITEM = re.compile(r"^[ 	]*<item>.*?</item>", re.S | re.M)
GUID = re.compile(r"<guid[^>]*>([^<]*)</guid>")


def lire(p: Path) -> str:
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def items(texte: str) -> dict[str, str]:
    return {GUID.search(i).group(1): i for i in ITEM.findall(texte)}


def main() -> None:
    anciens = items(lire(OUT)) if OUT.exists() else {}
    subprocess.run([sys.executable, str(HERE / "build_feed_archive.py")], check=True)
    neuf_texte = lire(OUT)
    neufs = items(neuf_texte)

    # Ordre du generateur (plus recent en tete), texte ancien conserve quand il existe.
    ordre = list(GUID.findall(neuf_texte))
    perdus = [g for g in anciens if g not in neufs]
    if perdus:
        raise SystemExit(f"ARRET — articles du depot absents du catalogue regenere : {perdus}")
    # 29/10/2026 : un article ancien qui porte « nothing to buy » est remplace par son texte courant
    # (meme guid). La phrase est fausse depuis que des pages portent des liens Amazon, et Pinterest l'a
    # retenue contre nous ; elle ne doit plus etre servie. Chez Flipboard, les articles deja avales ne
    # bougent pas : seul le fichier servi change.
    for g in list(anciens):
        if "nothing to buy" in anciens[g].lower() and g in neufs:
            del anciens[g]
    corps = "\n".join(anciens.get(g, neufs[g]) for g in ordre)

    debut = neuf_texte[: ITEM.search(neuf_texte).start()]
    fin = neuf_texte[neuf_texte.rindex("</item>") + len("</item>"):]
    OUT.write_bytes((debut + corps + fin).encode("utf-8"))
    ajoutes = [g for g in ordre if g not in anciens]
    print(f"feed_archive.xml : {len(ordre)} articles, dont {len(ajoutes)} ajoute(s), "
          f"{len(ordre) - len(ajoutes)} conserve(s) a l'identique")


if __name__ == "__main__":
    main()
