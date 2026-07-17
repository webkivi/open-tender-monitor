import "./private-config.js";

const DEFAULTS = {
  enabled: false,
  rssUrl: "",
  rssUrls: [],
  backendUrl: "",
  ingestToken: "",
  periodSeconds: 45,
  initializedFeeds: [],
  ...(self.PRIVATE_DEFAULTS || {}),
};

chrome.runtime.onInstalled.addListener(async () => {
  const current = await chrome.storage.local.get(DEFAULTS);
  if (!current.rssUrls.length && current.rssUrl) current.rssUrls = [current.rssUrl];
  if (!current.performanceTuned && current.periodSeconds === 60) current.periodSeconds = 45;
  current.performanceTuned = true;
  await chrome.storage.local.set(current);
  await schedule(current.periodSeconds);
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "eis-rss-poll") pull().catch((error) => chrome.storage.local.set({ lastError: String(error), lastCheckedAt: new Date().toISOString() }));
});

async function schedule(seconds) {
  await chrome.alarms.clear("eis-rss-poll");
  chrome.alarms.create("eis-rss-poll", { periodInMinutes: Math.max(0.75, Number(seconds || 45) / 60) });
}

function textOf(xml, tag) {
  const match = xml.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`, "i"));
  return match ? match[1].replace(/<!\[CDATA\[|\]\]>/g, "").replace(/<[^>]+>/g, "").trim() : "";
}

function parseFeed(xml) {
  const blocks = xml.match(/<(?:item|entry)\b[\s\S]*?<\/(?:item|entry)>/gi) || [];
  return blocks.map((block) => {
    const linkTag = block.match(/<link[^>]+href=["']([^"']+)["'][^>]*>/i);
    const link = linkTag?.[1] || textOf(block, "link") || textOf(block, "guid");
    return { title: textOf(block, "title"), url: link, summary: textOf(block, "description") || textOf(block, "summary"), published_at: textOf(block, "pubDate") || textOf(block, "updated") };
  }).filter((item) => item.title && /^https?:\/\//.test(item.url));
}

async function pull() {
  const startedAt = Date.now();
  const settings = await chrome.storage.local.get(DEFAULTS);
  await schedule(settings.periodSeconds);
  if (!settings.enabled) throw new Error("RSS receiving is disabled");
  if (!settings.backendUrl || !settings.ingestToken) throw new Error("Local monitor connection is not configured");
  const rssUrls = configuredUrls(settings);
  if (!rssUrls.length) throw new Error("RSS URL is not configured");
  const initializedFeeds = new Set(settings.initializedFeeds || []);
  const feedResults = await Promise.all(rssUrls.map((rssUrl) => fetchFeed(rssUrl, initializedFeeds.has(rssUrl))));
  const items = feedResults.flatMap((result) => result.items);
  const feedErrors = feedResults.filter((result) => result.error).map((result) => `${result.url}: ${result.error}`);
  const completedFeeds = feedResults.filter((result) => !result.error).map((result) => result.url);
  if (!items.length && feedErrors.length) throw new Error(feedErrors.join("\n"));
  if (!items.length) throw new Error("RSS did not contain tender entries");
  const uniqueItems = [...items.reduce((unique, item) => {
    const existing = unique.get(item.url);
    unique.set(item.url, existing ? { ...existing, suppressNotifications: existing.suppressNotifications && item.suppressNotifications, rss_observed_at: existing.rss_observed_at < item.rss_observed_at ? existing.rss_observed_at : item.rss_observed_at } : item);
    return unique;
  }, new Map()).values()];
  let delivered = 0;
  for (const item of uniqueItems) {
    const result = await fetch(`${settings.backendUrl.replace(/\/$/, "")}/api/intake/eis`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Ingest-Token": settings.ingestToken },
      body: JSON.stringify({ ...item, suppress_notifications: item.suppressNotifications })
    });
    if (!result.ok) throw new Error(`Local monitor returned HTTP ${result.status}`);
    delivered += 1;
  }
  const warning = feedErrors.length ? `Unavailable feeds: ${feedErrors.length}` : "";
  await sendHeartbeat(settings, { feed_count: rssUrls.length, item_count: uniqueItems.length, error_count: feedErrors.length, duration_ms: Date.now() - startedAt });
  await chrome.storage.local.set({ initializedFeeds: [...new Set([...initializedFeeds, ...completedFeeds])], lastCheckedAt: new Date().toISOString(), lastError: warning, lastFound: uniqueItems.length, lastDelivered: delivered });
  return { found: uniqueItems.length, delivered, warning };
}

async function fetchFeed(url, initialized) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const observedAt = new Date().toISOString();
    return { url, items: parseFeed(await response.text()).map((item) => ({ ...item, rss_observed_at: observedAt, suppressNotifications: !initialized })) };
  } catch (error) {
    return { url, items: [], error: error.message || String(error) };
  }
}

async function sendHeartbeat(settings, payload) {
  const result = await fetch(`${settings.backendUrl.replace(/\/$/, "")}/api/heartbeat/eis`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Ingest-Token": settings.ingestToken },
    body: JSON.stringify(payload)
  });
  if (!result.ok) throw new Error(`Local monitor heartbeat returned HTTP ${result.status}`);
}

function configuredUrls(settings) {
  const urls = Array.isArray(settings.rssUrls) && settings.rssUrls.length ? settings.rssUrls : [settings.rssUrl];
  return [...new Set(urls.map((url) => String(url).trim()).filter((url) => /^https:\/\/zakupki\.gov\.ru\//.test(url)))];
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "save") schedule(message.settings.periodSeconds).then(() => chrome.storage.local.set(message.settings)).then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, error: String(error) }));
  if (message?.type === "test") pull().then((result) => sendResponse({ ok: true, result })).catch((error) => sendResponse({ ok: false, error: String(error) }));
  return true;
});
