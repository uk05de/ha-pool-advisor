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
    note: str | None = None           # optional hint


# ---- base rules (per m³ water, per 0.1 pH / per 10 mg/l TA / per 1 mg/l Cl) ----
# Source: common pool chemistry tables. Values are for the *active* compound.
# We then divide by product strength% to get grams/ml of the commercial product.

# To raise pH by 0.1 in 10 m³: ~100 g soda ash (Na2CO3, pure)
G_SODA_PURE_PER_M3_PER_01_PH = 10.0

# To lower pH by 0.1 in 10 m³: ~100 g dry acid (NaHSO4, pure) OR ~100 ml HCl 33%
G_DRY_ACID_PURE_PER_M3_PER_01_PH = 10.0
ML_HCL_33_PER_M3_PER_01_PH = 10.0

# To raise TA by 10 mg/l in 10 m³: ~170 g sodium bicarb (pure)
G_BICARB_PURE_PER_M3_PER_10_TA = 17.0

# To raise free Cl by 1 mg/l in 10 m³:
G_DICHLOR_PURE_PER_M3_PER_1_FC = 1.67   # ~16.7 g active Cl per m³ for 1 mg/l
G_CAL_HYPO_PURE_PER_M3_PER_1_FC = 1.5
ML_NAOCL_PURE_PER_M3_PER_1_FC = 12.0    # liquid 12.5% gives ~1 mg/l per 10 m³ with ~120 ml

# Shock multiplier on combined chlorine (breakpoint chlorination)
SHOCK_FC_MULTIPLIER = 10.0


def _split(total: float, unit: str, product: str, max_fraction: float, interval_h: int) -> tuple[DoseStep, ...]:
    """Split a total dose into parts no larger than `max_fraction` of the total."""
    if total <= 0:
        return ()
    max_fraction = max(0.1, min(max_fraction, 1.0))
    n_parts = max(1, int(-(-1 // max_fraction)))  # ceil(1/max_fraction)
    # Round part up to 1 g / 10 ml for usability
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
    max_dose_fraction: float,
    interval_h: int,
    has_auto_dosing: bool,
) -> Recommendation:
    if current is None:
        return Recommendation(action="no_data", steps=(), reason="Kein pH-Messwert vorhanden")
    if ph_min <= current <= ph_max:
        return Recommendation(action="ok", steps=(), reason=f"pH {current:.2f} liegt im Zielbereich")

    delta = target - current
    is_critical = current < ph_critical_low or current > ph_critical_high

    # Slight deviation + auto dosing present → watch-only, let the system regulate.
    if not is_critical and has_auto_dosing:
        return Recommendation(
            action="watch",
            steps=(),
            reason=(
                f"pH {current:.2f} leicht außerhalb {ph_min:.1f}–{ph_max:.1f} — "
                "Dosieranlage sollte selbst regeln"
            ),
            delta=delta,
            note="Wenn Abweichung bestehen bleibt: Kanister, Elektrode und Sollwert der Anlage prüfen.",
        )

    steps_units_of_01 = abs(delta) / 0.1

    if delta < 0:
        # Lower pH
        if ph_minus_type == PH_MINUS_DRY_ACID:
            pure = G_DRY_ACID_PURE_PER_M3_PER_01_PH * volume_m3 * steps_units_of_01
            total = pure * (100.0 / max(1.0, ph_minus_strength_pct))
            steps = _split(total, "g", ph_minus_display, max_dose_fraction, interval_h)
        elif ph_minus_type == PH_MINUS_HCL:
            pure_ml = ML_HCL_33_PER_M3_PER_01_PH * volume_m3 * steps_units_of_01
            total = pure_ml * (33.0 / max(1.0, ph_minus_strength_pct))
            steps = _split(total, "ml", ph_minus_display, max_dose_fraction, interval_h)
        else:
            return Recommendation(action="lower", steps=(), reason="Unbekanntes pH− Produkt", delta=delta)
        rec = Recommendation(
            action="lower",
            steps=steps,
            reason=f"pH {current:.2f} kritisch hoch — Ziel {target:.2f}",
            delta=delta,
        )
        if has_auto_dosing:
            rec = _append_note(
                rec, "Alternative: pH-Dosieranlage prüfen (Kanister leer? Elektrode defekt? Sollwert?)."
            )
        return rec

    # Raise pH
    if ph_plus_type == PH_PLUS_SODA:
        pure = G_SODA_PURE_PER_M3_PER_01_PH * volume_m3 * steps_units_of_01
        total = pure * (100.0 / max(1.0, ph_plus_strength_pct))
        steps = _split(total, "g", ph_plus_display, max_dose_fraction, interval_h)
    else:
        return Recommendation(action="raise", steps=(), reason="Unbekanntes pH+ Produkt", delta=delta)

    rec = Recommendation(
        action="raise",
        steps=steps,
        reason=f"pH {current:.2f} kritisch niedrig — Ziel {target:.2f}",
        delta=delta,
    )
    if has_auto_dosing:
        rec = _append_note(
            rec, "Alternative: pH-Dosieranlage prüfen (Sollwert, Elektrode-Kalibrierung)."
        )
    return rec


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
    max_dose_fraction: float,
    interval_h: int,
) -> Recommendation:
    if current is None:
        return Recommendation(action="no_data", steps=(), reason="Keine Alkalitäts-Messung vorhanden")
    if ta_min <= current <= ta_max:
        return Recommendation(action="ok", steps=(), reason=f"Alkalität {current:.0f} mg/l im Zielbereich")

    delta = target - current
    is_critical = current < ta_critical_low or current > ta_critical_high

    if not is_critical:
        return Recommendation(
            action="watch",
            steps=(),
            reason=(
                f"Alkalität {current:.0f} mg/l leicht außerhalb {ta_min:.0f}–{ta_max:.0f} — beobachten"
            ),
            delta=delta,
            note="Bei nächster Messung beobachten, noch kein Eingriff nötig.",
        )

    if delta > 0:
        if ta_plus_type != TA_PLUS_BICARB:
            return Recommendation(action="raise", steps=(), reason="Unbekanntes TA+ Produkt", delta=delta)
        pure = G_BICARB_PURE_PER_M3_PER_10_TA * volume_m3 * (abs(delta) / 10.0)
        total = pure * (100.0 / max(1.0, ta_plus_strength_pct))
        steps = _split(total, "g", ta_plus_display, max_dose_fraction, interval_h)
        return Recommendation(
            action="raise",
            steps=steps,
            reason=f"Alkalität {current:.0f} mg/l kritisch niedrig — Ziel {target:.0f}",
            delta=delta,
        )

    # Lowering TA is a multi-day process (pH-down + aeration). Don't produce gram numbers;
    # give a guided note instead.
    return Recommendation(
        action="lower",
        steps=(),
        reason=f"Alkalität {current:.0f} mg/l kritisch hoch — Ziel {target:.0f}",
        delta=delta,
        note=(
            "TA senken erfolgt nicht durch einmalige Dosierung: pH gezielt auf ~7.0 senken, "
            "kräftig belüften (Düsen nach oben / Wasserfall), über mehrere Tage wiederholen, "
            "zwischendurch neu messen."
        ),
    )


def recommend_shock(
    *,
    combined_cl: float | None,
    free_cl: float | None,
    fc_min: float,
    fc_target: float,
    fc_critical_low: float,
    cc_shock_at: float,
    volume_m3: float,
    routine_type: str | None,
    routine_strength_pct: float,
    routine_display: str,
    shock_type: str,
    shock_strength_pct: float,
    shock_display: str,
    max_dose_fraction: float,
    interval_h: int,
    chlorination_is_salt: bool,
    has_auto_dosing: bool,
) -> Recommendation:
    """Shock / chlorine correction.

    Three-tier behavior:
      1. Combined Cl above cc_shock_at → Shock (breakpoint) with *shock* product.
      2. Free Cl below fc_critical_low → active Raise with *routine* product
         (if configured, else note-only with auto-dosing hint).
      3. Free Cl between fc_critical_low and fc_min → "watch" (no dose), let
         the auto-dosing system correct it.
    """
    if combined_cl is None and free_cl is None:
        return Recommendation(action="no_data", steps=(), reason="Keine Chlor-Messwerte vorhanden")

    # 1. Shock case — always uses the configured SHOCK product
    if combined_cl is not None and combined_cl >= cc_shock_at:
        need_fc_mg_per_l = combined_cl * SHOCK_FC_MULTIPLIER
        rec = _build_cl_dose(
            target_fc_increase=need_fc_mg_per_l,
            volume_m3=volume_m3,
            shock_type=shock_type,
            shock_strength_pct=shock_strength_pct,
            shock_display=shock_display,
            max_dose_fraction=max_dose_fraction,
            interval_h=interval_h,
            action="shock",
            reason=f"Gebundenes Chlor {combined_cl:.2f} mg/l — Breakpoint-Dosierung",
        )
        if chlorination_is_salt:
            rec = _append_note(
                rec,
                "Alternativ unterstützend: Redox-Sollwert temporär anheben. "
                "Für die eigentliche Breakpoint-Menge ist die manuelle Dosis empfohlen "
                "(Dosierpumpen liefern nicht schnell genug).",
            )
        return rec

    # 2. Free Cl below critical → active raise with ROUTINE product
    if free_cl is not None and free_cl < fc_critical_low:
        if routine_type:
            rec = _build_cl_dose(
                target_fc_increase=fc_target - free_cl,
                volume_m3=volume_m3,
                shock_type=routine_type,
                shock_strength_pct=routine_strength_pct,
                shock_display=routine_display,
                max_dose_fraction=max_dose_fraction,
                interval_h=interval_h,
                action="raise",
                reason=f"Freies Chlor {free_cl:.2f} mg/l kritisch niedrig — Ziel {fc_target:.2f}",
            )
        else:
            rec = Recommendation(
                action="raise",
                steps=(),
                reason=f"Freies Chlor {free_cl:.2f} mg/l kritisch niedrig — Ziel {fc_target:.2f}",
                delta=fc_target - free_cl,
                note="Kein Routine-Chlor konfiguriert — manuelle Dosierung nur über Shock-Produkt möglich.",
            )
        if chlorination_is_salt:
            rec = _append_note(
                rec,
                "Alternativer Weg: Redox-Sollwert erhöhen oder Produktionsrate der "
                "Elektrolyse anheben — dann keine manuelle Dosierung nötig.",
            )
        elif has_auto_dosing:
            rec = _append_note(
                rec,
                "Alternativer Weg: Chlor-Kanister der Dosieranlage prüfen (leer?) und "
                "Produktionsrate der Dosierpumpe erhöhen.",
            )
        return rec

    # 3. Free Cl slightly low → watch
    if free_cl is not None and free_cl < fc_min:
        return Recommendation(
            action="watch",
            steps=(),
            reason=f"Freies Chlor {free_cl:.2f} mg/l leicht unter {fc_min:.2f} — beobachten",
            delta=fc_target - free_cl,
            note=(
                "Dosieranlage sollte selbst nachregeln." if (chlorination_is_salt or has_auto_dosing)
                else None
            ),
        )

    return Recommendation(action="ok", steps=(), reason="Chlor-Werte ok")


def _append_note(rec: Recommendation, extra: str) -> Recommendation:
    combined = f"{rec.note} {extra}".strip() if rec.note else extra
    return dataclasses.replace(rec, note=combined)


def recommend_cya(
    *,
    current: float | None,
    target: float,
    watch_at: float,
    critical_at: float,
) -> Recommendation:
    """Evaluate ongoing CYA level. No dosing produced here — CYA only goes up
    (via dichlor shocks or explicit pre-dose at commissioning), and is lowered
    only by partial water replacement."""
    if current is None:
        return Recommendation(action="no_data", steps=(), reason="Keine CYA-Messung vorhanden")
    if current < target * 0.6:
        return Recommendation(
            action="raise",
            steps=(),
            reason=f"Cyanursäure {current:.0f} mg/l unter Ziel {target:.0f}",
            delta=target - current,
            note="Vor-Dosierung nur relevant bei Inbetriebnahme — siehe Workflow 'Frischwasser'.",
        )
    if current >= critical_at:
        return Recommendation(
            action="lower",
            steps=(),
            reason=f"Cyanursäure {current:.0f} mg/l kritisch hoch",
            delta=current - target,
            note=(
                "CYA lässt sich chemisch nicht senken. Ca. 30 % Wasser teiltauschen und "
                "danach neu messen. Häufige Schocks mit Dichlor vermeiden — auf Flüssig-Chlor "
                "(NaOCl) oder Calciumhypochlorit umstellen."
            ),
        )
    if current >= watch_at:
        return Recommendation(
            action="watch",
            steps=(),
            reason=f"Cyanursäure {current:.0f} mg/l erhöht — beobachten",
            delta=current - target,
            note="Bei nächsten Schocks bewusst kein Dichlor nehmen — dann steigt CYA nicht weiter.",
        )
    return Recommendation(action="ok", steps=(), reason=f"Cyanursäure {current:.0f} mg/l im Zielbereich")


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
        pure = G_DICHLOR_PURE_PER_M3_PER_1_FC * volume_m3 * increase * 10.0
        return pure * (100.0 / max(1.0, shock_strength_pct)), "g"
    if shock_type == SHOCK_CAL_HYPO:
        pure = G_CAL_HYPO_PURE_PER_M3_PER_1_FC * volume_m3 * increase * 10.0
        return pure * (100.0 / max(1.0, shock_strength_pct)), "g"
    if shock_type == SHOCK_NAOCL_LIQUID:
        pure_ml = ML_NAOCL_PURE_PER_M3_PER_1_FC * volume_m3 * increase
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
    reason_core = (
        f"Anlage {redox_live:.0f} mV vs Erwartung {expected:.0f} mV "
        f"(FC {free_cl:.2f}, pH {ph:.2f}, CYA {effective_cya:.0f})"
    )
    if abs(delta) <= threshold_mv:
        return Recommendation(
            action="ok",
            steps=(),
            reason=f"{reason_core} — Abweichung {delta:+.0f} mV im Toleranzbereich",
            delta=delta,
        )
    return Recommendation(
        action="calibrate",
        steps=(),
        reason=f"{reason_core} — Abweichung {delta:+.0f} mV > Schwelle {threshold_mv:.0f} mV",
        delta=delta,
        note=(
            "Redox-Elektrode prüfen: mit Prüflösung 468 mV kalibrieren, "
            "ggf. reinigen (Alkohol) oder tauschen. Präzision dieser Schätzung "
            "ist ±30 mV — bei einmaliger Abweichung einfach 1–2 Tage beobachten."
        ),
    )


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
            reason=f"Auto {ph_auto:.2f} vs Manuell {ph_manual:.2f} — Abweichung {delta:+.2f} im Toleranzbereich",
            delta=delta,
        )
    return Recommendation(
        action="calibrate",
        steps=(),
        reason=(
            f"Auto {ph_auto:.2f} vs Manuell {ph_manual:.2f} — Abweichung {delta:+.2f} "
            f"> Schwelle {threshold:.2f}"
        ),
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
    max_dose_fraction: float,
    interval_h: int,
    action: str,
    reason: str,
) -> Recommendation:
    if shock_type == SHOCK_DICHLOR:
        pure = G_DICHLOR_PURE_PER_M3_PER_1_FC * volume_m3 * target_fc_increase * 10.0
        total = pure * (100.0 / max(1.0, shock_strength_pct))
        steps = _split(total, "g", shock_display, max_dose_fraction, interval_h)
    elif shock_type == SHOCK_CAL_HYPO:
        pure = G_CAL_HYPO_PURE_PER_M3_PER_1_FC * volume_m3 * target_fc_increase * 10.0
        total = pure * (100.0 / max(1.0, shock_strength_pct))
        steps = _split(total, "g", shock_display, max_dose_fraction, interval_h)
    elif shock_type == SHOCK_NAOCL_LIQUID:
        pure_ml = ML_NAOCL_PURE_PER_M3_PER_1_FC * volume_m3 * target_fc_increase
        total = pure_ml * (12.5 / max(1.0, shock_strength_pct))
        steps = _split(total, "ml", shock_display, max_dose_fraction, interval_h)
    else:
        return Recommendation(action=action, steps=(), reason="Unbekanntes Shock-Produkt", delta=target_fc_increase)

    note: str | None = None
    if shock_type in SHOCK_STABILIZED:
        cya_factor = SHOCK_CYA_PER_PPM_CL.get(shock_type, 0.9)
        added_cya = target_fc_increase * cya_factor
        note = (
            f"⚠ {shock_display} bringt Cyanursäure mit ins Wasser "
            f"(~{added_cya:.1f} mg/l pro dieser Dosis). "
            "Cyanursäure messen und bei >50–75 mg/l Wasser teilverdünnen. "
            "CYA-frei schocken: Flüssig-Chlor (NaOCl) oder Monopersulfat/Oxi."
        )

    return Recommendation(
        action=action, steps=steps, reason=reason, delta=target_fc_increase, note=note
    )
