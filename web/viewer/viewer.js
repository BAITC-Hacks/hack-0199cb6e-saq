"use strict";

(() => {
  const fields = ["sku", "supplier", "qty_recommended", "reason", "urgency"];
  const urgencyOrder = ["critical", "high", "medium", "low", "none"];
  const urgencyDescriptions = {
    critical: "Критическая срочность",
    high: "Высокая срочность",
    medium: "Средняя срочность",
    low: "Низкая срочность",
    none: "Без срочности",
  };
  const urgencyIcons = { critical: "!", high: "!", medium: "◷", low: "↓", none: "✓" };
  const rowsElement = document.getElementById("recommendation-rows");
  const filterElement = document.getElementById("supplier-filter");
  const reloadButton = document.getElementById("reload");
  const reloadLabel = document.getElementById("reload-label");
  const sortButton = document.getElementById("sort-urgency");
  const stateElement = document.getElementById("state");
  const resetButton = document.getElementById("reset-filter");
  const tableRegion = document.getElementById("table-region");
  const announcement = document.getElementById("announcement");
  const totalCount = document.getElementById("total-count");
  const visibleCount = document.getElementById("visible-count");
  const urgentCount = document.getElementById("urgent-count");
  const loadStatus = document.getElementById("load-status");
  const countFormatter = new Intl.NumberFormat("ru-RU");
  let recommendations = [];
  let mostUrgentFirst = true;
  let loading = false;

  function normalizedSupplier(value) {
    const supplier = value.trim().toUpperCase();
    return supplier === "ИЭК" ? "IEK" : supplier;
  }

  function normalizedUrgency(value) {
    return value.trim().toLowerCase();
  }

  function compareUrgency(left, right) {
    const leftRank = urgencyOrder.indexOf(normalizedUrgency(left.urgency));
    const rightRank = urgencyOrder.indexOf(normalizedUrgency(right.urgency));
    // Unknown values stay last in either direction; equal ranks retain source order.
    if (leftRank === -1) return rightRank === -1 ? 0 : 1;
    if (rightRank === -1) return -1;
    return mostUrgentFirst ? leftRank - rightRank : rightRank - leftRank;
  }

  function showState(kind, title, description) {
    stateElement.hidden = false;
    stateElement.dataset.kind = kind;
    document.getElementById("state-icon").textContent = kind === "error" ? "!" : kind === "loading" ? "…" : "—";
    document.getElementById("state-title").textContent = title;
    document.getElementById("state-description").textContent = description;
    resetButton.hidden = kind !== "filtered-empty";
    announcement.textContent = `${title}. ${description}`;
  }

  function renderRow(row) {
    const tr = document.createElement("tr");
    for (const field of fields) {
      const td = document.createElement("td");
      td.className = field;
      if (field === "urgency") {
        const urgency = normalizedUrgency(row.urgency);
        const known = urgencyOrder.includes(urgency);
        const badge = document.createElement("span");
        badge.className = `urgency-badge urgency-${known ? urgency : "unknown"}`;
        badge.title = known ? urgencyDescriptions[urgency] : "Неизвестная срочность";
        const icon = document.createElement("span");
        icon.setAttribute("aria-hidden", "true");
        icon.className = "urgency-icon";
        icon.textContent = known ? urgencyIcons[urgency] : "?";
        const label = document.createElement("span");
        label.textContent = row[field];
        badge.append(icon, label);
        td.append(badge);
      } else {
        // Codes, quantities and multiline explanations are displayed exactly as received.
        td.textContent = row[field];
      }
      tr.append(td);
    }
    return tr;
  }

  function render() {
    const selectedSupplier = filterElement.value;
    const visible = recommendations
      .filter((row) => selectedSupplier === "all" || normalizedSupplier(row.supplier) === selectedSupplier)
      .sort(compareUrgency);
    const fragment = document.createDocumentFragment();
    for (const row of visible) fragment.append(renderRow(row));
    rowsElement.replaceChildren(fragment);

    totalCount.textContent = countFormatter.format(recommendations.length);
    visibleCount.textContent = countFormatter.format(visible.length);
    urgentCount.textContent = countFormatter.format(
      visible.filter((row) => ["critical", "high"].includes(normalizedUrgency(row.urgency))).length,
    );

    if (recommendations.length === 0) {
      showState("empty", "Рекомендаций пока нет", "После подготовки результатов нажмите «Обновить».");
    } else if (visible.length === 0) {
      showState("filtered-empty", "Для этого поставщика нет позиций", "Выберите другого поставщика или покажите все рекомендации.");
    } else {
      stateElement.hidden = true;
      resetButton.hidden = true;
      announcement.textContent = `Показано позиций: ${visibleCount.textContent} из ${totalCount.textContent}. ${document.getElementById("sort-description").textContent}.`;
    }
  }

  async function loadRecommendations() {
    if (loading) return;
    loading = true;
    reloadButton.disabled = true;
    filterElement.disabled = true;
    sortButton.disabled = true;
    reloadLabel.textContent = "Загрузка…";
    tableRegion.setAttribute("aria-busy", "true");
    rowsElement.replaceChildren();
    recommendations = [];
    totalCount.textContent = "—";
    visibleCount.textContent = "—";
    urgentCount.textContent = "—";
    loadStatus.textContent = "Ожидание данных";
    showState("loading", "Загружаем рекомендации", "Получаем результаты расчёта.");

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    let serverMessage = "";
    try {
      const response = await fetch("/recommendations", {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) {
        try {
          const problem = await response.json();
          if (typeof problem?.detail === "string") serverMessage = problem.detail;
        } catch {
          // A non-JSON error response still has a useful local fallback below.
        }
        throw new Error("response");
      }
      const data = await response.json();
      if (!Array.isArray(data) || !data.every((row) =>
        row !== null && typeof row === "object" && fields.every((field) => typeof row[field] === "string")
      )) {
        throw new Error("format");
      }
      recommendations = data;
      filterElement.disabled = false;
      sortButton.disabled = false;
      loadStatus.textContent = "Данные загружены";
      render();
    } catch (error) {
      loadStatus.textContent = "Ошибка загрузки";
      const description = error.name === "AbortError"
        ? "Сервер не ответил вовремя. Нажмите «Обновить», чтобы повторить загрузку."
        : error.message === "format"
          ? "Получен неожиданный формат данных. Проверьте результаты расчёта и нажмите «Обновить»."
          : serverMessage.trim()
            ? `${serverMessage} Нажмите «Обновить», чтобы повторить загрузку.`
            : "Не удалось получить данные с сервера. Проверьте доступность результатов и нажмите «Обновить».";
      showState("error", "Не удалось загрузить рекомендации", description);
    } finally {
      window.clearTimeout(timeout);
      loading = false;
      reloadButton.disabled = false;
      reloadLabel.textContent = "Обновить";
      tableRegion.setAttribute("aria-busy", "false");
    }
  }

  filterElement.addEventListener("change", render);
  reloadButton.addEventListener("click", loadRecommendations);
  resetButton.addEventListener("click", () => {
    filterElement.value = "all";
    render();
    filterElement.focus();
  });
  sortButton.addEventListener("click", () => {
    mostUrgentFirst = !mostUrgentFirst;
    const direction = mostUrgentFirst ? "Сначала самые срочные" : "Сначала наименее срочные";
    document.getElementById("sort-description").textContent = direction;
    document.getElementById("sort-arrow").textContent = mostUrgentFirst ? "↓" : "↑";
    document.getElementById("urgency-heading").setAttribute("aria-sort", mostUrgentFirst ? "descending" : "ascending");
    sortButton.setAttribute("aria-label", `Срочность: ${direction.toLowerCase()}. Показать ${mostUrgentFirst ? "сначала наименее срочные" : "сначала самые срочные"}`);
    render();
  });

  loadRecommendations();
})();
