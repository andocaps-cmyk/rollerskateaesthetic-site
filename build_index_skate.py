#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LA PAGE /skate/ : UNE PORTE VERS TOUTES LES PAGES SKATE.

Pose le 26/11/2026 par l'agent de remise en route (passe du matin du chef des projets).
Mesure du jour : l'accueil lie 27 pages /skate/ sur 237, l'adresse /skate/ rendait 404, et 132 pages
/skate/ n'etaient liees par AUCUNE autre page du site (seul le sitemap les nommait). Une page sans lien
interne recoit peu de poids de Google et aucun visiteur ne la trouve en naviguant.

Ce script ecrit skate/index.html : la liste de toutes les pages skate/<x>/index.html, avec leur <h1>
(a defaut leur <title>) et leur meta description, deja publiees ; il n'ecrit AUCUNE affirmation neuve
sur le roller. Il ajoute /skate/ au sitemap s'il n'y est pas. Il est idempotent : la page ne change
que si la liste change (la date affichee est celle de la page la plus recente de la liste).

  python3 build_index_skate.py             # ecrit la page (et le sitemap si besoin)
  python3 build_index_skate.py --verifier  # n'ecrit rien ; sort 1 si une page skate manque a l'index

Branche dans .github/workflows/fournee.yml, avant le menu : une page skate ajoutee demain y entre seule.
"""
import datetime, html, pathlib, re, sys

RACINE = pathlib.Path(__file__).resolve().parent
SITE = "https://rollerskateaesthetic.com"
MOIS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
        "October", "November", "December"]


def lire(motif, texte):
    m = re.search(motif, texte, re.S | re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def pages():
    out = []
    for f in sorted((RACINE / "skate").glob("*/index.html")):
        s = f.read_text(encoding="utf-8", errors="replace")
        tete = s.split("</head>", 1)[0]
        if re.search(r'<meta name="robots" content="[^"]*noindex', tete, re.I):
            continue
        titre = lire(r"<h1[^>]*>(.*?)</h1>", s) or lire(r"<title[^>]*>(.*?)</title>", tete) or f.parent.name
        desc = lire(r'<meta name="description" content="([^"]*)"', tete)
        mod = lire(r'"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2})', s) or lire(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', s)
        out.append((f.parent.name, titre, desc, mod))
    return out


def gabarit(liste):
    dates = [m for _, _, _, m in liste if m]
    jour = max(dates) if dates else "2026-11-26"
    d = datetime.date.fromisoformat(jour)
    visible = "%d %s %d" % (d.day, MOIS[d.month - 1], d.year)
    n = len(liste)
    titre = "All Roller Skating Answers for Beginners"
    desc = "Every beginner roller skating answer on Roller Skate Aesthetic in one list: %d short pages on falling, stopping, fit, wheels and gear." % n
    items = "\n".join(
        '<li><a href="%s/skate/%s/">%s</a>%s</li>' % (
            SITE, slug, html.escape(t), (" &mdash; <span class=\"d\">%s</span>" % html.escape(ds)) if ds else "")
        for slug, t, ds, _ in sorted(liste, key=lambda x: x[1].lower()))
    ld = ('{"@context":"https://schema.org","@type":"CollectionPage","name":"%s","description":"%s","url":"%s/skate/",'
          '"author":{"@type":"Person","name":"Cass","url":"%s/about/"},'
          '"publisher":{"@type":"Organization","name":"Roller Skate Aesthetic","url":"%s/"},'
          '"inLanguage":"en","dateModified":"%s"}') % (titre, desc, SITE, SITE, SITE, jour)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titre}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{SITE}/skate/">
<link rel="alternate" type="application/rss+xml" title="Roller Skate Aesthetic" href="{SITE}/feed.xml">
<meta property="og:type" content="website">
<meta property="og:title" content="{titre}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:url" content="{SITE}/skate/">
<meta property="og:image" content="{SITE}/pins/pin_19_pastel.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,700;9..144,900&family=Jost:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#F7EEE5;color:#2C2230;font-family:'Jost',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:18px;line-height:1.7;-webkit-font-smoothing:antialiased;overflow-wrap:break-word}}
.wrap{{max-width:720px;margin:0 auto;padding:0 24px}}
h1{{font-family:'Fraunces',Georgia,serif;font-size:clamp(1.9rem,5.4vw,2.9rem);font-weight:900;line-height:1.15;margin:0 0 .45em}}
.byline{{font-size:.9rem;opacity:.65;margin:-.4rem 0 1.4rem;letter-spacing:.02em}}
.eyebrow{{font-size:.72rem;letter-spacing:.28em;text-transform:uppercase;font-weight:600;opacity:.65;margin:0 0 1.4em}}
main{{padding:52px 0 40px}}
ul{{padding-left:1.2em}} li{{margin:0 0 .7em}}
.d{{opacity:.75;font-size:.92rem}}
a{{color:#2C2230;text-decoration-color:#E88A74;text-underline-offset:3px;text-decoration-thickness:2px}}
a:hover{{color:#E88A74}}
footer{{border-top:3px solid #2C2230;background:#EEE0D4;padding:28px 0;margin-top:52px;font-size:.9rem;opacity:.8}}
footer p{{margin:0 0 .4em}}
@media (max-width:520px){{body{{font-size:17px}}.wrap{{padding:0 16px}}}}
</style>
<script type="application/ld+json">
{ld}
</script>
</head>
<body>
<main class="wrap">
<p class="eyebrow">Beginner roller skating</p>
<h1>{titre}</h1>
<p class="byline">Updated {visible} &middot; by <a href="{SITE}/about/">Cass</a> &middot; written with an AI assistant</p>
<p>{n} short answers to the questions beginners ask, from the first wobble to the first stop. Start with the <a href="{SITE}/">beginner&rsquo;s guide</a> if you are new, or pick a question below.</p>
<ul>
{items}
</ul>
</main>
<footer><div class="wrap">
<p>Written with an AI assistant from a skater's notes.</p>
<p><a href="{SITE}/">Home</a> &middot; <a href="{SITE}/privacy/">Privacy</a> &middot; <a href="{SITE}/contact/">Contact</a> &middot; <a href="{SITE}/about/">About</a></p>
<p>As an Amazon Associate I earn from qualifying purchases.</p>
</div></footer>
</body>
</html>
"""


def main():
    liste = pages()
    cible = RACINE / "skate" / "index.html"
    if "--verifier" in sys.argv:
        actuel = cible.read_bytes().decode("utf-8") if cible.is_file() else ""
        manque = [s for s, *_ in liste if "/skate/%s/\"" % s not in actuel]
        print("index /skate/ : %d pages, %d absente(s) de l'index%s" % (len(liste), len(manque), (" : " + ", ".join(manque[:10])) if manque else ""))
        return 1 if manque else 0
    nouveau = gabarit(liste)
    if not cible.is_file() or cible.read_bytes().decode("utf-8") != nouveau:
        cible.write_bytes(nouveau.encode("utf-8"))
        print("skate/index.html ecrit : %d pages" % len(liste))
    else:
        print("skate/index.html inchange : %d pages" % len(liste))
    plan = RACINE / "sitemap.xml"
    t = plan.read_bytes().decode("utf-8")
    if "<loc>%s/skate/</loc>" % SITE not in t:
        bloc = "  <url>\n    <loc>%s/skate/</loc>\n    <lastmod>%s</lastmod>\n    <priority>0.8</priority>\n  </url>\n" % (
            SITE, datetime.date.today().isoformat())
        plan.write_bytes(t.replace("</urlset>", bloc + "</urlset>").encode("utf-8"))
        print("sitemap.xml : /skate/ ajoutee")
    return 0


if __name__ == "__main__":
    sys.exit(main())
