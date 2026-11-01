const get = (id) => {
    const node = document.getElementById(id);
    if (!node)
        throw new Error(id);
    return node;
};
const escapeHtml = (v) => String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
const notice = (message, error = false) => {
    get("notice").textContent = message;
    get("notice").classList.toggle("error", error);
};
async function api(url, options) {
    const r = await fetch(url, options);
    if (!r.ok) {
        let message = `Error ${r.status}`;
        try {
            const data = await r.json();
            if (typeof data === "object" && data !== null && "detail" in data) {
                const detail = data.detail;
                message = typeof detail === "string" ? detail : JSON.stringify(detail);
            }
        }
        catch {
            /* a bounded fallback for non-JSON HTTP errors */
        }
        throw new Error(message);
    }
    return r.json();
}
const money = (cents, currency) => new Intl.NumberFormat("es-PE", { style: "currency", currency }).format(cents / 100);
let currentBatch = null;
let offset = 0;
async function loadOutcomes() {
    if (!currentBatch)
        return;
    const rows = await api(`/api/imports/${currentBatch.id}/outcomes?limit=20&offset=${offset}`);
    get("quality-caption").textContent =
        `${currentBatch.filename} · línea física de inicio en el archivo original`;
    const labels = {
        accepted: "Válida",
        rejected: "Rechazada",
        duplicated: "Duplicada",
    };
    get("outcomes").innerHTML =
        rows
            .map((r) => `<tr><td>${r.source_row}</td><td><span class="tag ${escapeHtml(r.status)}">${labels[r.status] ?? escapeHtml(r.status)}</span></td><td>${escapeHtml(r.reason)}</td></tr>`)
            .join("") ||
            '<tr><td colspan="3" class="table-empty">No hay filas.</td></tr>';
    get("prev").disabled = offset === 0;
    get("next").disabled = offset + 20 >= currentBatch.total;
    get("page-label").textContent =
        `${Math.min(offset + 1, currentBatch.total)}–${Math.min(offset + 20, currentBatch.total)} de ${currentBatch.total}`;
}
async function load() {
    const period = get("period").value;
    const [summary, runs] = await Promise.all([
        api(`/api/summary?period=${encodeURIComponent(period)}`),
        api("/api/imports"),
    ]);
    for (const key of ["total", "accepted", "rejected", "duplicated"])
        get(key).textContent = summary.totals[key].toLocaleString("es-PE");
    get("import-count").textContent = `${summary.totals.imports} archivos`;
    if (summary.groups.length) {
        const max = Math.max(...summary.groups.map((g) => g.amount_cents));
        get("summary").innerHTML = summary.groups
            .map((g) => `<div class="summary-row"><div class="summary-top"><span>${escapeHtml(g.branch)}</span><strong>${escapeHtml(money(g.amount_cents, g.currency))}</strong></div><p>${g.records} registros · ${escapeHtml(g.period)} · ${escapeHtml(g.currency)}</p><svg class="summary-bar" viewBox="0 0 100 5" preserveAspectRatio="none" aria-hidden="true"><rect width="100" height="5" fill="#eff2eb"/><rect width="${((g.amount_cents / max) * 100).toFixed(2)}" height="5" fill="#759168"/></svg></div>`)
            .join("");
    }
    else {
        get("summary").innerHTML =
            '<div class="empty"><span>◷</span><h3>No hay registros para mostrar</h3><p>Importa un CSV o selecciona otro periodo.</p></div>';
    }
    get("imports").innerHTML =
        runs
            .map((r) => `<tr><td class="file-name">${escapeHtml(r.filename)}</td><td>${escapeHtml(r.created_at.slice(0, 16).replace("T", " "))}</td><td>${r.total}</td><td class="green">${r.accepted}</td><td class="orange">${r.rejected}</td><td>${r.duplicated}</td><td><button class="table-button" data-batch="${r.id}">Ver filas →</button></td></tr>`)
            .join("") ||
            '<tr><td colspan="7" class="table-empty">Todavía no hay importaciones.</td></tr>';
    get("imports")
        .querySelectorAll("[data-batch]")
        .forEach((button) => button.addEventListener("click", () => {
        currentBatch = runs.find((r) => r.id === button.dataset.batch) ?? null;
        offset = 0;
        void loadOutcomes()
            .then(() => get("quality").scrollIntoView({ block: "start" }))
            .catch(showError);
    }));
    if (currentBatch)
        await loadOutcomes();
}
function showError(error) {
    notice(error instanceof Error
        ? error.message
        : "No se pudo completar la operación. Intenta de nuevo.", true);
}
async function busy(button, action) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    try {
        await action();
    }
    catch (e) {
        showError(e);
    }
    finally {
        button.disabled = false;
        button.removeAttribute("aria-busy");
    }
}
get("demo").addEventListener("click", () => {
    void busy(get("demo"), async () => {
        notice("Cargando el ejemplo sintético…");
        const runs = await api("/api/demo", { method: "POST" });
        await load();
        notice(runs.every((r) => r.replayed)
            ? "El ejemplo ya estaba importado. No se duplicó ningún resultado."
            : "Ejemplo sintético importado. Revisa los resultados, las incidencias y las exportaciones.");
        currentBatch = runs[0] ?? null;
        offset = 0;
        await loadOutcomes();
    });
});
const resetMapping = () => {
    get("mapping").hidden = true;
    get("mapping").replaceChildren();
    get("process").disabled = true;
};
get("file").addEventListener("change", resetMapping);
get("delimiter").addEventListener("change", resetMapping);
get("preview").addEventListener("click", () => {
    void busy(get("preview"), async () => {
        const file = get("file").files?.[0];
        if (!file)
            throw new Error("Selecciona un archivo CSV.");
        if (file.size > 5 * 1024 * 1024)
            throw new Error("El archivo supera 5 MiB.");
        const form = new FormData();
        form.append("file", file);
        form.append("delimiter", get("delimiter").value);
        notice("Revisando cabeceras…");
        const result = await api("/api/preview", { method: "POST", body: form });
        const fields = {
            sale_id: "Identificador *",
            branch: "Sucursal *",
            sale_date: "Fecha *",
            amount: "Importe *",
            currency: "Moneda *",
            description: "Descripción (opcional)",
        };
        get("mapping").innerHTML = Object.entries(fields)
            .map(([key, label]) => `<label>${label}<select data-field="${key}" ${key === "description" ? "" : "required"}><option value="">Seleccionar</option>${result.headers.map((h) => `<option value="${escapeHtml(h)}" ${h === (result.suggested_mapping[key] ?? key) ? "selected" : ""}>${escapeHtml(h)}</option>`).join("")}</select></label>`)
            .join("");
        get("mapping").hidden = false;
        get("process").disabled = false;
        get("file-info").textContent =
            `${file.name} · ${result.records} registros detectados`;
        notice("Columnas revisadas. Confirma las asociaciones y los formatos antes de importar.");
    });
});
get("upload-form").addEventListener("submit", (event) => {
    event.preventDefault();
    void busy(get("process"), async () => {
        const file = get("file").files?.[0];
        if (!file)
            throw new Error("Selecciona un CSV.");
        const map = {};
        get("mapping")
            .querySelectorAll("select")
            .forEach((s) => {
            if (s.value && s.dataset.field)
                map[s.dataset.field] = s.value;
        });
        const form = new FormData();
        form.append("file", file);
        form.append("mapping", JSON.stringify(map));
        form.append("delimiter", get("delimiter").value);
        form.append("date_format", get("date-format").value);
        form.append("number_format", get("number-format").value);
        notice("Validando y consolidando…");
        currentBatch = await api("/api/imports", {
            method: "POST",
            body: form,
        });
        offset = 0;
        await load();
        notice(currentBatch.replayed
            ? "Archivo ya procesado con estas reglas. Se conserva la importación original."
            : `Importación completa: ${currentBatch.accepted} válidas, ${currentBatch.rejected} rechazadas y ${currentBatch.duplicated} duplicadas.`);
    });
});
get("period").addEventListener("change", () => {
    void load().catch(showError);
});
get("prev").addEventListener("click", () => {
    offset = Math.max(0, offset - 20);
    void loadOutcomes().catch(showError);
});
get("next").addEventListener("click", () => {
    offset += 20;
    void loadOutcomes().catch(showError);
});
void load().catch(showError);
export {};
