// Comptage d'un clic vers Amazon SANS redirection : POST /api/clic (navigator.sendBeacon).
// Écrit le 15/11/2026 (décision de plateforme du projet, un document interne du 15/11 02 h 36) :
// les pages portent des liens DIRECTS vers Amazon ; le script id="clic-amazon" posé par va_liens.py
// envoie ici, au clic, un corps application/x-www-form-urlencoded :
//   to = adresse Amazon du lien (a.href, telle que le navigateur la suit)
//   p  = chemin de la page d'où part le clic
//   de = adresse complète de cette page (seul ?src= ou ?utm_source= en est lu, rien d'autre n'est gardé)
// Le clic s'écrit dans le MÊME KV (CLICS), sous la MÊME clé (clics_<site>_<jour Paris>) et au MÊME
// format que /va/ (functions/va/[[chemin]].js) : total, reseaux, pages, produits, clics[] avec
// heure, page, reseau, origine, produit, agent, sf. /api/stats/clics ne change pas.
// Produit : même règle que l'ancien va_liens.py (ASIN, préfixe « panier- » pour cart/add) ; depuis le
// 15/11/2026, un panier de plusieurs articles se nomme « kit-<n>articles ».
// sf vaut ici ce que le navigateur envoie pour une balise (en général « no-cors/empty »), là où
// /va/ notait une navigation (« navigate/document ») : c'est ce qui distingue les deux voies.
// Répond toujours 204 sans corps : rien à attendre pour la page, rien qui retienne la navigation.
// Aucune donnée sur la personne : ni adresse IP, ni identifiant, ni témoin.
const ROBOTS_CLIC = /bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|curl|wget|python|node-fetch|headless|lighthouse|monitor/i;
const DEST_CLIC = /^https?:\/\/(?:[a-z0-9-]+\.)*(?:amazon\.[a-z.]{2,10}|amzn\.(?:to|eu))\/[^\s"'<>]*$/i;
const AGENT_NAVIGATEUR_CLIC = /Mozilla\/5\.0.*(Chrome\/|CriOS\/|Firefox\/|FxiOS\/|Version\/[\d.]+ Safari|Edg\/|OPR\/|SamsungBrowser\/)/i;
const ASIN_CLIC = [/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/, /ASIN(?:\.1)?=([A-Z0-9]{10})/];
function familleAgentClic(ua) {
  if (!ua) return "vide";
  return AGENT_NAVIGATEUR_CLIC.test(ua) ? "navigateur" : "outil";
}
function secFetchClic(request) {
  const mode = request.headers.get("sec-fetch-mode") || "";
  const dest = request.headers.get("sec-fetch-dest") || "";
  return mode || dest ? mode + "/" + dest : "absents";
}
function jourParisClic(d = new Date()) {
  return new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}
function heureParisClic(d = new Date()) {
  return new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(d);
}
async function produitClic(dest) {
  // 15/11/2026 : bouton « kit » de /tools/starter-kit-cost/kit/ (build_kit_list.py) : un lien panier qui
  // porte plusieurs articles (ASIN.1, ASIN.2, …) se nomme « kit-<n>articles ». La page d'origine est
  // gardée dans le champ page, comme pour tout clic ; le format lu par /api/stats/clics ne change pas.
  if (dest.includes("cart/add")) {
    const n = new Set((dest.match(/[?&]ASIN\.\d+=/g) || []).map(x => x.slice(1))).size;
    if (n >= 2) return "kit-" + n + "articles";
  }
  for (const r of ASIN_CLIC) {
    const m = r.exec(dest);
    if (m) return (dest.includes("cart/add") ? "panier-" : "") + m[1];
  }
  // Même empreinte que l'ancien va_liens.py, qui hachait l'attribut brut (avec &amp;).
  const o = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(dest.replace(/&/g, "&amp;")));
  return "lien-" + [...new Uint8Array(o)].map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 8);
}
async function lireClic(f, request, hote, site) {
  const dest = (f.get("to") || "").slice(0, 2000);
  if (!DEST_CLIC.test(dest)) return null;
  const produit = (await produitClic(dest)).replace(/[^A-Za-z0-9_-]/g, "").slice(0, 40) || "inconnu";
  let page = (f.get("p") || "").replace(/[^A-Za-z0-9/._~-]/g, "").slice(0, 200);
  let reseau = "", origine = "site";
  const ref = f.get("de") || request.headers.get("referer") || "";
  try {
    if (ref) {
      const r = new URL(ref);
      if (!page && r.hostname === hote) page = r.pathname.slice(0, 200);
      const s = (r.searchParams.get("src") || r.searchParams.get("utm_source") || "").toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 20);
      if (s) { reseau = s; origine = "src"; }
      else if (r.hostname !== hote && !r.hostname.endsWith("." + site) && r.hostname !== site) { reseau = r.hostname.slice(0, 60); origine = "referent"; }
    }
  } catch (e) {}
  if (!reseau) reseau = "site:" + site;
  return { produit, page: page || "inconnue", reseau, origine };
}
async function noterClic(kv, site, c) {
  const k = "clics_" + site + "_" + jourParisClic();
  const v = JSON.parse((await kv.get(k)) || '{"total":0,"reseaux":{},"pages":{},"produits":{},"clics":[]}');
  v.total++;
  v.reseaux[c.reseau] = (v.reseaux[c.reseau] || 0) + 1;
  v.pages[c.page] = (v.pages[c.page] || 0) + 1;
  v.produits[c.produit] = (v.produits[c.produit] || 0) + 1;
  if (v.clics.length < 5000) v.clics.push({ heure: heureParisClic(), page: c.page, reseau: c.reseau, origine: c.origine, produit: c.produit, agent: c.agent || "", sf: c.sf || "" });
  else v.clics_non_detailles = (v.clics_non_detailles || 0) + 1;
  await kv.put(k, JSON.stringify(v), { expirationTtl: 400 * 86400 });
}

const SITE_CLIC = "rollerskateaesthetic.com";
const REPONSE_CLIC = () => new Response(null, { status: 204, headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" } });
export async function onRequestPost(ctx) {
  const request = ctx.request, kv = ctx.env.CLICS;
  try {
    const hote = new URL(request.url).hostname;
    // Une balise envoyée depuis une autre origine que le site n'est pas comptée.
    const origin = request.headers.get("origin");
    if (origin) {
      const oh = new URL(origin).hostname;
      if (oh !== hote && oh !== SITE_CLIC && oh !== "www." + SITE_CLIC) return REPONSE_CLIC();
    }
    const ua = request.headers.get("user-agent") || "";
    if (!kv || ROBOTS_CLIC.test(ua)) return REPONSE_CLIC();
    const f = new URLSearchParams((await request.text()).slice(0, 4000));
    const c = await lireClic(f, request, hote, SITE_CLIC);
    if (c) {
      c.agent = familleAgentClic(ua);
      c.sf = secFetchClic(request);
      ctx.waitUntil(noterClic(kv, SITE_CLIC, c).catch(() => {}));
    }
  } catch (e) {}
  return REPONSE_CLIC();
}
