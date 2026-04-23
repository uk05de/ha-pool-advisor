"""Pool chemistry dosing calculations.

All formulas are empirical rules of thumb widely used in pool chemistry
literature. They are intentionally conservative — the advisor always splits
doses so the user re-measures before completing a correction.

Volume unit: m³. Dosages returned in grams (dry chemicals) or milliliters
(liquid chemicals).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .const import (
    PH_MINUS_DRY_ACID,
    PH_MINUS_HCL,
    PH_PLUS_SODA,
    SHOCK_CAL_HYPO,
    SHOCK_CYA_PER_PPM_CL,
    SHOCK_DICHLOR,
    SHOCK_NAOCL_LIQUID,
    SHOCK_STABILIZED,
    SHOCK_TARGET_ROUTINE,
    TA_PLUS_BICARB,
)


@dataclass(frozen=True)
class DoseStep:
    """A single dosing step."""

    amount: float          # grams or milliliters
    unit: str              # "g" or "ml"
    product: str           # translation key for the chemical
    wait_hours: int        # hours to wait before the NEXT step (0 for last)


@dataclass(frozen=True)
class Recommendation:
    """Full recommendation for one parameter."""

    action: str                       # "raise" | "lower" | "shock" | "watch" | "ok" | "no_data" | "calibrate"
    steps: tuple[DoseStep, ...]       # may be empty
    reason: str                       # short human-readable reason
    delta: float | None = None        # how far off target (same unit as parameter)
    note: str | None = None           # method hint / HOW it's done (under chem-table)
    why: str | None = None            # WHY this action — leads the note-under-table paragraph
    is_critical: bool = False         # True → red banner (MUSS), False → yellow banner (SOLLTE)


# ---- base rules (per m³ water, per 0.1 pH / per 10 mg/l TA / per 1 mg/l Cl) ----
# Source: common pool chemistry tables. Values are for the *active* compound.
# We then divide by product strength% to get grams/ml of the commercial product.

# pH-Dosierung — TA-abhängig (Puffer), Werte als Mittel aus Bayrol/TFP/Pentair
# Literatur:
#   Soda (Na2CO3) pH anheben:     5–7 g/m³ pro 0.1 pH  → Mittel 6.0
#   Trockensäure pH senken:       7.5–9 g/m³ pro 0.1 pH → Mittel 8.0
#   Salzsäure 33 % pH senken:     7–8 mL/m³ pro 0.1 pH  → Mittel 7.5
# Advisor splittet Dosen bei Bedarf (MAX_DOSE_PER_M3), User misst zwischendurch.
G_SODA_PURE_PER_M3_PER_01_PH = 6.0
G_DRY_ACID_PURE_PER_M3_PER_01_PH = 8.0
ML_HCL_33_PER_M3_PER_01_PH = 7.5

# To raise TA by 10 mg/l in 10 m³: ~170 g sodium bicarb (pure)
G_BICARB_PURE_PER_M3_PER_10_TA = 17.0

# Chemische Basis: um FC um 1 mg/l in 1 m³ Wasser (1000 L) zu erhöhen,
# braucht man 1 g aktives Chlor. Produktmenge dann × (100 / Stärke %).
# Flüssig-Chlor NaOCl bei 12.5 % Verfügbar-Chlor: 8 mL pro m³ pro 1 mg/l FC.
G_ACTIVE_CL_PER_M3_PER_1_FC = 1.0
ML_NAOCL_PER_M3_PER_1_FC_AT_12_5 = 8.0

# Shock multiplier on combined chlorine (breakpoint chlorination)
SHOCK_FC_MULTIPLIER = 10.0

# Max Sicherheits-Einzeldosis je Produkt-Typ (pro m³ pro Anwendung).
# Damit nicht 1.2 L Salzsäure auf einmal reinkippt, auch wenn mathematisch nötig.
# Werte aus Bayrol/TFP-Praxis-Empfehlungen für Privatpools.
MAX_DOSE_PER_M3 = {
    "dry_acid_nahso4": 20.0,       # g/m³  — pH− (Bayrol: ~15 g/m³/0.2pH)
    "muriatic_acid_hcl": 20.0,     # ml/m³ — pH− flüssig (Bayrol: 200 ml/10m³)
    "soda_ash_na2co3": 20.0,       # g/m³  — pH+ (Bayrol: ~15 g/m³/0.2pH)
    "sodium_bicarbonate_nahco3": 50.0,  # g/m³ — TA+ (mild, tolerant)
    "dichlor": 20.0,               # g/m³  — Dichlor Shock (Bayrol: 200 g/10m³)
    "calcium_hypochlorite": 20.0,  # g/m³  — Cal-Hypo Shock
    "sodium_hypochlorite": 20.0,   # ml/m³ — Flüssig-Chlor (Bayrol: 200 ml/10m³)
    "cyanuric_acid": 30.0,         # g/m³  — Stabilisator (Batch-Anwendung üblich)
}

# Wartezeit zwischen Teildosen je Produkt-Typ (Stunden). Chemie-abhängig:
# schnell-wirkende/mild lösliche Produkte kürzer, langsam-lösende länger.
# Quellen: Bayrol/TFP-Praxis.
DOSE_INTERVAL_PER_CHEMICAL = {
    "dry_acid_nahso4": 4,              # Trockensäure — zirkulieren lassen
    "muriatic_acid_hcl": 4,            # Salzsäure — zirkulieren, nicht zu schnell nachkippen
    "soda_ash_na2co3": 6,              # Soda — kann trüben, länger warten
    "sodium_bicarbonate_nahco3": 2,    # Natron — mild, löst schnell
    "dichlor": 6,                      # Dichlor-Granulat — langsam auflösen
    "calcium_hypochlorite": 6,         # Cal-Hypo — kräftig, Verteilung abwarten
    "sodium_hypochlorite": 2,          # Flüssig-Chlor — wirkt schnell
    "cyanuric_acid": 24,               # CYA — gehört in Filter-/Skimmer-Socke, tagelang
}

# Applikationsmethode je Chemikalie. Faustregel: alles Granulat/Konzentrat im
# Eimer Wasser vorlösen, damit es sich sauber verteilt und den Liner nicht
# punktuell angreift. Ausnahme CYA (zu langsam löslich → Socke).
APPLICATION_METHOD_PER_CHEMICAL = {
    "dry_acid_nahso4": (
        "**Im Eimer Wasser auflösen**, dann bei laufender Pumpe langsam ins Becken."
    ),
    "muriatic_acid_hcl": (
        "**Eimer erst mit Wasser füllen, dann Säure langsam hineingeben** "
        "(niemals umgekehrt — exothermes Spritzen). Bei laufender Pumpe ins tiefe Becken."
    ),
    "soda_ash_na2co3": (
        "**Im Eimer Wasser auflösen**, dann bei laufender Pumpe langsam ins Becken."
    ),
    "sodium_bicarbonate_nahco3": (
        "**Im Eimer Wasser auflösen**, dann bei laufender Pumpe langsam ins Becken."
    ),
    "dichlor": (
        "**Im Eimer Wasser vollständig auflösen** — ungelöste Körner bleichen den Liner (weiße Flecken)."
    ),
    "calcium_hypochlorite": (
        "**Im Eimer Wasser vollständig auflösen** — ungelöste Körner bleichen den Liner, "
        "Kalzium-Sediment am Boden möglich."
    ),
    "sodium_hypochlorite": (
        "**Im Eimer 1:5 mit Wasser verdünnen**, dann bei laufender Pumpe langsam ins Becken — "
        "schonendere Verteilung als direkt einkippen."
    ),
    "cyanuric_acid": (
        "**In Skimmer- oder Filter-Socke** geben (Eimer zu langsam löslich). "
        "Pumpe 24–48 h laufen lassen, erst dann neu messen."
    ),
}


def _method_hint(chemical_type: str) -> str | None:
    """Anwendungs-Hinweis (Eimer/Socke/direkt) für eine Chemikalie."""
    return APPLICATION_METHOD_PER_CHEMICAL.get(chemical_type)


# Öffentlicher Alias — von workflow.py importiert, damit der Render den
# Hinweis an derselben Stelle formulieren kann wie der Calculator.
method_hint = _method_hint


def method_plain(chemical_type: str) -> str:
    """Methoden-Hinweis ohne Markdown-Bold, für Bullet-/Inline-Nutzung."""
    m = _method_hint(chemical_type)
    if not m:
        return ""
    return m.replace("**", "")


def format_steps_short(steps: tuple[DoseStep, ...]) -> str:
    """Kurze Beschreibung einer Dosis-Sequenz.

    Uniforme Mehrdosen → "N× X unit Produkt alle Y h".
    Einzeldose → "X unit Produkt".
    Nicht-uniform → Pfeilkette.
    """
    if not steps:
        return ""
    amounts = {s.amount for s in steps}
    if len(steps) >= 2 and len(amounts) == 1:
        s = steps[0]
        n = len(steps)
        wait = s.wait_hours or 0
        wait_str = f" alle {wait} h" if wait > 0 else ""
        return f"{n}× {s.amount:g} {s.unit} {s.product}{wait_str}"
    if len(steps) == 1:
        s = steps[0]
        return f"{s.amount:g} {s.unit} {s.product}"
    return " → ".join(f"{s.amount:g} {s.unit}" for s in steps)


def format_total_hours(steps: tuple[DoseStep, ...]) -> int:
    """Gesamtzeit bis Kontroll-Messung: n × wait_interval."""
    if not steps:
        return 0
    n = len(steps)
    wait = steps[0].wait_hours or 0
    return n * wait


def format_total_sum(steps: tuple[DoseStep, ...]) -> tuple[float, str] | None:
    """Summiert uniforme Doses. Nur wenn alle gleich."""
    if not steps or len({s.amount for s in steps}) != 1:
        return None
    return steps[0].amount * len(steps), steps[0].unit


def compute_ph_minus_dose(
    *,
    current: float,
    target: float,
    volume_m3: float,
    ph_minus_type: str,
    ph_minus_strength_pct: float,
    ph_minus_display: str,
) -> tuple[DoseStep, ...]:
    """Isolierte Berechnung der pH-minus-Dosis zum Absenken von current → target.
    Wird für TA-Senkung (Format C) wiederverwendet.
    """
    if current <= target:
        return ()
    steps_units_of_01 = (current - target) / 0.1
    if ph_minus_type == PH_MINUS_DRY_ACID:
        pure = G_DRY_ACID_PURE_PER_M3_PER_01_PH * volume_m3 * steps_units_of_01
        total = pure * (100.0 / max(1.0, ph_minus_strength_pct))
        return _split(total, "g", ph_minus_display, PH_MINUS_DRY_ACID, volume_m3)
    if ph_minus_type == PH_MINUS_HCL:
        pure_ml = ML_HCL_33_PER_M3_PER_01_PH * volume_m3 * steps_units_of_01
        total = pure_ml * (33.0 / max(1.0, ph_minus_strength_pct))
        return _split(total, "ml", ph_minus_display, PH_MINUS_HCL, volume_m3)
    return ()


def compute_cya_exchange(
    *, current: float, target: float, volume_m3: float
) -> dict:
    """Berechnung des nötigen Wasser-Teilwechsels um CYA auf target zu bringen."""
    if current <= target:
        return {"percent": 0.0, "liters": 0.0}
    f = 1.0 - (target / current)
    return {
        "percent": f * 100.0,
        "liters": volume_m3 * f * 1000.0,
        "needs_etappen": f * 100.0 > 50,
        "needs_post_shock": f * 100.0 >= 30,
    }


def hocl_percent_at_ph(ph: float) -> float:
    """Anteil aktiver Hypochloriger Säure (HOCl) am freien Chlor, %.
    Henderson-Hasselbalch mit pKa(HOCl) = 7.54 bei 25 °C."""
    import math
    return 100.0 / (1.0 + math.pow(10.0, ph - 7.54))


def _split(
    total: float,
    unit: str,
    product: str,
    chemical_type: str,
    volume_m3: float,
) -> tuple[DoseStep, ...]:
    """Split a total dose into parts, sized by the chemical's per-m³ cap and
    timed by its typical dissolution/circulation interval.
    """
    if total <= 0:
        return ()
    max_part = MAX_DOSE_PER_M3.get(chemical_type, 20.0) * volume_m3
    interval_h = DOSE_INTERVAL_PER_CHEMICAL.get(chemical_type, 4)
    import math
    n_parts = max(1, math.ceil(total / max_part))
    part = total / n_parts
    step = 1.0 if unit == "g" else 10.0
    part = max(step, round(part / step) * step)
    steps = []
    remaining = total
    for i in range(n_parts):
        amount = min(part, remaining)
        if amount <= 0:
            break
        wait = interval_h if (i < n_parts - 1) else 0
        steps.append(DoseStep(amount=round(amount, 1), unit=unit, product=product, wait_hours=wait))
        remaining -= amount
    return tuple(steps)


def recommend_ph(
    *,
    current: float | None,
    target: float,
    ph_min: float,
    ph_max: float,
    ph_critical_low: float,
    ph_critical_high: float,
    volume_m3: float,
    ph_minus_type: str,
    ph_minus_strength_pct: float,
    ph_minus_display: str,
    ph_plus_type: str,
    ph_plus_strength_pct: float,
    ph_plus_display: str,
    ph_dosing_minus: bool,
    ph_dosing_plus: bool,
) -> Recommendation:
    if current is None:
        return Recommendation(action="no_data", steps=(), reason="Kein pH-Messwert vorhanden")
    if ph_min <= current <= ph_max:
        return Recommendation(
            action="ok",
            steps=(),
            reason=f"{current:.2f} (Ziel {target:.2f}, Bereich {ph_min:.1f}–{ph_max:.1f})",
        )

    delta = target - current
    is_critical = current < ph_critical_low or current > ph_critical_high

    # Can the dosing system self-correct in this direction?
    needs_lowering = delta < 0  # pH too high
    can_auto_correct = (needs_lowering and ph_dosing_minus) or (not needs_lowering and ph_dosing_plus)

    if not is_critical and can_auto_correct:
        direction_word = "hoch" if needs_lowering else "niedrig"
        direction_verb = "senken" if needs_lowering else "anheben"
        return Recommendation(
            action="watch",
            steps=(),
            reason=(
                f"{current:.2f} {direction_word} — "
                f"Dosieranlage kann {direction_verb} und sollte selbst regeln"
            ),
            delta=delta,
        )

    steps_units_of_01 = abs(delta) / 0.1

    if delta < 0:
        # Lower pH
        if ph_minus_type == PH_MINUS_DRY_ACID:
            pure = G_DRY_ACID_PURE_PER_M3_PER_01_PH * volume_m3 * steps_units_of_01
            total = pure * (100.0 / max(1.0, ph_minus_strength_pct))
            steps = _split(total, "g", ph_minus_display, PH_MINUS_DRY_ACID, volume_m3)
        elif ph_minus_type == PH_MINUS_HCL:
            pure_ml = ML_HCL_33_PER_M3_PER_01_PH * volume_m3 * steps_units_of_01
            total = pure_ml * (33.0 / max(1.0, ph_minus_strength_pct))
            steps = _split(total, "ml", ph_minus_display, PH_MINUS_HCL, volume_m3)
        else:
            return Recommendation(action="lower", steps=(), reason="Unbekanntes pH− Produkt", delta=delta)
        hocl_pct = hocl_percent_at_ph(current)
        why = (
            f"Basisches Wasser lässt Kalk ausfallen und Chlor verliert Wirksamkeit "
            f"(bei pH {current:.2f} wirken nur noch ~{hocl_pct:.0f} % als Hypochlorige Säure)."
        )
        return Recommendation(
            action="lower",
            steps=steps,
            reason=f"{current:.2f} zu hoch — Ziel {target:.2f}",
            delta=delta,
            is_critical=is_critical,
            why=why,
        )

    # Raise pH
    if ph_plus_type == PH_PLUS_SODA:
        pure = G_SODA_PURE_PER_M3_PER_01_PH * volume_m3 * steps_units_of_01
        total = pure * (100.0 / max(1.0, ph_plus_strength_pct))
        steps = _split(total, "g", ph_plus_display, PH_PLUS_SODA, volume_m3)
    else:
        return Recommendation(action="raise", steps=(), reason="Unbekanntes pH+ Produkt", delta=delta)

    # WHY: für critical härter, für non-critical mit Alternative
    why_text = "Saures Wasser reizt Augen und Haut und greift Liner/Metall an."
    if is_critical:
        why_text = "Saures Wasser reizt Augen und Haut und greift Liner/Metall akut an."
    elif not ph_dosing_plus:
        # Milder, Anlage regelt nicht in diese Richtung → Alternative erwähnen
        why_text += (
            " Alternativ abwarten — pH steigt über Tage durch CO₂-Ausgasung meist natürlich wieder."
        )

    return Recommendation(
        action="raise",
        steps=steps,
        reason=f"{current:.2f} zu niedrig — Ziel {target:.2f}",
        delta=delta,
        is_critical=is_critical,
        why=why_text,
    )


def recommend_alkalinity(
    *,
    current: float | None,
    target: float,
    ta_min: float,
    ta_max: float,
    ta_critical_low: float,
    ta_critical_high: float,
    volume_m3: float,
    ta_plus_type: str,
    ta_plus_strength_pct: float,
    ta_plus_display: str,
    # Kontext für TA-Senkung (Format C braucht pH-Erst-Dosis):
    ph_current: float | None = None,
    ph_minus_type: str = "",
    ph_minus_strength_pct: float = 0.0,
    ph_minus_display: str = "",
) -> Recommendation:
    if current is None:
        return Recommendation(action="no_data", steps=(), reason="Keine Alkalitäts-Messung vorhanden")
    if ta_min <= current <= ta_max:
        return Recommendation(
            action="ok",
            steps=(),
            reason=(
                f"{current:.0f} mg/l "
                f"(Ziel {target:.0f}, Bereich {ta_min:.0f}–{ta_max:.0f})"
            ),
        )

    delta = target - current
    is_critical = current < ta_critical_low or current > ta_critical_high

    if not is_critical:
        direction = "hoch" if delta < 0 else "niedrig"
        return Recommendation(
            action="watch",
            steps=(),
            reason=f"{current:.0f} mg/l {direction} — beobachten",
            delta=delta,
        )

    if delta > 0:
        if ta_plus_type != TA_PLUS_BICARB:
            return Recommendation(action="raise", steps=(), reason="Unbekanntes TA+ Produkt", delta=delta)
        pure = G_BICARB_PURE_PER_M3_PER_10_TA * volume_m3 * (abs(delta) / 10.0)
        total = pure * (100.0 / max(1.0, ta_plus_strength_pct))
        steps = _split(total, "g", ta_plus_display, TA_PLUS_BICARB, volume_m3)
        return Recommendation(
            action="raise",
            steps=steps,
            reason=f"{current:.0f} mg/l zu niedrig — Ziel {target:.0f}",
            delta=delta,
            is_critical=is_critical,
            why="TA ist der pH-Puffer — zu niedrig heißt pH springt bei jeder Dosis unkontrolliert.",
        )

    # Lowering TA — mehrtägiger Prozess. pH-Erst-Dosis wird in workflow für
    # Format C gerendert, Note hier bleibt nur die WHY-Erklärung.
    return Recommendation(
        action="lower",
        steps=(),
        reason=f"{current:.0f} mg/l zu hoch — Ziel {target:.0f}",
        delta=delta,
        is_critical=is_critical,
        why=(
            "TA lässt sich nicht chemisch senken, nur durch CO₂-Ausgasung. Der pH wird "
            "gezielt auf ~7.0 gedrückt, CO₂ entweicht beim Belüften, TA fällt langsam. "
            "Prozess dauert 5–10 Tage."
        ),
    )


def _cl_values_summary(
    free_cl: float | None, combined_cl: float | None, total_cl: float | None
) -> str:
    parts: list[str] = []
    parts.append(f"FC {free_cl:.2f}" if free_cl is not None else "FC —")
    parts.append(f"CC {combined_cl:.2f}" if combined_cl is not None else "CC —")
    parts.append(f"TC {total_cl:.2f}" if total_cl is not None else "TC —")
    return " / ".join(parts) + " mg/l"


def recommend_shock(
    *,
    combined_cl: float | None,
    free_cl: float | None,
    total_cl: float | None,
    fc_min: float,
    fc_max: float,
    fc_target: float,
    fc_critical_low: float,
    fc_critical_high: float,
    cc_max: float,
    cc_critical_high: float,
    volume_m3: float,
    routine_type: str | None,
    routine_strength_pct: float,
    routine_display: str,
    shock_type: str,
    shock_strength_pct: float,
    shock_display: str,
    chlorination_is_salt: bool,
    has_auto_dosing: bool,
    cya: float | None = None,
    water_temp: float | None = None,
) -> Recommendation:
    """Shock / chlorine correction.

    Three-tier behavior:
      1. Combined Cl above cc_critical_high → Shock (breakpoint) with *shock* product.
      2. Free Cl below fc_critical_low → active Raise with *routine* product
         (if configured, else note-only with auto-dosing hint).
      3. Free Cl between fc_critical_low and fc_min → "watch" (no dose), let
         the auto-dosing system correct it.
    """
    values = _cl_values_summary(free_cl, combined_cl, total_cl)
    if combined_cl is None and free_cl is None and total_cl is None:
        return Recommendation(action="no_data", steps=(), reason="Keine Chlor-Messwerte vorhanden")

    # 1. Shock case — always uses the configured SHOCK product
    if combined_cl is not None and combined_cl >= cc_critical_high:
        need_fc_mg_per_l = combined_cl * SHOCK_FC_MULTIPLIER
        rec = _build_cl_dose(
            target_fc_increase=need_fc_mg_per_l,
            volume_m3=volume_m3,
            shock_type=shock_type,
            shock_strength_pct=shock_strength_pct,
            shock_display=shock_display,
            action="shock",
            reason=f"{values} — Breakpoint-Dosierung (CC ≥ {cc_critical_high:.2f})",
        )
        why = (
            f"Chloramine (CC = {combined_cl:.2f} mg/l) haben kritische Schwelle "
            f"({cc_critical_high:.2f}) überschritten — chemisch aufbrechen per "
            f"Breakpoint nötig (FC kurzzeitig auf ~10× CC ≈ {need_fc_mg_per_l:.1f} mg/l). "
            "Gebundenes Chlor reizt Augen und erzeugt Chlorgeruch."
        )
        rec = dataclasses.replace(rec, is_critical=True, why=why)
        return rec

    # 2. Free Cl below critical → aktiver Routine-Shock auf Ziel 10 mg/l
    if free_cl is not None and free_cl < fc_critical_low:
        target_fc_for_shock = float(SHOCK_TARGET_ROUTINE)
        if routine_type:
            rec = _build_cl_dose(
                target_fc_increase=target_fc_for_shock - free_cl,
                volume_m3=volume_m3,
                shock_type=routine_type,
                shock_strength_pct=routine_strength_pct,
                shock_display=routine_display,
                action="raise",
                reason=f"{values} — FC zu niedrig (Ziel {fc_target:.2f})",
            )
        else:
            rec = Recommendation(
                action="raise",
                steps=(),
                reason=f"{values} — FC zu niedrig (Ziel {fc_target:.2f})",
                delta=fc_target - free_cl,
                note="Kein Routine-Chlor konfiguriert — manuelle Dosierung nur über Shock-Produkt möglich.",
            )
        why = (
            f"FC ({free_cl:.2f} mg/l) unter kritischer Untergrenze "
            f"({fc_critical_low:.2f}) — keine wirksame Sanitation, Bakterien und Algen "
            f"können wachsen. Routine-Shock bringt FC schnell auf sichere "
            f"{target_fc_for_shock:.0f} mg/l."
        )
        rec = dataclasses.replace(rec, is_critical=True, why=why)
        return rec

    # 3. Free Cl slightly low → watch
    if free_cl is not None and free_cl < fc_min:
        return Recommendation(
            action="watch",
            steps=(),
            reason=f"{values} — FC niedrig — beobachten",
            delta=fc_target - free_cl,
            why="Dosieranlage sollte selbst nachregeln — falls FC nicht steigt, Kanister und Produktionsrate prüfen.",
        )

    # 4. Free Cl too high
    if free_cl is not None and free_cl > fc_max:
        decay_note = ""
        hours = estimate_fc_decay_hours(
            fc_current=free_cl, fc_target=fc_max, cya=cya, water_temp_c=water_temp
        )
        if hours is not None and hours > 0:
            lo_d = hours * 0.75 / 24
            hi_d = hours * 1.25 / 24
            if hi_d < 1.5:
                range_str = f"{max(1, int(hours * 0.75))}–{max(2, int(hours * 1.25))} h"
            else:
                range_str = f"{lo_d:.1f}–{hi_d:.1f} Tage"
            decay_note = f" Geschätzt ~{range_str} bis FC ≤ {fc_max:.1f}."

        if free_cl > fc_critical_high:
            why = (
                "FC weit über kritischer Obergrenze — Augen-/Haut-Reizung, Bade-Sperre. "
                "Chlor lässt sich nicht sinnvoll entfernen, Abbau nur über UV und Zeit." + decay_note
            )
            return Recommendation(
                action="lower",
                steps=(),
                reason=f"{values} — FC zu hoch — nicht baden",
                delta=free_cl - fc_max,
                is_critical=True,
                why=why,
            )
        why = (
            "FC überdosiert, unkritisch — Filter + UV + Zeit bauen Chlor ab. "
            "Die Dosieranlage pausiert automatisch." + decay_note
        )
        return Recommendation(
            action="watch",
            steps=(),
            reason=f"{values} — FC hoch — Anlage pausiert, klingt ab",
            delta=free_cl - fc_max,
            why=why,
        )

    # 5. Combined Cl elevated but below shock threshold
    if combined_cl is not None and combined_cl > cc_max:
        return Recommendation(
            action="watch",
            steps=(),
            reason=f"{values} — CC hoch — beobachten",
            delta=combined_cl - cc_max,
            why=(
                f"Gebundenes Chlor (Chloramine) leicht erhöht — kann durch normale "
                f"Dosierung wieder sinken. Wenn CC dauerhaft über {cc_max:.2f} mg/l "
                f"bleibt, Breakpoint-Chlorung einleiten."
            ),
        )

    return Recommendation(
        action="ok",
        steps=(),
        reason=(
            f"{values} — Ziel-FC {fc_target:.2f} (Bereich {fc_min:.2f}–{fc_max:.2f}), "
            f"CC max {cc_max:.2f}, Shock ab {cc_critical_high:.2f}"
        ),
    )


def _append_note(rec: Recommendation, extra: str) -> Recommendation:
    combined = f"{rec.note} {extra}".strip() if rec.note else extra
    return dataclasses.replace(rec, note=combined)


def _prefix_note(existing: str | None, prefix: str) -> str:
    """Stellt einen Text vor eine evtl. vorhandene Note — mit Leerzeichen dazwischen."""
    if not existing:
        return prefix
    return f"{prefix} {existing}"


def recommend_cya(
    *,
    current: float | None,
    target: float,
    cya_min: float,
    cya_max: float,
    critical_low: float,
    critical_high: float,
    volume_m3: float,
    cya_display: str,
    cya_strength_pct: float,
) -> Recommendation:
    """Evaluate CYA level. Mirrors the pH/TA semantic but without auto-correction
    (no CYA dosing system exists): inside [min, max] is ok, outside but not
    critical is 'watch', past the critical thresholds gets an active dose /
    water-exchange recommendation.

    critical_low = 0 disables the low-criticality warning (acceptable because
    too-little CYA is never a safety issue, only inefficient chlorination).
    """
    if current is None:
        return Recommendation(action="no_data", steps=(), reason="Keine CYA-Messung vorhanden")
    if cya_min <= current <= cya_max:
        return Recommendation(
            action="ok",
            steps=(),
            reason=(
                f"{current:.0f} mg/l "
                f"(Ziel {target:.0f}, Bereich {cya_min:.0f}–{cya_max:.0f})"
            ),
        )

    # Too low — immer aktiv dosieren. Rot (critical) unter critical_low, gelb sonst.
    if current < cya_min:
        delta = target - current
        is_critical = critical_low > 0 and current < critical_low
        pure_g = delta * volume_m3
        product_g = pure_g * (100.0 / max(1.0, cya_strength_pct)) * 0.8
        step = DoseStep(
            amount=round(product_g, 0),
            unit="g",
            product=cya_display,
            wait_hours=48,
        )
        if is_critical:
            why = (
                "Stabilisator kritisch niedrig — Chlor verbrennt innerhalb weniger "
                "Stunden unter UV, Sanitation bricht praktisch zusammen."
            )
        else:
            why = (
                "Stabilisator fehlt — ohne ihn halbiert sich Chlor unter direkter "
                "Sonne in ~30–60 Min."
            )
        return Recommendation(
            action="raise",
            steps=(step,),
            reason=f"{current:.0f} mg/l zu niedrig — Ziel {target:.0f}",
            delta=delta,
            is_critical=is_critical,
            why=why,
        )

    # Too high — Wasserwechsel empfohlen. Rot über critical_high, gelb zwischen max und critical_high.
    is_critical = current >= critical_high
    if is_critical:
        why = (
            "Stabilisator kritisch hoch — Chlor wird so stark gebunden, dass es "
            "kaum noch desinfiziert. Chemisch nicht senkbar, nur durch Verdünnung."
        )
    else:
        why = (
            "Zu viel Stabilisator — Chlor wird chemisch gebunden und verliert "
            "Sanitationswirkung. Chemisch nicht senkbar, nur durch Verdünnung."
        )
    return Recommendation(
        action="lower",
        steps=(),
        reason=f"{current:.0f} mg/l zu hoch — Ziel {target:.0f}",
        delta=current - target,
        is_critical=is_critical,
        why=why,
    )


def cya_pre_dose_grams(
    *,
    current_cya: float,
    target_cya: float,
    shock_fc_increase: float,
    shock_type: str,
    volume_m3: float,
    cya_strength_pct: float,
) -> float:
    """Grams of pure-CYA product to pre-dose before shocking, so that
    shock-added CYA (if any) rounds out to the target.

    Returns 0 if no pre-dose needed.
    """
    from .const import SHOCK_CYA_PER_PPM_CL, SHOCK_STABILIZED

    shock_cya = (
        shock_fc_increase * SHOCK_CYA_PER_PPM_CL.get(shock_type, 0.0)
        if shock_type in SHOCK_STABILIZED
        else 0.0
    )
    needed = max(0.0, target_cya - current_cya - shock_cya)
    if needed <= 0:
        return 0.0
    pure_g = needed * volume_m3  # 1 mg/l × 1 m³ = 1 g
    return pure_g * (100.0 / max(1.0, cya_strength_pct))


def shock_dose_grams_or_ml(
    *,
    current_fc: float,
    target_fc: float,
    volume_m3: float,
    shock_type: str,
    shock_strength_pct: float,
) -> tuple[float, str] | None:
    """Manual shock dose calculation for workflow steps (not split).
    Returns (amount, unit) or None for unknown product.
    """
    increase = max(0.0, target_fc - current_fc)
    if increase <= 0:
        return 0.0, "g"
    if shock_type == SHOCK_DICHLOR:
        pure = G_ACTIVE_CL_PER_M3_PER_1_FC * volume_m3 * increase
        return pure * (100.0 / max(1.0, shock_strength_pct)), "g"
    if shock_type == SHOCK_CAL_HYPO:
        pure = G_ACTIVE_CL_PER_M3_PER_1_FC * volume_m3 * increase
        return pure * (100.0 / max(1.0, shock_strength_pct)), "g"
    if shock_type == SHOCK_NAOCL_LIQUID:
        pure_ml = ML_NAOCL_PER_M3_PER_1_FC_AT_12_5 * volume_m3 * increase
        return pure_ml * (12.5 / max(1.0, shock_strength_pct)), "ml"
    return None


def expected_redox_mv(
    *, free_cl: float, ph: float, cya: float
) -> float:
    """Rule-of-thumb estimate of expected ORP in mV.

    ORP ≈ 700 + 50·log10(FC) − 20·(pH − 7.2) − 1·(CYA − 30)

    Calibrated for CYA ~30, pH ~7.2, FC 1.0 mg/l → 700 mV.
    Precision: ±30 mV. Use only for plausibility warnings, not exact
    calibration.
    """
    import math

    fc_clamped = max(free_cl, 0.05)
    return 700.0 + 50.0 * math.log10(fc_clamped) - 20.0 * (ph - 7.2) - 1.0 * (cya - 30.0)


def recommend_drift_redox(
    *,
    redox_live: float | None,
    free_cl: float | None,
    ph: float | None,
    cya: float | None,
    threshold_mv: float,
) -> Recommendation:
    """Compare Bayrol redox electrode reading against expected ORP derived
    from current FC + pH + CYA. Rough plausibility check, not precise
    calibration."""
    if redox_live is None or free_cl is None or ph is None:
        return Recommendation(
            action="no_data",
            steps=(),
            reason="Kein Vergleich möglich — Redox, FC oder pH fehlen",
        )
    effective_cya = cya if cya is not None else 30.0
    expected = expected_redox_mv(free_cl=free_cl, ph=ph, cya=effective_cya)
    delta = redox_live - expected
    if abs(delta) <= threshold_mv:
        return Recommendation(
            action="ok",
            steps=(),
            reason=(
                f"{redox_live:.0f} mV vs {expected:.0f} mV "
                f"(abw. {delta:+.0f} mV, Toleranz ±{threshold_mv:.0f} mV)"
            ),
            delta=delta,
        )
    return Recommendation(
        action="calibrate",
        steps=(),
        reason=(
            f"{redox_live:.0f} mV vs {expected:.0f} mV "
            f"(abw. {delta:+.0f} mV > ±{threshold_mv:.0f} mV)"
        ),
        delta=delta,
        note=(
            f"Berechnet aus FC {free_cl:.2f}, pH {ph:.2f}, CYA {effective_cya:.0f}. "
            "Redox-Elektrode prüfen: mit Prüflösung 468 mV kalibrieren, ggf. reinigen "
            "(Alkohol) oder tauschen. Präzision dieser Schätzung ist ±30 mV — bei "
            "einmaliger Abweichung einfach 1–2 Tage beobachten."
        ),
    )


def estimate_fc_decay_hours(
    *,
    fc_current: float,
    fc_target: float,
    cya: float | None,
    water_temp_c: float | None,
) -> float | None:
    """Rough empirical estimate of hours until FC decays from `fc_current` to
    `fc_target`.

    Model: exponential decay with CYA- and temperature-dependent half-life.

    Half-life baseline (outdoor pool, cover open, moderate sun, 25 °C water):
      - CYA < 20:    12 h   (very fast, chlorine unprotected from UV)
      - CYA 20–39:   36 h
      - CYA 40–59:   60 h
      - CYA 60–99:   96 h
      - CYA ≥ 100:  120 h

    Temperature adjustment: doubles per +10 °C (biological demand).

    Returns hours until target reached, or None if inputs insufficient or
    already at/below target.
    """
    import math

    if fc_current <= fc_target:
        return 0.0
    if fc_current <= 0:
        return None

    effective_cya = cya if cya is not None else 30.0
    if effective_cya < 20:
        base_half_life = 12.0
    elif effective_cya < 40:
        base_half_life = 36.0
    elif effective_cya < 60:
        base_half_life = 60.0
    elif effective_cya < 100:
        base_half_life = 96.0
    else:
        base_half_life = 120.0

    temp = water_temp_c if water_temp_c is not None else 25.0
    temp_factor = 2.0 ** ((temp - 25.0) / 10.0)
    half_life = base_half_life / max(0.25, temp_factor)

    return half_life * math.log2(fc_current / fc_target)


def recommend_calibration(
    *,
    ph_auto: float | None,
    ph_manual: float | None,
    threshold: float,
) -> Recommendation:
    """Compare automatic (electrode) vs manual (photometer) pH.

    Caller is responsible for filtering stale manual readings — any value
    passed in here is considered fresh enough for comparison.
    """
    if ph_auto is None or ph_manual is None:
        return Recommendation(
            action="no_data",
            steps=(),
            reason="Kein Vergleich möglich — Auto- oder Manuell-pH fehlt",
        )
    delta = ph_auto - ph_manual
    if abs(delta) <= threshold:
        return Recommendation(
            action="ok",
            steps=(),
            reason=f"{ph_auto:.2f} vs {ph_manual:.2f} (abw. {delta:+.2f}, Toleranz ±{threshold:.2f})",
            delta=delta,
        )
    return Recommendation(
        action="calibrate",
        steps=(),
        reason=f"{ph_auto:.2f} vs {ph_manual:.2f} (abw. {delta:+.2f} > ±{threshold:.2f})",
        delta=delta,
        note=(
            "Elektrode der Dosieranlage gegen Referenz kalibrieren (Pufferlösung pH 7 / pH 4). "
            "Bis dahin den Manuellwert als Wahrheit nehmen."
        ),
    )


def _build_cl_dose(
    *,
    target_fc_increase: float,
    volume_m3: float,
    shock_type: str,
    shock_strength_pct: float,
    shock_display: str,
    action: str,
    reason: str,
) -> Recommendation:
    if shock_type == SHOCK_DICHLOR:
        pure = G_ACTIVE_CL_PER_M3_PER_1_FC * volume_m3 * target_fc_increase
        total = pure * (100.0 / max(1.0, shock_strength_pct))
        steps = _split(total, "g", shock_display, SHOCK_DICHLOR, volume_m3)
    elif shock_type == SHOCK_CAL_HYPO:
        pure = G_ACTIVE_CL_PER_M3_PER_1_FC * volume_m3 * target_fc_increase
        total = pure * (100.0 / max(1.0, shock_strength_pct))
        steps = _split(total, "g", shock_display, SHOCK_CAL_HYPO, volume_m3)
    elif shock_type == SHOCK_NAOCL_LIQUID:
        pure_ml = ML_NAOCL_PER_M3_PER_1_FC_AT_12_5 * volume_m3 * target_fc_increase
        total = pure_ml * (12.5 / max(1.0, shock_strength_pct))
        steps = _split(total, "ml", shock_display, SHOCK_NAOCL_LIQUID, volume_m3)
    else:
        return Recommendation(action=action, steps=(), reason="Unbekanntes Shock-Produkt", delta=target_fc_increase)

    note: str | None = None
    if shock_type in SHOCK_STABILIZED:
        cya_factor = SHOCK_CYA_PER_PPM_CL.get(shock_type, 0.9)
        added_cya = target_fc_increase * cya_factor
        note = (
            f"Bei stabilisiertem Shock ({shock_display}) erhöht sich CYA um "
            f"~{added_cya:.1f} mg/l pro Dosis. Nach mehreren Shocks Cyanursäure prüfen."
        )

    return Recommendation(
        action=action, steps=steps, reason=reason, delta=target_fc_increase, note=note
    )
