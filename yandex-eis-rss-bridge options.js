const ids = ["enabled", "rssUrls", "backendUrl", "ingestToken", "periodSeconds"];
const elements = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
const status = document.getElementById("status");
const values = await chrome.storage.local.get({ enabled: false, rssUrl: "", rssUrls: [], backendUrl: "", ingestToken: "", periodSeconds: 45, lastError: "", lastCheckedAt: "" });
if (!values.rssUrls.length && values.rssUrl) values.rssUrls = [values.rssUrl];
for (const id of ids) elements[id].type === "checkbox" ? elements[id].checked = values[id] : elements[id].value = values[id];
status.textContent = values.lastError || (values.lastCheckedAt ? `Последняя проверка: ${values.lastCheckedAt}` : "Заполните параметры и сохраните.");
function settings() { return { enabled: elements.enabled.checked, rssUrls: elements.rssUrls.value.split(/\r?\n/).map((url) => url.trim()).filter(Boolean), backendUrl: elements.backendUrl.value.trim(), ingestToken: elements.ingestToken.value.trim(), periodSeconds: Math.max(45, Number(elements.periodSeconds.value || 45)) }; }
document.getElementById("save").onclick = async () => { const result = await chrome.runtime.sendMessage({ type: "save", settings: settings() }); status.textContent = result.ok ? "Сохранено." : result.error; };
document.getElementById("test").onclick = async () => { status.textContent = "Проверка..."; const result = await chrome.runtime.sendMessage({ type: "test" }); status.textContent = result.ok ? `Поток обработан: ${result.result.found} записей.` + (result.result.warning ? ` ${result.result.warning}` : "") : result.error; };
