// Lien de passage compté vers Amazon : /va/<produit>?p=<page>&to=<adresse Amazon d'origine>
// Écrit le 10/11/2026 par un sous-agent de l'equipe (décision du propriétaire du 10/11/2026, 14 h).
// Note le clic (jour, heure, page, réseau d'arrivée, produit) dans le KV, puis renvoie en 302 vers
// l'adresse Amazon d'origine, à l'octet près (même tag, même produit). Les liens des pages sont
// réécrits par va_liens.py. Lecture : GET /api/stats/clics?jour=AAAA-MM-JJ
// Réseau : ?src= (ou utm_source) de la page d'où part le clic, lu dans son Referer ; sinon l'hôte
// d'un Referer extérieur (page embarquée ailleurs) ; sinon le site lui-même (« site:<hôte> »).
// Aucune donnée sur la personne : ni adresse IP, ni identifiant, ni témoin.
// Jumeaux : fonctions /va/ de Plumo et du site roller (functions/va/[[chemin]].js), routes /va/
// du Worker de GTA (site/_worker.js). Corriger l'un, c'est corriger les trois.
// Champs `agent` (famille d'agent utilisateur : navigateur / outil / vide) et `sf` (en-têtes
// Sec-Fetch-Mode/Sec-Fetch-Dest telles que reçues, ou « absents ») ajoutés le 11/11/2026 (poste 4,
// dossier clics-nocturnes-roller-compteur-sans-agent-utilisateur) : ne changent ni le filtre des
// robots connus ni la redirection, ils ne font qu'armer la mesure demandée pour les clics qui
// passent déjà ce filtre.
// ⛔ 15/11/2026 : les PAGES ne passent plus par /va/ (décision de plateforme du projet, règles Amazon sur
// les « Redirecting Links ») : va_liens.py laisse les liens Amazon directs et le clic est compté par
// functions/api/clic.js (sendBeacon), même KV, même format. Cette route reste en service pour les
// liens /va/ déjà partagés ou gardés en cache : elle compte et redirige comme avant.
const ROBOTS_VA = /bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|curl|wget|python|node-fetch|headless|lighthouse|monitor/i;
const DEST_VA = /^https?:\/\/(?:[a-z0-9-]+\.)*(?:amazon\.[a-z.]{2,10}|amzn\.(?:to|eu))\/[^\s"'<>]*$/i;
const AGENT_NAVIGATEUR_VA = /Mozilla\/5\.0.*(Chrome\/|CriOS\/|Firefox\/|FxiOS\/|Version\/[\d.]+ Safari|Edg\/|OPR\/|SamsungBrowser\/)/i;
function familleAgentVa(ua) {
  if (!ua) return "vide";
  return AGENT_NAVIGATEUR_VA.test(ua) ? "navigateur" : "outil";
}
function secFetchVa(request) {
  const mode = request.headers.get("sec-fetch-mode") || "";
  const dest = request.headers.get("sec-fetch-dest") || "";
  return mode || dest ? mode + "/" + dest : "absents";
}
function jourParisVa(d = new Date()) {
  return new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}
function heureParisVa(d = new Date()) {
  return new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(d);
}
function lireClicVa(request, site) {
  const brut = request.url;
  const m = /[?&]to=/.exec(brut);
  if (!m) return null;
  const dest = brut.slice(m.index + 4);
  if (!DEST_VA.test(dest)) return null;
  const u = new URL(brut.slice(0, m.index));
  let produit = "";
  try { produit = decodeURIComponent(u.pathname.replace(/^\/va\/?/, "")); } catch (e) {}
  produit = produit.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 40) || "inconnu";
  let page = (u.searchParams.get("p") || "").replace(/[^A-Za-z0-9/._~-]/g, "").slice(0, 200);
  let reseau = "", origine = "site";
  const ref = request.headers.get("referer") || "";
  try {
    if (ref) {
      const r = new URL(ref);
      if (!page && r.hostname === u.hostname) page = r.pathname.slice(0, 200);
      const s = (r.searchParams.get("src") || r.searchParams.get("utm_source") || "").toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 20);
      if (s) { reseau = s; origine = "src"; }
      else if (r.hostname !== u.hostname && !r.hostname.endsWith("." + site) && r.hostname !== site) { reseau = r.hostname.slice(0, 60); origine = "referent"; }
    }
  } catch (e) {}
  if (!reseau) reseau = "site:" + site;
  return { dest, produit, page: page || "inconnue", reseau, origine };
}
async function noterClicVa(kv, site, c) {
  const k = "clics_" + site + "_" + jourParisVa();
  const v = JSON.parse((await kv.get(k)) || '{"total":0,"reseaux":{},"pages":{},"produits":{},"clics":[]}');
  v.total++;
  v.reseaux[c.reseau] = (v.reseaux[c.reseau] || 0) + 1;
  v.pages[c.page] = (v.pages[c.page] || 0) + 1;
  v.produits[c.produit] = (v.produits[c.produit] || 0) + 1;
  if (v.clics.length < 5000) v.clics.push({ heure: heureParisVa(), page: c.page, reseau: c.reseau, origine: c.origine, produit: c.produit, agent: c.agent || "", sf: c.sf || "" });
  else v.clics_non_detailles = (v.clics_non_detailles || 0) + 1;
  await kv.put(k, JSON.stringify(v), { expirationTtl: 400 * 86400 });
}
function reponseVa(request, kv, site, attendre) {
  const c = lireClicVa(request, site);
  if (!c) return new Response("Lien inconnu.", { status: 404, headers: { "Content-Type": "text/plain; charset=utf-8", "X-Robots-Tag": "noindex, nofollow" } });
  const ua = request.headers.get("user-agent") || "";
  if (kv && !ROBOTS_VA.test(ua)) {
    c.agent = familleAgentVa(ua);
    c.sf = secFetchVa(request);
    attendre(noterClicVa(kv, site, c).catch(() => {}));
  }
  return new Response(null, { status: 302, headers: { "Location": c.dest, "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" } });
}
async function statsClicsVa(request, kv, site) {
  const url = new URL(request.url);
  const jour = url.searchParams.get("jour") || jourParisVa();
  const h = { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(jour)) return new Response(JSON.stringify({ error: { code: "jour", message: "forme AAAA-MM-JJ" } }), { status: 400, headers: h });
  if (!kv) return new Response(JSON.stringify({ error: { code: "config", message: "KV non relié" } }), { status: 500, headers: h });
  const v = await kv.get("clics_" + site + "_" + jour);
  return new Response(JSON.stringify({ site, jour, compte_depuis: "2026-11-10", ...(v ? JSON.parse(v) : { total: 0, reseaux: {}, pages: {}, produits: {}, clics: [] }) }), { headers: h });
}

const SITE_VA = "rollerskateaesthetic.com";
export function onRequestGet(ctx) { return reponseVa(ctx.request, ctx.env.CLICS, SITE_VA, p => ctx.waitUntil(p)); }
export function onRequestHead(ctx) { return reponseVa(ctx.request, null, SITE_VA, () => {}); }
