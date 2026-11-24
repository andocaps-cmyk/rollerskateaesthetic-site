#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Liens Amazon DIRECTS + comptage du clic sans redirection — réécrit le 15/11/2026.

Commande de build de Cloudflare Pages pour ce site (le nom du fichier est gardé pour cette raison :
changer le nom obligerait à changer la commande dans l'interface de Cloudflare).

HISTOIRE. Du 10/11/2026 au 15/11/2026, ce script réécrivait chaque lien Amazon des pages en
    href="/va/<produit>?p=<page>&amp;to=<adresse Amazon>"
et la Function /va/ comptait le clic puis renvoyait en 302 vers Amazon. Décision de plateforme du
projet du 15/11/2026 (un document interne du dossier du projet, ligne du 15/11 02 h 36) : les règles
du programme Amazon (« Associates Program Policies », mise à jour du 14/04/2026, lues le 15/11/2026)
disqualifient les achats venus d'un « Redirecting Link » (Commission Income Statement § 2(e)) et
exigent que « All Special Links must be accessed directly from your Site » (Participation
Requirements § 2(b)) ; elles ne disent pas si une redirection sur le même domaine est visée. Conduite
la moins exposée : les pages ne passent plus par /va/.

CE QUE FAIT CE SCRIPT AUJOURD'HUI, dans chaque page *.html du dossier donné :
  1. tout lien encore écrit href="/va/…&amp;to=<adresse Amazon>" redevient href="<adresse Amazon>"
     (octet pour octet : même tag, même produit) — filet pour une page qui l'aurait gardé ;
  2. une page qui porte au moins un lien Amazon direct reçoit, juste avant </body>, le petit script
     id="clic-amazon" : au clic (ou clic du milieu) sur un lien Amazon, il appelle
     navigator.sendBeacon("/api/clic", …) avec l'adresse du lien, le chemin de la page et l'adresse de
     la page (pour ?src=). Il ne touche pas au href, n'appelle pas preventDefault, ne pose aucun
     témoin, n'envoie rien à un tiers ; sendBeacon met l'envoi en file sans retenir la navigation.
     Sans sendBeacon (navigateur ancien), rien n'est envoyé et le lien marche pareil.
La Function functions/api/clic.js écrit le clic dans le même KV et au même format que /va/
(clé clics_<site>_<jour>, champs total, reseaux, pages, produits, clics[] avec agent et sf) :
/api/stats/clics rend les mêmes champs. La route /va/ reste en service pour les liens déjà partagés.
Les attributs rel, target, class des liens ne sont pas touchés.
Idempotent : une page qui porte déjà id="clic-amazon" ne reçoit pas un second script.

Jumeaux de l'ANCIEN script (/va/), non touchés le 15/11/2026, chacun dans son projet :
  ClaudeGTARoller/outils/va_liens.py, ClaudePlumo/va_liens.py.

    python3 va_liens.py [dossier]      (défaut : le dossier courant)
Sortie toujours 0 (sauf --strict) : un échec laisse les pages telles quelles, il ne bloque jamais une
mise en ligne."""
import os, re, sys

AMAZON = r"https?://(?:[a-z0-9-]+\.)*(?:amazon\.[a-z.]{2,10}|amzn\.(?:to|eu))/[^\"'\s]*"
LIEN = re.compile(r"""href=(["'])(""" + AMAZON + r""")\1""", re.I)
LIEN_VA = re.compile(r"""href=(["'])/va/[^"'\s]*?[?&](?:amp;)?to=(""" + AMAZON + r""")\1""", re.I)
EXCLUS = {".git", "node_modules", "functions", "__pycache__", ".github"}
MARQUE = 'id="clic-amazon"'

SCRIPT = ('<script id="clic-amazon">(function(){'
          'var R=/^https?:\\/\\/(?:[a-z0-9-]+\\.)*(?:amazon\\.[a-z.]{2,10}|amzn\\.(?:to|eu))\\//i;'
          'function f(e){try{if(e.type==="auxclick"&&e.button!==1)return;'
          'var a=e.target&&e.target.closest?e.target.closest("a[href]"):null;'
          'if(!a||!R.test(a.href)||!navigator.sendBeacon)return;'
          'var d=new URLSearchParams();d.set("to",a.href);d.set("p",location.pathname);d.set("de",location.href);'
          'navigator.sendBeacon("/api/clic",d);}catch(x){}}'
          'document.addEventListener("click",f,true);document.addEventListener("auxclick",f,true);'
          '})();</script>\n')


def reecrire_texte(texte):
    """Rend (texte, liens /va/ remis en direct, script posé 0/1)."""
    n = [0]

    def direct(m):
        n[0] += 1
        return "href=%s%s%s" % (m.group(1), m.group(2), m.group(1))
    texte = LIEN_VA.sub(direct, texte)
    pose = 0
    if MARQUE not in texte and LIEN.search(texte):
        i = texte.lower().rfind("</body>")
        texte = (texte[:i] + SCRIPT + texte[i:]) if i >= 0 else (texte + SCRIPT)
        pose = 1
    return texte, n[0], pose


def reecrire_dossier(dossier):
    pages = remis = scripts = 0
    for dp, dns, fns in os.walk(dossier):
        dns[:] = [d for d in dns if d not in EXCLUS]
        for fn in fns:
            if not fn.endswith(".html"):
                continue
            chemin = os.path.join(dp, fn)
            try:
                with open(chemin, "rb") as f:
                    texte = f.read().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            neuf, n, s = reecrire_texte(texte)
            if neuf != texte:
                with open(chemin, "wb") as f:
                    f.write(neuf.encode("utf-8"))
                pages += 1
                remis += n
                scripts += s
    return pages, remis, scripts


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dossier = args[0] if args else "."
    try:
        p, n, s = reecrire_dossier(dossier)
        print("va_liens : liens Amazon directs ; %d lien(s) /va/ remis en direct, script clic-amazon pose "
              "sur %d page(s), %d page(s) modifiee(s) dans %s" % (n, s, p, os.path.abspath(dossier)))
        return 0
    except Exception as e:  # noqa: BLE001
        print("va_liens : ECHEC %s: %s (pages laissees telles quelles)" % (type(e).__name__, e))
        return 1 if "--strict" in sys.argv else 0


if __name__ == "__main__":
    sys.exit(main())
