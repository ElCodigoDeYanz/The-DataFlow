export {};
type ImportRun = {
  id: string;
  filename: string;
  created_at: string;
  total: number;
  accepted: number;
  rejected: number;
  duplicated: number;
  elapsed_ms: number;
  replayed?: boolean;
};
type Group = {
  branch: string;
  period: string;
  currency: string;
  records: number;
  amount_cents: number;
};
type Summary = {
  totals: {
    total: number;
    accepted: number;
    rejected: number;
    duplicated: number;
    imports: number;
  };
  groups: Group[];
};
type Outcome = { source_row: number; status: string; reason: string };
const get = <T extends HTMLElement>(id: string): T => {
  const node = document.getElementById(id);
  if (!node) throw new Error(id);
  return node as T;
};
const escapeHtml = (v: unknown): string =>
  String(v).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ] ?? c,
  );
const notice = (message: string, error = false): void => {
  get("notice").textContent = message;
  get("notice").classList.toggle("error", error);
};
async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const r = await fetch(url, options);
  if (!r.ok) {
    let message = `Error ${r.status}`;
    try {
      const data: unknown = await r.json();
      if (typeof data === "object" && data !== null && "detail" in data) {
        const detail = (data as { detail: unknown }).detail;
        message = typeof detail === "string" ? detail : JSON.stringify(detail);
      }
    } catch {
      /* a bounded fallback for non-JSON HTTP errors */
    }
    throw new Error(message);
  }
  return r.json() as Promise<T>;
}
const money = (cents: number, currency: string): string =>
  new Intl.NumberFormat("es-PE", { style: "currency", currency }).format(
    cents / 100,
  );
let currentBatch: ImportRun | null = null;
let offset = 0;
async function loadOutcomes(): Promise<void> {
  if (!currentBatch) return;
  const rows = await api<Outcome[]>(
    `/api/imports/${currentBatch.id}/outcomes?limit=20&offset=${offset}`,
  );
  get("quality-caption").textContent =
    `${currentBatch.filename} · línea física de inicio en el archivo original`;
  const labels: Record<string, string> = {
    accepted: "Válida",
    rejected: "Rechazada",
    duplicated: "Duplicada",
  };
  get("outcomes").innerHTML =
    rows
      .map(
        (r) =>
          `<tr><td>${r.source_row}</td><td><span class="tag ${escapeHtml(r.status)}">${labels[r.status] ?? escapeHtml(r.status)}</span></td><td>${escapeHtml(r.reason)}</td></tr>`,
      )
      .join("") ||
    '<tr><td colspan="3" class="table-empty">No hay filas.</td></tr>';
  get<HTMLButtonElement>("prev").disabled = offset === 0;
  get<HTMLButtonElement>("next").disabled = offset + 20 >= currentBatch.total;
  get("page-label").textContent =
    `${Math.min(offset + 1, currentBatch.total)}–${Math.min(offset + 20, currentBatch.total)} de ${currentBatch.total}`;
}
async function load(): Promise<void> {
  const period = get<HTMLInputElement>("period").value;
  const [summary, runs] = await Promise.all([
    api<Summary>(`/api/summary?period=${encodeURIComponent(period)}`),
    api<ImportRun[]>("/api/imports"),
  ]);
  for (const key of ["total", "accepted", "rejected", "duplicated"] as const)
    get(key).textContent = summary.totals[key].toLocaleString("es-PE");
  get("import-count").textContent = `${summary.totals.imports} archivos`;
  if (summary.groups.length) {
    const max = Math.max(...summary.groups.map((g) => g.amount_cents));
    get("summary").innerHTML = summary.groups
      .map(
        (g) =>
          `<div class="summary-row"><div class="summary-top"><span>${escapeHtml(g.branch)}</span><strong>${escapeHtml(money(g.amount_cents, g.currency))}</strong></div><p>${g.records} registros · ${escapeHtml(g.period)} · ${escapeHtml(g.currency)}</p><svg class="summary-bar" viewBox="0 0 100 5" preserveAspectRatio="none" aria-hidden="true"><rect width="100" height="5" fill="#eff2eb"/><rect width="${((g.amount_cents / max) * 100).toFixed(2)}" height="5" fill="#759168"/></svg></div>`,
      )
      .join("");
  } else {
    get("summary").innerHTML =
      '<div class="empty"><span>◷</span><h3>No hay registros para mostrar</h3><p>Importa un CSV o selecciona otro periodo.</p></div>';
  }
  get("imports").innerHTML =
    runs
      .map(
        (r) =>
          `<tr><td class="file-name">${escapeHtml(r.filename)}</td><td>${escapeHtml(r.created_at.slice(0, 16).replace("T", " "))}</td><td>${r.total}</td><td class="green">${r.accepted}</td><td class="orange">${r.rejected}</td><td>${r.duplicated}</td><td><button class="table-button" data-batch="${r.id}">Ver filas →</button></td></tr>`,
      )
      .join("") ||
    '<tr><td colspan="7" class="table-empty">Todavía no hay importaciones.</td></tr>';
  get("imports")
    .querySelectorAll<HTMLButtonElement>("[data-batch]")
    .forEach((button) =>
      button.addEventListener("click", () => {
        currentBatch = runs.find((r) => r.id === button.dataset.batch) ?? null;
        offset = 0;
        void loadOutcomes()
          .then(() => get("quality").scrollIntoView({ block: "start" }))
          .catch(showError);
      }),
    );
  if (currentBatch) await loadOutcomes();
}
function showError(error: unknown): void {
  notice(
    error instanceof Error
      ? error.message
      : "No se pudo completar la operación. Intenta de nuevo.",
    true,
  );
}
async function busy(
  button: HTMLButtonElement,
  action: () => Promise<void>,
): Promise<void> {
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  try {
    await action();
  } catch (e) {
    showError(e);
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}
get<HTMLButtonElement>("demo").addEventListener("click", () => {
  void busy(get("demo"), async () => {
    notice("Cargando el ejemplo sintético…");
    const runs = await api<ImportRun[]>("/api/demo", { method: "POST" });
    await load();
    notice(
      runs.every((r) => r.replayed)
        ? "El ejemplo ya estaba importado. No se duplicó ningún resultado."
        : "Ejemplo sintético importado. Revisa los resultados, las incidencias y las exportaciones.",
    );
    currentBatch = runs[0] ?? null;
    offset = 0;
    await loadOutcomes();
  });
});
const resetMapping = (): void => {
  get("mapping").hidden = true;
  get("mapping").replaceChildren();
  get<HTMLButtonElement>("process").disabled = true;
};
get("file").addEventListener("change", resetMapping);
get("delimiter").addEventListener("change", resetMapping);
get<HTMLButtonElement>("preview").addEventListener("click", () => {
  void busy(get("preview"), async () => {
    const file = get<HTMLInputElement>("file").files?.[0];
    if (!file) throw new Error("Selecciona un archivo CSV.");
    if (file.size > 5 * 1024 * 1024)
      throw new Error("El archivo supera 5 MiB.");
    const form = new FormData();
    form.append("file", file);
    form.append("delimiter", get<HTMLSelectElement>("delimiter").value);
    notice("Revisando cabeceras…");
    const result = await api<{
      headers: string[];
      records: number;
      suggested_mapping: Record<string, string>;
    }>("/api/preview", { method: "POST", body: form });
    const fields: Record<string, string> = {
      sale_id: "Identificador *",
      branch: "Sucursal *",
      sale_date: "Fecha *",
      amount: "Importe *",
      currency: "Moneda *",
      description: "Descripción (opcional)",
    };
    get("mapping").innerHTML = Object.entries(fields)
      .map(
        ([key, label]) =>
          `<label>${label}<select data-field="${key}" ${key === "description" ? "" : "required"}><option value="">Seleccionar</option>${result.headers.map((h) => `<option value="${escapeHtml(h)}" ${h === (result.suggested_mapping[key] ?? key) ? "selected" : ""}>${escapeHtml(h)}</option>`).join("")}</select></label>`,
      )
      .join("");
    get("mapping").hidden = false;
    get<HTMLButtonElement>("process").disabled = false;
    get("file-info").textContent =
      `${file.name} · ${result.records} registros detectados`;
    notice(
      "Columnas revisadas. Confirma las asociaciones y los formatos antes de importar.",
    );
  });
});
get<HTMLFormElement>("upload-form").addEventListener("submit", (event) => {
  event.preventDefault();
  void busy(get("process"), async () => {
    const file = get<HTMLInputElement>("file").files?.[0];
    if (!file) throw new Error("Selecciona un CSV.");
    const map: Record<string, string> = {};
    get("mapping")
      .querySelectorAll<HTMLSelectElement>("select")
      .forEach((s) => {
        if (s.value && s.dataset.field) map[s.dataset.field] = s.value;
      });
    const form = new FormData();
    form.append("file", file);
    form.append("mapping", JSON.stringify(map));
    form.append("delimiter", get<HTMLSelectElement>("delimiter").value);
    form.append("date_format", get<HTMLSelectElement>("date-format").value);
    form.append("number_format", get<HTMLSelectElement>("number-format").value);
    notice("Validando y consolidando…");
    currentBatch = await api<ImportRun>("/api/imports", {
      method: "POST",
      body: form,
    });
    offset = 0;
    await load();
    notice(
      currentBatch.replayed
        ? "Archivo ya procesado con estas reglas. Se conserva la importación original."
        : `Importación completa: ${currentBatch.accepted} válidas, ${currentBatch.rejected} rechazadas y ${currentBatch.duplicated} duplicadas.`,
    );
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
