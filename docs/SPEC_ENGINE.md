# SPEC_ENGINE — алгоритм расчёта (`src/ekt_engine`)

Движок — чистые функции над каноническими таблицами (SPEC_DATA §2). Без I/O, без сети, без ИИ (аналоги — через интерфейс
`AnalogsProvider` с детерминированным fallback). Все параметры — `ekt_core.config.EngineParams` (§3).

## 1. Конвейер

```
prepare(dataset, params)                           # кэшируется по (dataset_id, forecast-параметры)
  1 history      → окно 2024-01 … последний полный месяц; pre-launch → NaN
  2 cleaning     → возвраты, отрицательные месяцы
  3 oneoff       → разовые строки (транзакции) → вычитание из месяцев; Hampel по месяцам
  4 stockout     → доступность a[m] ∈ [0,1], восстановленный спрос
  5 classify     → класс спроса, ABC (если нет), жизненный цикл, преемственность
  6 seasonality  → индексы s[sku, 1..12] с иерархическим сжатием
  7 forecast     → уровень, тренд, прогноз f[sku, месяц], σ
plan(prepared, params)                             # быстрый, пересчитывается в what-if
  8 policy       → горизонт, D_T, SS, IP, Q (кэп, округление, ед. закупки)
  9 projection   → дневная проекция остатка, дата дефицита, срочность, канал
 10 explain      → reason codes, waterfall, краткое обоснование RU/KZ, контрфакты
 11 aggregate    → группировка по поставщикам/каналам, KPI
→ RunResult(run_id, lines, details, summary, quality)
```

`run_id = sha256(dataset_hash + canonical_json(params) + ENGINE_VERSION)[:16]`.

## 2. Этапы и формулы

Обозначения: `m` — месяц, `d[m]` — месячные продажи (нетто), `L_days` — срок поставки канала SKU, `R` — период пересмотра,
`T = L_days + R`, `as_of` — дата расчёта.

### 2.1 History
- Окно: `history_start` (2024-01) … последний **полный** месяц до `as_of` (2026-08).
- Месяцы до `launch_date` или до первой ненулевой продажи/остатка SKU → `NaN` (не ноль).
- Если SKU — преемник (подтверждённая подсказка `successor` или синтетика): `d_new[m] = d_old[m]` для месяцев до запуска нового
  (перенос истории), reason `SUCCESSOR_HISTORY{from_sku}`.

### 2.2 Cleaning
- `d[m] < 0` → 0, накопленная величина в `RETURNS_CLIPPED{qty}`.
- Транзакции: только `doc_type = Расходная накладная`, `qty > 0` для поиска разовых; отрицательные — в дневную проекцию.

### 2.3 One-off (разовые крупные заказы) — `oneoff.py`
Для каждого SKU по строкам транзакций за последние 21 месяц:
1. Если строк ≥ `oneoff_min_lines` (8):
   - `x = log1p(qty)`, `med = median(x)`, `mad = max(1.4826·MAD(x), 0.1)`, `z = (x − med)/mad`;
   - `p95 = quantile(qty, 0.95)`, `med_q = median(qty)`;
   - `share = qty / Σqty(SKU, месяц строки)`;
   - **кандидат**, если `z > oneoff_z` (3.5) **и** (`qty > oneoff_p95_mult·p95` (3) **или** (`share ≥ oneoff_share` (0.5) **и** `qty ≥ oneoff_median_mult·med_q` (10))).
2. Если строк < 8: кандидат, если `qty > oneoff_small_mult (5) × Σ(прочие строки за 12 мес)` и `qty ≥ 10·med_q`.
3. **Регулярность** (не разовый): кандидатоподобные строки (`qty ≥ 0.5·qty_candidate`) встречаются в ≥ `oneoff_recurrence_months` (4)
   из последних 12 месяцев → `REGULAR_LARGE_BUYER{count}`; при наличии `client_hash`: клиент покупал SKU в ≥3 разных месяцах → регулярный.
4. Разовая строка: `cap = max(quantile(qty_non_candidates, 0.9), 3·med_q)`, `excess = qty − cap`.
5. **Вычитание из месячного ряда (D3)**:
   `tx_total[m] = Σ строк месяца`, `excess_sum[m] = Σ excess разовых`, `tx_regular[m] = tx_total[m] − excess_sum[m]`,
   `removed[m] = min(excess_sum[m], max(0, d[m] − tx_regular[m]))`, `d_clean[m] = d[m] − removed[m]`.
   Reason `ONE_OFF_EXCLUDED{count, qty=Σremoved, max_line}`; если `removed < excess_sum` → `ONE_OFF_NOT_IN_MONTHLY{qty}` (info).
6. **Hampel по месяцам** (страховка для 2024 и месяцев без строк): на `d_clean / s_prior[month]` окно 7, порог `hampel_t` (3.5)·MAD →
   значения выше порога обрезаются до `median + hampel_t·MAD`, reason `MONTH_SPIKE_CAPPED{month, qty}`. Только вверх.
7. Результат: таблица `oneoff_lines` (для карточки) и `d_clean`.

### 2.4 Stockout — `stockout.py`
Для SKU-месяца: `open = stock_opening[m]`, `close = stock_opening[m+1]` (для последнего месяца — текущий остаток/оценка).
- **Полный stockout**: `open ≤ 0` и `close ≤ 0` и `d_clean[m] ≤ 0.1·level_hint` → `a = 0`.
- **Частичный**: ровно одно из (`open ≤ 0`, `close ≤ 0`):
  - есть транзакции (2025+): `close ≤ 0` → `a = day(last_sale)/days_in_month`; `open ≤ 0` → `a = (days − day(first_sale) + 1)/days`;
    нет продаж в месяце → `a = 0`;
  - нет транзакций (2024) → `a = stockout_partial_default` (0.5).
- **Неявный** (опционально, флаг `implicit_stockout=True`): серия нулевых дней длиной k при дневной интенсивности λ (по месяцам с a≥0.95)
  с `exp(−λk) < 0.01` и `open < λ·days` → уменьшить `a` на `k/days`.
- Иначе `a = 1`.
- Восстановление: `a ≥ 0.95` → `r[m] = d_clean[m]`; `stockout_min_avail ≤ a < 0.95` → `r[m] = min(d_clean[m]/a, cap_r)`;
  `a < stockout_min_avail` (0.3) → `r[m] = NaN` (импутируется моделью: уровень × сезонность);
  `cap_r = stockout_cap_mult (1.5) × quantile(r[a≥0.95] / s, 0.9) × s[month]`.
- Reason `STOCKOUT_RESTORED{months, qty=Σ(r − d_clean) + импутация}`; флаг строки `STOCKOUT_HISTORY`, если за 12 мес были месяцы с a<0.95.

### 2.5 Classify — `classify.py`
- По `r` за последние 24 мес (без NaN): `ADI = n_months / n_nonzero`, `CV² = (std/mean)²` ненулевых.
  `smooth` (ADI<1.32, CV²<0.49), `erratic` (ADI<1.32, CV²≥0.49), `intermittent` (ADI≥1.32, CV²<0.49), `lumpy` (иначе).
- `dead`: нет продаж 12 мес. `new`: история с запуска < `new_months` (6).
- ABC: SE — из «Категория 2026»; ИЭК — вычислить: по стоимости (`Σqty·unit_cost` за 12 мес), если есть цены, иначе по **числу строк
  продаж** за 12 мес; кумулятивно 80% → A, 95% → B, остальное C; без продаж → N. `abc_source='computed'`.
- Жизненный цикл из подтверждённых подсказок (SPEC_AI AI-3): `eol`, `discontinued`, `made_to_order`, `new`.

### 2.6 Seasonality — `seasonality.py`
- **Априор поставщика** `s_prior[1..12] = 0.5·s_qty + 0.5·s_partner`, где `s_qty` — индексы по сумме `r` всех SKU поставщика
  (для каждого года: месяц / среднее года при ≥10 валидных месяцах; медиана по годам), `s_partner` — `season_prior` из файла; оба
  нормированы к среднему 1.
- **Группа** (линейка: из `skus.group` — серия/семейство по токенам названия: ATLAS, Wessen 59, ARTGALLERY, BLANCA, BRITE, ВА47-29,
  City 9, ЩРН/ЩРВ, IMT-коробки, ITK, GENERICA, TEKFOR, KARAT, ARMAT…; иначе категория 1-го уровня из enrich): `s_grp` так же по сумме
  группы; используется, если в группе ≥5 SKU с ≥24 мес истории, `w_grp = 0.5`, иначе 0.
- **SKU**: `s_sku` так же по собственному `r` при ≥18 валидных месяцах и классе smooth/erratic; `w_sku = n_years/(n_years + season_k)`
  (`season_k=2`), иначе 0.
- `s = w_sku·s_sku + (1 − w_sku)·(w_grp·s_grp + (1 − w_grp)·s_prior)`, клип `[0.5, 2.0]`, нормировка к среднему 1.
- Reason `SEASON{coef_horizon, source: sku|group|supplier}`.

### 2.7 Forecast — `forecast.py`
- Десезонализация: `y[m] = r[m]/s[month(m)]`.
- **Уровень** (smooth/erratic): последние 12 мес (мин. 3 значения, иначе вся история); веса `0.5^(age/level_half_life)` (6 мес);
  при n≥8 обрезать значения вне [P10, P90]; `L = Σw·y/Σw`.
- **Уровень** (intermittent/lumpy): TSB по `y` помесячно: инициализация `z0 = mean(y>0)`, `p0 = share(y>0)`;
  `y_t>0: z ← z + α(y_t − z), p ← p + β(1 − p)`; `y_t=0: p ← p + β(0 − p)`; `α=β=0.1`; `L = p·z`.
- **Тренд** (smooth/erratic, ≥12 точек): Theil–Sen (`scipy.stats.theilslopes`) по `log1p(y)` последних 18 мес →
  `g = exp(12·slope) − 1`, клип `±trend_cap` (0.30); множитель на горизонте h мес: `(1+g)^(trend_damping·h/12)` (`trend_damping=0.5`).
  Иначе `g = 0`. Reason `TREND{pct}` при |g| ≥ 0.05.
- **Ручной прирост** (`growth_overrides`, «прогноз по приросту» из кейса): приоритет `line > category > supplier`, множитель `(1+pct)`.
  Reason `MANUAL_GROWTH{pct, scope, key}`.
- **Новинки** (`new`): `L = new_conservative (0.7) × median(L аналогов)`; аналоги от `AnalogsProvider` (SPEC_AI AI-2; fallback — SKU той же
  группы и поставщика с совпадением ≥60% токенов названия); если у новинки ≥3 мес собственных продаж — `L = 0.5·L_own + 0.5·L_analog`.
  Reason `NEW_BY_ANALOGS{analogs:[…]}`.
- **dead / eol / discontinued / made_to_order / abc N** → прогноз считается (для графика), но заказ 0 (§2.8).
- `f[m] = L × s[month(m)] × trend(h) × manual` для m = следующий месяц после as_of … +12.
- **σ_month**: `1.25 × mean(|r[t] − L·s[t]|)` по последним 12 валидным месяцам; для intermittent/lumpy — `max(σ, sqrt(L))`;
  интервал прогноза `f ± 1.28·σ` (для графика).

### 2.8 Policy — `policy.py`
1. `L_days` = канал SKU (`default_channel_id`; переопределения из params), `R = review_days[supplier]` (14), `T = L_days + R`.
2. `D_T = Σ_{день=as_of+1}^{as_of+T} f[месяц(день)]/дней_в_месяце`.
3. `z = Φ⁻¹(service_level[abc])` (A 0.95, B 0.90, C 0.85, NEW 0.90); `SS = z·σ_month·sqrt(T/30.4375)`; `SS ≤ D_T`.
4. `stock_now = free + retail + showcase + tz (+ rc, если include_rc)`; `inbound_in_T = Σ inbound с eta ≤ as_of + T`;
   прочие поставки → reason `INBOUND_AFTER_HORIZON{qty, eta}`. `IP = stock_now + inbound_in_T`.
5. `Q0 = D_T + SS − IP`; `Q_raw = max(0, Q0)` (шаг waterfall `floor`, если Q0<0).
6. **Блокировки** (Q=0 с причиной): lifecycle `eol` → `EOL_NO_ORDER`, `discontinued` → `DISCONTINUED_NO_ORDER`,
   `made_to_order` → `MADE_TO_ORDER`, класс `dead` → `DEAD_NO_ORDER`, abc `N` → `CATEGORY_NO_ORDER`.
7. **Кэп покрытия (D8)**: `avg_f = mean(f следующих 6 мес)`; `Q_cap = max(0, cover_max[abc]·avg_f − IP)`
   (A 4, B 4, C 3); если `Q_raw > Q_cap` → `Q = Q_cap`, reason `COVER_CAP{max_months}`.
8. **Единицы и округление**: `q = Q/purchase_factor`; если `q>0`: `q = ceil(q/order_multiple)·order_multiple`, `q = max(q, min_order_qty)`;
   мелочь: если `Q_raw < round_down_share (0.25)·order_multiple·purchase_factor` и срочность ≤ medium → 0 (`ROUND_DOWN_SMALL`);
   `C` и округление > удвоения `Q_raw` и срочность ≤ medium → 0 (`MOQ_NOT_JUSTIFIED`).
   `Q_final = q·purchase_factor` (ед. продажи), `qty_purchase = q`. Reasons `ROUND_MULTIPLE{from,to,multiple}`, `MOQ_APPLIED`, `UOM_CONVERTED{factor,uom}`.
9. `value_kzt = Q_final·unit_cost` (если есть).
10. **Избыток**: `cover_now = (stock_now + Σ всех inbound)/avg_f`; `cover_now > excess_months` (4) → флаг `EXCESS`,
    `excess_qty = stock_now + inbound_all − cover_max·avg_f`, `excess_value = excess_qty·unit_cost`.

### 2.9 Projection и срочность — `projection.py`
- Дневная проекция 0…180 дн: `stock(t) = stock_now + Σ inbound(eta ≤ t) − Σ f_daily(≤ t)`.
- `stockout_date` = первый t с `stock(t) < 0` (или null).
- Срочность: `critical` — `stockout_date ≤ as_of + L_days`; `high` — `≤ as_of + L_days + R`; `medium` — `Q_final > 0`;
  `low` — `Q_final = 0` и `cover_now < cover_min` (1); иначе `none`.
- `order_by = max(as_of, stockout_date − L_days)`.
- **Разделение по каналам (ИЭК)**: если `critical` и есть канал `is_fast` с `as_of + L_fast < stockout_date` (или меньше текущего L):
  `urgent_qty = Σ f_daily от (as_of + L_fast) до (as_of + L_days)` (округлить по кратности) → `channel_suggestion {channel_id, qty, arrival}`,
  reason `CHANNEL_SPLIT{fast_channel, qty}`; общий Q не меняется.

### 2.10 Explain — `explain.py`
**Waterfall** (сумма шагов = `Q_final`, тест):

| key | значение |
|---|---|
| `base` | `L × T/30.4375` |
| `season` | `D_T(s, без тренда/ручного) − base` |
| `trend` | `D_T(s, тренд) − D_T(s)` |
| `manual_growth` | `D_T(всё) − D_T(s, тренд)` |
| `safety_stock` | `SS` |
| `stock_now` | `−stock_now` |
| `inbound` | `−inbound_in_T` |
| `floor` | `max(0, −Q0)` |
| `block` | `−Q_raw`, если блокировка |
| `cap` | `Q − Q_raw` (≤0) |
| `rounding` | `Q_final − Q` (±) |
| `result` | `Q_final` (итоговая, не суммируется) |

**Контрфакты** (тот же plan на альтернативном prepare): `without_stockout_restore` (a=1 везде), `without_one_off_exclusion`
(removed=0, без Hampel), `raw_average_method` (`max(0, mean(d за 12 мес)·T/30.4375 − IP)` без SS).

**Reason codes** (параметры в фигурных скобках, тексты в `ekt_engine/i18n/reasons.{ru,kk}.yaml`, шаблоны `str.format`):
`BASE_DEMAND{level,months}`, `SEASON{coef,source}`, `TREND{pct}`, `MANUAL_GROWTH{pct,scope,key}`, `STOCKOUT_RESTORED{months,qty}`,
`ONE_OFF_EXCLUDED{count,qty,max_line}`, `ONE_OFF_NOT_IN_MONTHLY{qty}`, `REGULAR_LARGE_BUYER{count}`, `MONTH_SPIKE_CAPPED{month,qty}`,
`RETURNS_CLIPPED{qty}`, `SAFETY_STOCK{ss,service,z}`, `STOCK_NOW{qty,estimate}`, `INBOUND{qty,eta}`, `INBOUND_AFTER_HORIZON{qty,eta}`,
`ROUND_MULTIPLE{from,to,multiple}`, `MOQ_APPLIED{moq}`, `ROUND_DOWN_SMALL`, `MOQ_NOT_JUSTIFIED`, `COVER_CAP{max_months}`,
`UOM_CONVERTED{factor,uom}`, `NEW_BY_ANALOGS{analogs}`, `SUCCESSOR_HISTORY{from_sku}`, `EOL_NO_ORDER`, `DISCONTINUED_NO_ORDER`,
`MADE_TO_ORDER`, `DEAD_NO_ORDER`, `CATEGORY_NO_ORDER`, `EXCESS{cover,value}`, `URGENT{stockout_date,arrival}`,
`CHANNEL_SPLIT{fast_channel,qty}`, `STOCK_ESTIMATED`, `DATA_WARNING{code}`.

**Краткое обоснование** (`reason_short`, ≤ 180 символов): итог + 2–3 шага waterfall с наибольшим |вкладом| + срочность.

Примеры шаблонов (KZ — на вычитку носителем):

| code | ru | kk |
|---|---|---|
| SUMMARY | `Заказать {qty} {uom}: спрос на {days} дн. — {demand}, страховой запас — {ss}, доступно — {available}.` | `{qty} {uom} тапсырыс беру ұсынылады: {days} күнге сұраныс — {demand}, сақтандыру қоры — {ss}, қолжетімді — {available}.` |
| ONE_OFF_EXCLUDED | `Исключено {count} {count:plural:разовый заказ\|разовых заказа\|разовых заказов} на {qty} шт (крупнейший — {max_line} шт).` | `Жалпы {qty} дана болатын {count} бір реттік тапсырыс есептен шығарылды (ең үлкені — {max_line} дана).` |
| STOCKOUT_RESTORED | `Спрос восстановлен за {months} мес. без остатка: +{qty} шт.` | `Қалдық болмаған {months} айдағы сұраныс қалпына келтірілді: +{qty} дана.` |
| URGENT | `Дефицит ожидается с {stockout_date}; товар по новому заказу придёт не раньше {arrival}.` | `Тапшылық {stockout_date} бастап күтіледі; жаңа тапсырыс бойынша тауар {arrival} күнінен бұрын келмейді.` |
| EXCESS | `Избыток: запаса на {cover} мес., заморожено {value} ₸.` | `Артық қор: {cover} айға жетеді, {value} ₸ қатып тұр.` |

Числа в текстах форматировать `ru-KZ` (пробел-разделитель тысяч, запятая дробей), даты `дд.мм.гггг`.
Склонения: плейсхолдер `{count:plural:заказ|заказа|заказов}` → хелпер `plural_ru(n, forms)` (1 заказ, 2 заказа, 5 заказов);
в казахском существительное после числительного не меняется (`3 тапсырыс`) — плейсхолдер `{count}` без форм.

### 2.11 What-if — `whatif.py`
`apply(prepared, base_params, scope, changes) -> list[(sku, before, after)]` — пересчитывает только `plan` (быстро):
`inbound_delta` (добавить/убрать количество ближайшей поставке или создать поставку на as_of+7), `stock_delta`, `lead_time_delta_days`,
`inbound_delay_days` (сдвиг ETA всех поставок канала/поставщика), `growth_pct` (временный manual), `service_level`.
Цели: 1 SKU < 300 мс, весь поставщик < 10 с.

## 3. Параметры по умолчанию (`EngineParams`)

| Параметр | Значение | Параметр | Значение |
|---|---|---|---|
| history_start | 2024-01 | oneoff_min_lines | 8 |
| oneoff_z | 3.5 | oneoff_p95_mult | 3.0 |
| oneoff_share | 0.5 | oneoff_median_mult | 10 |
| oneoff_small_mult | 5 | oneoff_recurrence_months | 4 (из 12) |
| hampel_window | 7 | hampel_t | 3.5 |
| stockout_min_avail | 0.3 | stockout_partial_default | 0.5 |
| stockout_cap_mult | 1.5 | implicit_stockout | True |
| season_k | 2 | season_clip | [0.5, 2.0] |
| level_half_life | 6 мес | tsb_alpha / tsb_beta | 0.1 / 0.1 |
| trend_window | 18 мес | trend_cap | 0.30 |
| trend_damping | 0.5 | new_months | 6 |
| new_conservative | 0.7 | analog_min_similarity | 0.80 |
| service_level | A .95, B .90, C .85, NEW .90 | review_days | SE 14, IEK 14 |
| lead_time_days | SE-MAIN 45; IEK — из данных (fallback РФ 38, ПП 24, УТ 12) | default_inbound_eta_days | 14 |
| cover_min / cover_max | 1 / A 4, B 4, C 3 | excess_months | 4 |
| round_down_share | 0.25 | significant_coef | 0.30 |
| edit_reason_threshold | 0.20 | four_eyes | True |
| include_rc | False | iek_default_channel | IEK-PP |

## 4. Бэктест — `backtest.py` (A-7)
- Происхождения `o ∈ {2026-01 … 2026-06}`; горизонт 2 мес (`o`, `o+1`); данные до `o` (как будто `as_of = o − 1 день`).
- Факт — месячные продажи; сравниваем только SKU-пары месяцев с `a ≥ 0.9` (чтобы не штрафовать за цензуру).
- Методы: **наш**; **наивный** (`mean(d, 12 мес)`); **прокси метода менеджера** (`mean(d, 12 мес) × (1+Кэф.Роста) × (1+Кэф.Сез-ти)`,
  коэффициенты по формулам SPEC_DATA §SE-6, клип [−0.5, 1.0]; комбинация — **допущение**, указать в отчёте).
- Метрики по поставщику и ABC: `WAPE = Σ|F−A|/ΣA`, `bias = Σ(F−A)/ΣA`, доля SKU с |ошибкой| > 50%.
- Упрощённая симуляция: для каждого `o` доля SKU, у которых `A > IP_o + Q_o` (риск дефицита) и средний избыток `max(0, IP_o + Q_o − A)`
  (в ₸ для SE) — наш vs прокси менеджера (для прокси `Q = max(0, прогноз × 2 мес − IP)`).
- Вывод: `var/backtest.json` + `docs/BACKTEST.md` (честно: где лучше, где хуже).

## 5. Приёмочные тесты (`tests/acceptance`, на `make_dataset(seed=42)`)

| Тест | Проверка |
|---|---|
| `test_mh1_sources.py` | Для `SYN_INTRANSIT` (Q>0 с запасом): +inbound → Q↓; +stock → Q↓; история ×1.5 → Q↑; abc C→A → SS↑; manual growth +20% → Q↑; lead_time +30 → Q↑; кратность 1→50 → Q кратно 50. **Абляция**: удаление/искажение каждой входной таблицы (`sales_monthly, sales_lines, stock_opening, stock_current, inbound, skus.abc, growth_overrides, season_prior, moq`) меняет хэш результатов run. |
| `test_mh2_seasonality.py` | `SYN_SEASONAL` (амплитуда 0.5, пик август): прогноз августа ≥ 1.3 × февраля; corr(профиль прогноза, истинный) > 0.8; прогноз ≠ константа. |
| `test_mh3_stockout.py` | `SYN_STOCKOUT` (2 полных + 1 частичный месяц): `Q > counterfactual.without_stockout_restore`; восстановленный спрос частичного месяца в ±25% от истины; reason `STOCKOUT_RESTORED`. |
| `test_mh4_oneoff.py` | Инъекция строки ×50 медианы в `sales_lines` **и** `sales_monthly` у `SYN_ONEOFF`: `|Q_with − Q_without|/Q_without < 0.05`; строка в `one_off_lines`; reason `ONE_OFF_EXCLUDED`. `SYN_REGULAR_BIG` **не** помечается (reason `REGULAR_LARGE_BUYER`). Строка есть только в транзакциях (как LOOP) → `ONE_OFF_NOT_IN_MONTHLY`, месяц не уменьшается. |
| `test_mh5_explain.py` | У каждой строки непустые `reason_short.ru/kk` с цифрой; Σ waterfall = `recommended_qty` (±1 ед. кратности); оба поставщика в summary; группировка по `supplier_id` и `channel_id`. |
| `test_units.py` | `SYN_CABLE`: спрос в м → заказ целыми бухтами 305 м; `SYN_PACK`: шт → упак. |
| `test_inbound_eta.py` | Поставка с ETA после даты дефицита не снимает `critical`; с ETA до — снимает. |
| `test_lifecycle.py` | `SYN_EOL`, `SYN_MTO`, dead → Q=0 с reason; `SYN_SUCC_NEW` получает историю `SYN_SUCC_OLD`; `SYN_NEW` — по аналогам. |
| `test_determinism.py` | Два прогона → одинаковые `run_id` и результаты. |
| `test_i18n_reasons.py` | Для каждого reason code есть шаблоны ru и kk с одинаковым набором плейсхолдеров. |
| `test_properties.py` (hypothesis) | `Q ≥ 0`; `qty_purchase` кратно `order_multiple`; `Q_final` = `qty_purchase·purchase_factor`; монотонность по inbound/stock. |

## 6. Производительность
`prepare` ≤ 12 с на 3 000 SKU × 32 мес + 250 тыс. строк; `plan` ≤ 2 с; карточка SKU ≤ 50 мс (из кэша). Векторизация через
groupby/numpy; дневная проекция — матрично (SKU × 180).
