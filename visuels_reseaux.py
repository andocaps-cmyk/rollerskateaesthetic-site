#!/usr/bin/env python3
"""Visuels des publications Instagram et YouTube, tires de la page et de son epingle. Pillow + ffmpeg, aucun modele.

Ecrit le 29/10/2026 (un document interne du projet).
Gabarit visuel des epingles : fond creme, encre prune, accents corail, lilas et sauge, titres en Fraunces Black.

DIAPOS d'une page (diapos()) :
- la couverture : l'epingle de la page (og:image, dans pins/), posee sans recadrage sur le format demande ;
- 2 ou 3 diapos d'etapes : une phrase du paragraphe d'ouverture de la page chacune (etapes()).
Instagram : 1080 x 1350 (4:5), JPEG, couverture + etapes = carrousel de 3 ou 4 elements (10 au plus).
YouTube : 1080 x 1920, couverture, etapes, puis une diapo de fin ; video() les enchaine (20 a 40 s, sans son).

  python3 visuels_reseaux.py --instagram [--toutes|CLE ...]   ecrit ig/<slug>-<n>.jpg (servis par le site)
  python3 visuels_reseaux.py --video CLE SORTIE.mp4           fabrique la video d'une page
"""
import argparse, os, re, shutil, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFont

ICI = os.path.dirname(os.path.abspath(__file__))
FOND, ENCRE, CORAIL, LILAS, SAUGE = "#f7eee5", "#2c2230", "#e88a74", "#b7a2c4", "#9cae9a"
TITRE = os.path.join(ICI, "polices", "FrauncesBlackDisplay.ttf")
SANS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"]
DOSSIER_IG = "ig"
IG = (1080, 1350)
YT = (1080, 1920)
ETAPES_MAX = 3
PHRASE_MAX = 190
SECONDES_COUV, SECONDES_FIN = 5.0, 4.0


def police(chemin, taille):
    if isinstance(chemin, list):
        chemin = next((c for c in chemin if os.path.exists(c)), None)
    if not chemin or not os.path.exists(chemin):
        sys.exit("ERREUR: police introuvable (%s)" % chemin)
    return ImageFont.truetype(chemin, taille)


def slug(cle):
    return cle.replace("/", "-")


def etapes(page):
    """2 ou 3 phrases du paragraphe d'ouverture (a defaut de la meta-description), sans mention ni formule."""
    import publier_threads as pt
    for source in (page["lede"], page["meta"]):
        out = [s for s in pt.phrases(source) if not pt.JUNK.search(s) and s[-1] in ".!?" and len(s) <= PHRASE_MAX]
        if len(out) >= 2:
            return out[:ETAPES_MAX]
    return []


def titre(page):
    s = open(os.path.join(ICI, page["cle"], "index.html"), encoding="utf-8").read()
    import publier_threads as pt
    h1 = re.search(r"<h1>(.*?)</h1>", s, re.S)
    return pt.texte_html(h1.group(1)) if h1 else page["cle"].split("/")[-1].replace("-", " ")


def epingle(page):
    s = open(os.path.join(ICI, page["cle"], "index.html"), encoding="utf-8").read()
    og = re.search(r'property="og:image" content="[^"]*/(pins/[^"/]+)"', s)
    chemin = os.path.join(ICI, og.group(1)) if og else None
    return chemin if chemin and os.path.isfile(chemin) else None


def couper(texte, fonte, largeur, dessin):
    lignes, ligne = [], ""
    for mot in texte.split():
        essai = (ligne + " " + mot).strip()
        if dessin.textlength(essai, font=fonte) <= largeur or not ligne:
            ligne = essai
        else:
            lignes.append(ligne)
            ligne = mot
    if ligne:
        lignes.append(ligne)
    return lignes


def etoile(d, x, y, r, couleur):
    """Etoile a quatre branches des epingles."""
    k = r * 0.28
    d.polygon([(x, y - r), (x + k, y - k), (x + r, y), (x + k, y + k), (x, y + r), (x - k, y + k), (x - r, y), (x - k, y - k)],
              fill=couleur)


def cadre(taille):
    im = Image.new("RGB", taille, FOND)
    d = ImageDraw.Draw(im)
    w, h = taille
    etoile(d, 0.11 * w, 0.09 * h, 0.03 * w, LILAS)
    etoile(d, 0.88 * w, 0.09 * h, 0.03 * w, CORAIL)
    etoile(d, 0.10 * w, 0.88 * h, 0.025 * w, CORAIL)
    etoile(d, 0.89 * w, 0.88 * h, 0.025 * w, SAUGE)
    pied = police(SANS, int(0.031 * w))
    t = "ROLLER SKATE AESTHETIC"
    d.text(((w - d.textlength(t, font=pied)) / 2, 0.93 * h), t, font=pied, fill=ENCRE)
    return im, d


def diapo_texte(taille, haut, corps, couleur_corps=ENCRE):
    """Une diapo : etiquette en capitales, puis un texte en Fraunces, centre, le plus grand qui tienne."""
    im, d = cadre(taille)
    w, h = taille
    eti = police(SANS, int(0.034 * w))
    d.text(((w - d.textlength(haut, font=eti)) / 2, 0.20 * h), haut, font=eti, fill=CORAIL)
    zone_l, zone_h = 0.80 * w, 0.52 * h
    for t in range(int(0.085 * w), int(0.04 * w), -2):
        f = police(TITRE, t)
        lignes = couper(corps, f, zone_l, d)
        pas = int(t * 1.18)
        if len(lignes) * pas <= zone_h and max(d.textlength(l, font=f) for l in lignes) <= zone_l:
            break
    y = 0.30 * h + (zone_h - len(lignes) * pas) / 2
    for l in lignes:
        d.text(((w - d.textlength(l, font=f)) / 2, y), l, font=f, fill=couleur_corps)
        y += pas
    return im


def couverture(page, taille):
    """L'epingle entiere sur le format demande, sans recadrage : le fond creme comble les marges."""
    chemin = epingle(page)
    if not chemin:
        return None
    pin = Image.open(chemin).convert("RGB")
    w, h = taille
    r = min(w / pin.width, h / pin.height)
    pin = pin.resize((round(pin.width * r), round(pin.height * r)), Image.LANCZOS)
    im = Image.new("RGB", taille, FOND)
    im.paste(pin, ((w - pin.width) // 2, (h - pin.height) // 2))
    return im


def diapos(page, taille):
    """[couverture, etape 1, etape 2(, etape 3)] ; liste vide si la page n'a pas d'epingle ou pas deux phrases."""
    couv, ph = couverture(page, taille), etapes(page)
    if not couv or len(ph) < 2:
        return []
    return [couv] + [diapo_texte(taille, "STEP %d OF %d" % (i + 1, len(ph)), s) for i, s in enumerate(ph)]


def ecrire_instagram(page):
    """ig/<slug>-<n>.jpg ; rend la liste des chemins (vide si la page ne s'y prete pas)."""
    out = []
    os.makedirs(os.path.join(ICI, DOSSIER_IG), exist_ok=True)
    for i, im in enumerate(diapos(page, IG), 1):
        chemin = os.path.join(DOSSIER_IG, "%s-%d.jpg" % (slug(page["cle"]), i))
        im.save(os.path.join(ICI, chemin), "JPEG", quality=86, optimize=True, progressive=False)
        out.append(chemin)
    return out


def images_instagram(page):
    """Chemins ig/ deja fabriques pour la page, dans l'ordre."""
    out, n = [], 1
    while os.path.isfile(os.path.join(ICI, DOSSIER_IG, "%s-%d.jpg" % (slug(page["cle"]), n))):
        out.append("%s/%s-%d.jpg" % (DOSSIER_IG, slug(page["cle"]), n))
        n += 1
    return out


def ffmpeg():
    for c in (shutil.which("ffmpeg"),):
        if c and os.path.exists(c):
            return c
    sys.exit("ERREUR: ffmpeg introuvable")


def duree_etape(phrase):
    """Temps de lecture : 2,5 s + 0,06 s par caractere, entre 5 et 9 s."""
    return max(5.0, min(9.0, 2.5 + 0.06 * len(phrase)))


def video(page, sortie):
    """Video verticale 1080 x 1920, sans son : couverture, etapes, fin. Rend sa duree en secondes (None si impossible)."""
    images = diapos(page, YT)
    if not images:
        return None
    fin = diapo_texte(YT, "FULL GUIDE", "rollerskateaesthetic.com", CORAIL)
    ph = etapes(page)
    durees = [SECONDES_COUV] + [duree_etape(s) for s in ph] + [SECONDES_FIN]
    total = sum(durees)
    if total > 40:
        durees = [d * 40 / total for d in durees]
    images.append(fin)
    tmp = tempfile.mkdtemp(prefix="video_")
    try:
        cmd = [ffmpeg(), "-y", "-loglevel", "error"]
        for i, (im, d) in enumerate(zip(images, durees)):
            p = os.path.join(tmp, "%02d.png" % i)
            im.save(p)
            cmd += ["-loop", "1", "-framerate", "30", "-t", "%.2f" % d, "-i", p]
        filtres = []
        for i, d in enumerate(durees):
            filtres.append("[%d:v]format=yuv420p,fade=t=in:st=0:d=0.4,fade=t=out:st=%.2f:d=0.4,setsar=1[v%d]" % (i, d - 0.4, i))
        filtres.append("".join("[v%d]" % i for i in range(len(durees))) + "concat=n=%d:v=1:a=0[out]" % len(durees))
        cmd += ["-filter_complex", ";".join(filtres), "-map", "[out]", "-an", "-c:v", "libx264", "-preset", "medium",
                "-crf", "22", "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart", sortie]
        subprocess.run(cmd, check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return round(sum(durees), 1)


def main():
    import publier_threads as pt
    ap = argparse.ArgumentParser()
    ap.add_argument("--instagram", action="store_true")
    ap.add_argument("--toutes", action="store_true")
    ap.add_argument("--video", nargs=2, metavar=("CLE", "SORTIE"))
    ap.add_argument("cles", nargs="*")
    a = ap.parse_args()
    os.chdir(ICI)
    pages = dict((p["cle"], p) for p in pt.lire_pages())
    if a.video:
        d = video(pages[a.video[0]], a.video[1])
        print("%s -> %s (%s s)" % (a.video[0], a.video[1], d))
        return 0 if d else 1
    if a.instagram:
        choix = list(pages.values()) if a.toutes else [pages[c] for c in a.cles]
        faites, sans = 0, []
        for p in choix:
            if ecrire_instagram(p):
                faites += 1
            else:
                sans.append(p["cle"])
        print("%d pages avec carrousel dans %s/ ; sans (pas d'epingle ou moins de deux phrases) : %d %s"
              % (faites, DOSSIER_IG, len(sans), " ".join(sans[:20])))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
