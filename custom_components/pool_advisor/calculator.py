"""Pool chemistry dosing calculations.

All formulas are empirical rules of thumb widely used in pool chemistry
literature. They are intentionally conservative — the advisor always splits
doses so the user re-measures before completing a correction.

Volume unit: m³. Dosages returned in grams (dry chemicals) or milliliters
(liquid chemicals).
"""
from __future__ import annotations

from dataclasses import dataclass

from .const import (
    PH_MINUS_DRY_ACID,
    PH_MINUS_HCL,
    PH_PLUS_SODA,
    SHOCK_CAL_HYPO,
    SHOCK_DICHLOR,
    SHOCK_NAOCL_LIQUID,
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

    action: str                       # "raise" | "lower" | "shock" | "ok" | "no_data" | "calibrate"
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
    volume_m3: float,
    ph_minus_type: str,
    ph_minus_strength_pct: float,
    ph_plus_type: str,
    ph_plus_strength_pct: float,
    max_dose_fraction: float,
    interval_h: int,
) -> Recommendation:
    if current is None:
        return Recommendation(action="no_data", steps=(), reason="Kein pH-Messwert vorhanden")
    if ph_min <= current <= ph_max:
        return Recommendation(action="ok", steps=(), reason=f"pH {current:.2f} liegt im Zielbereich")

    delta = target - current
    steps_units_of_01 = abs(delta) / 0.1

    if delta < 0:
        # Lower pH
        if ph_minus_type == PH_MINUS_DRY_ACID:
            pure = G_DRY_ACID_PURE_PER_M3_PER_01_PH * volume_m3 * steps_units_of_01
            total = pure * (100.0 / max(1.0, ph_minus_strength_pct))
            steps = _split(total, "g", ph_minus_type, max_dose_fraction, interval_h)
        elif ph_minus_type == PH_MINUS_HCL:
            pure_ml = ML_HCL_33_PER_M3_PER_01_PH * volume_m3 * steps_units_of_01
            total = pure_ml * (33.0 / max(1.0, ph_minus_strength_pct))
            steps = _split(total, "ml", ph_minus_type, max_dose_fraction, interval_h)
        else:
            return Recommendation(action="lower", steps=(), reason="Unbekanntes pH− Produkt", delta=delta)
        return Recommendation(
            action="lower",
            steps=steps,
            reason=f"pH {current:.2f} zu hoch — Ziel {target:.2f}",
            delta=delta,
        )

    # Raise pH
    if ph_plus_type == PH_PLUS_SODA:
        pure = G_SODA_PURE_PER_M3_PER_01_PH * volume_m3 * steps_units_of_01
        total = pure * (100.0 / max(1.0, ph_plus_strength_pct))
        steps = _split(total, "g", ph_plus_type, max_dose_fraction, interval_h)
    else:
        return Recommendation(action="raise", steps=(), reason="Unbekanntes pH+ Produkt", delta=delta)

    return Recommendation(
        action="raise",
        steps=steps,
        reason=f"pH {current:.2f} zu niedrig — Ziel {target:.2f}",
        delta=delta,
    )


def recommend_alkalinity(
    *,
    current: float | None,
    target: float,
    ta_min: float,
    ta_max: float,
    volume_m3: float,
    ta_plus_type: str,
    ta_plus_strength_pct: float,
    max_dose_fraction: float,
    interval_h: int,
) -> Recommendation:
    if current is None:
        return Recommendation(action="no_data", steps=(), reason="Keine Alkalitäts-Messung vorhanden")
    if ta_min <= current <= ta_max:
        return Recommendation(action="ok", steps=(), reason=f"Alkalität {current:.0f} mg/l im Zielbereich")

    delta = target - current
    if delta > 0:
        if ta_plus_type != TA_PLUS_BICARB:
            return Recommendation(action="raise", steps=(), reason="Unbekanntes TA+ Produkt", delta=delta)
        pure = G_BICARB_PURE_PER_M3_PER_10_TA * volume_m3 * (abs(delta) / 10.0)
        total = pure * (100.0 / max(1.0, ta_plus_strength_pct))
        steps = _split(total, "g", ta_plus_type, max_dose_fraction, interval_h)
        return Recommendation(
            action="raise",
            steps=steps,
            reason=f"Alkalität {current:.0f} mg/l zu niedrig — Ziel {target:.0f}",
            delta=delta,
        )

    # Lowering TA is a multi-day process (pH-down + aeration). Don't produce gram numbers;
    # give a guided note instead.
    return Recommendation(
        action="lower",
        steps=(),
        reason=f"Alkalität {current:.0f} mg/l zu hoch — Ziel {target:.0f}",
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
    cc_shock_at: float,
    volume_m3: float,
    shock_type: str,
    shock_strength_pct: float,
    max_dose_fraction: float,
    interval_h: int,
    chlorination_is_salt: bool,
) -> Recommendation:
    """Shock / chlorine correction.

    Priority:
    1. If combined Cl above threshold → shock dose (breakpoint).
    2. Else if free Cl below minimum → raise free Cl to target.
    3. Else OK.
    """
    if combined_cl is None and free_cl is None:
        return Recommendation(action="no_data", steps=(), reason="Keine Chlor-Messwerte vorhanden")

    # Shock case
    if combined_cl is not None and combined_cl >= cc_shock_at:
        if chlorination_is_salt:
            return Recommendation(
                action="shock",
                steps=(),
                reason=f"Gebundenes Chlor {combined_cl:.2f} mg/l — Shock nötig",
                delta=combined_cl,
                note=(
                    "Salzelektrolyse: Redox-Sollwert temporär anheben ODER manuell mit "
                    "Chlor-Granulat/Flüssig-Chlor schocken. Produktwahl siehe Konfiguration."
                ),
            )
        need_fc_mg_per_l = combined_cl * SHOCK_FC_MULTIPLIER
        return _build_cl_dose(
            target_fc_increase=need_fc_mg_per_l,
            volume_m3=volume_m3,
            shock_type=shock_type,
            shock_strength_pct=shock_strength_pct,
            max_dose_fraction=max_dose_fraction,
            interval_h=interval_h,
            action="shock",
            reason=f"Gebundenes Chlor {combined_cl:.2f} mg/l — Breakpoint-Dosierung",
        )

    # Low free Cl
    if free_cl is not None and free_cl < fc_min:
        if chlorination_is_salt:
            return Recommendation(
                action="raise",
                steps=(),
                reason=f"Freies Chlor {free_cl:.2f} mg/l zu niedrig",
                delta=fc_target - free_cl,
                note=(
                    "Salzelektrolyse: Produktionsrate erhöhen oder Redox-Sollwert anheben. "
                    "Manuelle Chlor-Dosierung nur als Notfallmaßnahme."
                ),
            )
        return _build_cl_dose(
            target_fc_increase=fc_target - free_cl,
            volume_m3=volume_m3,
            shock_type=shock_type,
            shock_strength_pct=shock_strength_pct,
            max_dose_fraction=max_dose_fraction,
            interval_h=interval_h,
            action="raise",
            reason=f"Freies Chlor {free_cl:.2f} zu niedrig — Ziel {fc_target:.2f}",
        )

    return Recommendation(action="ok", steps=(), reason="Chlor-Werte ok")


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
    max_dose_fraction: float,
    interval_h: int,
    action: str,
    reason: str,
) -> Recommendation:
    if shock_type == SHOCK_DICHLOR:
        pure = G_DICHLOR_PURE_PER_M3_PER_1_FC * volume_m3 * target_fc_increase * 10.0
        total = pure * (100.0 / max(1.0, shock_strength_pct))
        steps = _split(total, "g", shock_type, max_dose_fraction, interval_h)
    elif shock_type == SHOCK_CAL_HYPO:
        pure = G_CAL_HYPO_PURE_PER_M3_PER_1_FC * volume_m3 * target_fc_increase * 10.0
        total = pure * (100.0 / max(1.0, shock_strength_pct))
        steps = _split(total, "g", shock_type, max_dose_fraction, interval_h)
    elif shock_type == SHOCK_NAOCL_LIQUID:
        pure_ml = ML_NAOCL_PURE_PER_M3_PER_1_FC * volume_m3 * target_fc_increase
        total = pure_ml * (12.5 / max(1.0, shock_strength_pct))
        steps = _split(total, "ml", shock_type, max_dose_fraction, interval_h)
    else:
        return Recommendation(action=action, steps=(), reason="Unbekanntes Shock-Produkt", delta=target_fc_increase)

    return Recommendation(action=action, steps=steps, reason=reason, delta=target_fc_increase)
