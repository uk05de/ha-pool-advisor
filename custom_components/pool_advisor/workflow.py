"""Kontext-abhängige Empfehlungs-Renderer.

Vier Modi, jeweils eine `render(ctx)`-Funktion die eine vollständige
Markdown-Liste zurückgibt. Keine Step-Engine, kein State — alle Einträge
werden live aus dem aktuellen Snapshot berechnet und bekommen ein
Status-Symbol (✅ / ⚠ / ○).

Der User pickt aus der Liste was er tut, in der Reihenfolge die er für
richtig hält. Wenn ein Wert im Ziel liegt, steht dort nur die
Zusammenfassung — keine Dosis-Empfehlung.
"""
from __future__ import annotations

from dataclasses import dataclass

from .calculator import (
    Recommendation,
    cya_pre_dose_grams,
    estimate_fc_decay_hours,
    shock_dose_grams_or_ml,
)
from .const import (
    MODE_NORMAL,
    MODE_SAISONSTART,
    MODE_SCHOCKCHLORUNG,
    MODE_WASSERWECHSEL,
    SHOCK_CYA_PER_PPM_CL,
    SHOCK_STABILIZED,
    SHOCK_TARGET_ALGEN_LEICHT,
    SHOCK_TARGET_ALGEN_STARK,
    SHOCK_TARGET_ROUTINE,
    SHOCK_TARGET_SCHWARZALGEN,
)


# ---------- Kontext ----------


@dataclass
class WorkflowContext:
    volume_m3: float

    # Produkt-Displaynamen (User-Config)
    ph_minus_display: str
    ph_plus_display: str
    ta_plus_display: str
    routine_cl_display: str
    shock_display: str
    shock_type: str
    shock_strength_pct: float
    cya_display: str
    cya_strength_pct: float

    # Messwerte
    ph_auto: float | None
    ph_manual: float | None
    ta: float | None
    fc: float | None
    cc: float | None
    cya: float | None

    # Targets
    ph_target: float
    ta_target: float
    fc_target: float
    cya_target: float

    ph_min: float = 7.0
    ph_max: float = 7.4
    ta_min: float = 80.0
    ta_max: float = 120.0
    water_temp: float | None = None


# ---------- Hilfsfunktionen ----------


def _eff_ph(ctx: WorkflowContext) -> float | None:
    return ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto


def _ta_dose_g(ctx: WorkflowContext) -> float | None:
    from .calculator import G_BICARB_PURE_PER_M3_PER_10_TA

    if ctx.ta is None:
        return None
    delta = ctx.ta_target - ctx.ta
    if delta <= 0:
        return 0.0
    return G_BICARB_PURE_PER_M3_PER_10_TA * ctx.volume_m3 * (delta / 10.0)


def _ph_dose(ctx: WorkflowContext) -> tuple[str, float] | None:
    """Returns (direction, grams) or None if no action. direction is 'up' or 'down'."""
    from .calculator import (
        G_DRY_ACID_PURE_PER_M3_PER_01_PH,
        G_SODA_PURE_PER_M3_PER_01_PH,
    )

    ph = _eff_ph(ctx)
    if ph is None:
        return None
    if ctx.ph_min <= ph <= ctx.ph_max:
        return None
    delta = ctx.ph_target - ph
    units = abs(delta) / 0.1
    if delta > 0:
        return ("up", G_SODA_PURE_PER_M3_PER_01_PH * ctx.volume_m3 * units)
    return ("down", G_DRY_ACID_PURE_PER_M3_PER_01_PH * ctx.volume_m3 * units)


def _cya_predose_g(ctx: WorkflowContext, shock_target_fc: float) -> float:
    current = ctx.cya if ctx.cya is not None else 0.0
    shock_increase = max(0.0, shock_target_fc - (ctx.fc or 0.0))
    g = cya_pre_dose_grams(
        current_cya=current,
        target_cya=ctx.cya_target,
        shock_fc_increase=shock_increase,
        shock_type=ctx.shock_type,
        volume_m3=ctx.volume_m3,
        cya_strength_pct=ctx.cya_strength_pct,
    )
    return g * 0.8  # 80 % Sicherheitspuffer


def _shock_dose(ctx: WorkflowContext, target_fc: float) -> tuple[float, str] | None:
    current_fc = ctx.fc if ctx.fc is not None else 0.0
    return shock_dose_grams_or_ml(
        current_fc=current_fc,
        target_fc=target_fc,
        volume_m3=ctx.volume_m3,
        shock_type=ctx.shock_type,
        shock_strength_pct=ctx.shock_strength_pct,
    )


def _cya_from_shock(ctx: WorkflowContext, target_fc: float) -> float:
    """Erwarteter CYA-Eintrag durch diese Shock-Dosis (falls stabilisiertes Produkt)."""
    if ctx.shock_type not in SHOCK_STABILIZED:
        return 0.0
    increase = max(0.0, target_fc - (ctx.fc or 0.0))
    return increase * SHOCK_CYA_PER_PPM_CL.get(ctx.shock_type, 0.9)


def _val(v: float | None, unit: str, dec: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:.{dec}f} {unit}".rstrip()


# ---------- Normalbetrieb: nutzt bestehende Recommendation-Objekte ----------


ACTION_ICONS = {
    "ok": "✅",
    "watch": "👁",
    "raise": "⚠",
    "lower": "⚠",
    "shock": "🚨",
    "calibrate": "🎯",
    "no_data": "❔",
}


def _render_rec(title: str, rec: Recommendation | None) -> list[str]:
    if rec is None:
        return []
    icon = ACTION_ICONS.get(rec.action, "")
    lines: list[str] = [f"### {icon} {title}", rec.reason]
    if rec.steps:
        lines.append("")
        for i, s in enumerate(rec.steps, 1):
            lines.append(f"{i}. **{s.amount:g} {s.unit}** {s.product}")
            if s.wait_hours > 0 and i < len(rec.steps):
                lines.append(f"   ⏳ dann **{s.wait_hours} h warten**, Filter an")
    if rec.note:
        lines.append("")
        lines.append(f"> {rec.note}")
    lines.append("")
    return lines


def render_normal(ctx: WorkflowContext, recs: dict[str, Recommendation]) -> str:
    lines: list[str] = ["## Pool-Empfehlung — Normalbetrieb", ""]
    for key, title in (
        ("ph", "pH"),
        ("alkalinity", "Alkalität"),
        ("chlorine", "Chlor"),
        ("cya", "Cyanursäure"),
        ("calibration", "Drift pH Sonde"),
        ("drift_redox", "Drift Redox Sonde"),
    ):
        lines.extend(_render_rec(title, recs.get(key)))
    # Badebetrieb-Freigabe als finale Sektion
    lines.append("---")
    lines.append("")
    lines.extend(_swim_ready_block(ctx))
    return "\n".join(lines)


# ---------- Inbetriebnahme-Listen (Wasserwechsel / Saisonstart) ----------


def _inbetriebnahme_list(ctx: WorkflowContext, shock_target_fc: float, shock_label: str, include_brush: bool) -> list[str]:
    L: list[str] = []

    # 1. TA
    if ctx.ta is None:
        L += ["### ❔ 1. Alkalität", "TA noch nicht gemessen.", ""]
    elif ctx.ta_min <= ctx.ta <= ctx.ta_max:
        L += [f"### ✅ 1. Alkalität", f"TA **{ctx.ta:.0f} mg/l** (Ziel {ctx.ta_target:.0f}, Bereich {ctx.ta_min:.0f}–{ctx.ta_max:.0f}).", ""]
    else:
        dose = _ta_dose_g(ctx)
        if dose and dose > 0:
            L += [
                f"### ⚠ 1. Alkalität anheben",
                f"TA **{ctx.ta:.0f} mg/l** — Ziel {ctx.ta_target:.0f}.",
                "",
                f"Dosiere **{dose:.0f} g {ctx.ta_plus_display}** (in Eimer auflösen, verteilen).",
                "Filter 12–24 h durchlaufen, dann neu messen.",
                "",
            ]
        else:
            L += [
                f"### ⚠ 1. Alkalität senken",
                f"TA **{ctx.ta:.0f} mg/l** — Ziel {ctx.ta_target:.0f}.",
                "",
                "Mehrtägiger Prozess: pH auf ~7.0 senken, kräftig belüften, wiederholen.",
                "",
            ]

    # 2. pH grob
    ph = _eff_ph(ctx)
    if ph is None:
        L += ["### ❔ 2. pH grob", "pH noch nicht gemessen.", ""]
    elif ctx.ph_min <= ph <= ctx.ph_max:
        L += [f"### ✅ 2. pH grob", f"pH **{ph:.2f}** (Ziel {ctx.ph_target:.2f}, Bereich {ctx.ph_min:.1f}–{ctx.ph_max:.1f}).", ""]
    else:
        dose = _ph_dose(ctx)
        if dose:
            direction, grams = dose
            if direction == "up":
                L += [
                    f"### ⚠ 2. pH anheben",
                    f"pH **{ph:.2f}** — Ziel {ctx.ph_target:.2f}.",
                    "",
                    f"Dosiere **{grams:.0f} g {ctx.ph_plus_display}**. Filter 4–6 h, neu messen.",
                    "",
                ]
            else:
                L += [
                    f"### ⚠ 2. pH senken",
                    f"pH **{ph:.2f}** — Ziel {ctx.ph_target:.2f}.",
                    "",
                    f"Dosiere **{grams:.0f} g {ctx.ph_minus_display}**. Filter 4–6 h, neu messen.",
                    "",
                    "> Hinweis: erst pH grob einstellen, **dann** Dosierung aktivieren.",
                    "",
                ]

    # 3. pH-System
    L += [
        "### ○ 3. pH-Dosierung in Betrieb",
        "- Elektrode in Pufferlösungen **pH 7 + pH 4** kalibrieren",
        f"- Sollwert **{ctx.ph_target:.1f}** setzen",
        "- Dosierung einschalten",
        "",
    ]

    # 4. CYA
    if ctx.cya is None:
        L += ["### ❔ 4. Cyanursäure", "CYA noch nicht gemessen.", ""]
    elif ctx.cya >= ctx.cya_target * 0.9:
        L += [f"### ✅ 4. Cyanursäure", f"CYA **{ctx.cya:.0f} mg/l** (Ziel {ctx.cya_target:.0f}).", ""]
    else:
        pre_g = _cya_predose_g(ctx, shock_target_fc)
        if pre_g <= 0:
            L += [
                "### ✅ 4. Cyanursäure",
                f"CYA **{ctx.cya:.0f} mg/l** — Shock bringt genug nach, keine Vor-Dosierung nötig.",
                "",
            ]
        else:
            L += [
                "### ⚠ 4. Cyanursäure vor-dosieren",
                f"CYA **{ctx.cya:.0f} mg/l** — Ziel {ctx.cya_target:.0f}.",
                "",
                f"Dosiere **ca. {pre_g:.0f} g {ctx.cya_display}** (80 % Sicherheitspuffer).",
                "In Skimmer-Sockel/Socke geben — langsam löslich. Filter 24–48 h.",
                "",
                f"> Der nachfolgende Shock bringt zusätzlich ~{_cya_from_shock(ctx, shock_target_fc):.0f} mg/l CYA mit.",
                "",
            ]

    # 5. Chlor-System
    L += [
        "### ○ 5. Chlor-Dosierung in Betrieb",
        "- Redox-Elektrode mit **468 mV Prüflösung** kalibrieren",
        "- Redox-Sollwert **700 mV**",
        "- Kanister prüfen, Dosierung einschalten",
        "",
    ]

    # 6. Shock
    dose = _shock_dose(ctx, shock_target_fc)
    fc_now = ctx.fc if ctx.fc is not None else 0.0
    if fc_now >= shock_target_fc * 0.8:
        L += [
            f"### ✅ 6. {shock_label}",
            f"FC **{fc_now:.2f} mg/l** — Ziel {shock_target_fc:.0f} bereits erreicht.",
            "",
        ]
    elif dose is not None and dose[0] > 0:
        amount, unit = dose
        extra = ""
        if ctx.shock_type in SHOCK_STABILIZED:
            extra = f"\n⚠ Bringt ~{_cya_from_shock(ctx, shock_target_fc):.0f} mg/l CYA mit."
        brush_line = "\nZusätzlich Wände und Boden bürsten (2–3×)." if include_brush else ""
        L += [
            f"### ⚠ 6. {shock_label}",
            f"FC **{fc_now:.2f} mg/l** — Ziel {shock_target_fc:.0f}.",
            "",
            f"Dosiere **{amount:.0f} {unit} {ctx.shock_display}**. Filter 24 h durchlaufen.{brush_line}{extra}",
            "",
        ]
    else:
        L += [f"### ❔ 6. {shock_label}", "Shock-Produkt nicht konfiguriert.", ""]

    # 7. Badebetrieb-Freigabe
    L += _swim_ready_block(ctx, nr=7)

    return L


def _swim_ready_block(ctx: WorkflowContext, nr: int | None = None) -> list[str]:
    prefix = f"{nr}. " if nr is not None else ""
    if ctx.fc is None:
        return [f"### ❔ {prefix}Badebetrieb-Freigabe", "FC noch nicht gemessen.", ""]
    reasons: list[str] = []
    # Direkte Reizungsfaktoren
    if ctx.fc > 3.0:
        reasons.append(f"FC **{ctx.fc:.2f}** zu hoch (Ziel ≤ 3.0 mg/l) — reizt Augen/Haut")
    if ctx.fc < 0.3:
        reasons.append(f"FC **{ctx.fc:.2f}** zu niedrig (mind. 0.3 mg/l) — keine Desinfektion")
    if ctx.cc is not None and ctx.cc > 0.5:
        reasons.append(f"CC **{ctx.cc:.2f}** zu hoch (Chloramin-Belastung, reizt)")
    ph = _eff_ph(ctx)
    if ph is not None and (ph < 6.8 or ph > 7.8):
        reasons.append(f"pH **{ph:.2f}** außerhalb 6.8–7.8 — reizt Augen/Haut")
    # Indirekte Sicherheit: CYA-Lock
    if ctx.cya is not None and ctx.cya > 100:
        reasons.append(
            f"CYA **{ctx.cya:.0f}** mg/l zu hoch — Chlorine-Lock, Chlor wirkt nicht mehr "
            "richtig (Wassertausch nötig)"
        )
    elif ctx.cya is not None and ctx.cya > 75 and ctx.fc < 2.0:
        reasons.append(
            f"CYA {ctx.cya:.0f} reduziert Chlor-Wirksamkeit — FC {ctx.fc:.2f} "
            "evtl. zu niedrig für sichere Desinfektion"
        )
    if not reasons:
        return [
            f"### ✅ {prefix}Badebetrieb-Freigabe",
            f"FC {ctx.fc:.2f}, CC {_val(ctx.cc, 'mg/l')}, pH {_val(ph, '')}, "
            f"CYA {_val(ctx.cya, 'mg/l', 0)} — alles im sicheren Bereich. Pool nutzbar.",
            "",
        ]
    # FC-Abklingzeit-Schätzung wenn FC das Hauptproblem ist
    extra = ""
    if ctx.fc > 3.0:
        hours = estimate_fc_decay_hours(
            fc_current=ctx.fc,
            fc_target=3.0,
            cya=ctx.cya,
            water_temp_c=ctx.water_temp,
        )
        if hours is not None and hours > 0:
            lo_d = hours * 0.75 / 24
            hi_d = hours * 1.25 / 24
            if hi_d < 1.5:
                range_str = f"{max(1, int(hours * 0.75))}–{max(2, int(hours * 1.25))} h"
            else:
                range_str = f"{lo_d:.1f}–{hi_d:.1f} Tage"
            extra = f"\n⏳ Geschätzt **~{range_str}** bis FC ≤ 3 (Filter an, Abdeckung ab)."
    return [
        f"### ⚠ {prefix}Badebetrieb-Freigabe",
        "Noch nicht badetauglich:",
        *(f"- {r}" for r in reasons),
        f"{extra}",
        "> Aktives Senken nicht nötig — Filter + UV + Zeit reichen.",
        "",
    ]


def render_wasserwechsel(ctx: WorkflowContext, _recs: dict[str, Recommendation]) -> str:
    L = [
        "## Pool-Empfehlung — Wasserwechsel / Inbetriebnahme",
        "",
        "**Voraussetzungen:** Pool befüllt → Filter 2–4 h gelaufen → PoolLab-Messung übertragen.",
        "",
        "---",
        "",
    ]
    L += _inbetriebnahme_list(ctx, SHOCK_TARGET_ROUTINE, "Routine-Shock", include_brush=False)
    return "\n".join(L)


def render_saisonstart(ctx: WorkflowContext, _recs: dict[str, Recommendation]) -> str:
    L = [
        "## Pool-Empfehlung — Saisonstart nach Winter",
        "",
        "**Voraussetzungen:** Abdeckung ab → inspizieren → **gründlich rückspülen** "
        "(1–3 m³ Verlust, TA/CYA checken) → Filter 2–4 h → messen.",
        "",
        "---",
        "",
    ]
    L += _inbetriebnahme_list(ctx, SHOCK_TARGET_ALGEN_LEICHT, "Shock gegen Bio-Last", include_brush=True)
    return "\n".join(L)


# ---------- Schockchlorung: alle Szenarien zum Auswählen ----------


def _shock_scenario_block(ctx: WorkflowContext, target_fc: float, label: str, note: str = "") -> list[str]:
    dose = _shock_dose(ctx, target_fc)
    fc_now = ctx.fc if ctx.fc is not None else 0.0
    if dose is None:
        return [f"### {label}", "Shock-Produkt nicht konfiguriert.", ""]
    amount, unit = dose
    if amount <= 0:
        return [f"### ✅ {label}", f"FC {fc_now:.2f} bereits ≥ {target_fc:.0f}.", ""]
    cya_add = _cya_from_shock(ctx, target_fc)
    cya_note = f" Bringt ~{cya_add:.1f} mg/l CYA mit." if cya_add > 0 else ""
    body = [
        f"### {label}",
        f"Ziel FC {target_fc:.0f} (aktuell {fc_now:.2f}). Dosiere **{amount:.0f} {unit} {ctx.shock_display}**.{cya_note}",
    ]
    if note:
        body.append(note)
    body.append("")
    return body


def render_schockchlorung(ctx: WorkflowContext, _recs: dict[str, Recommendation]) -> str:
    L: list[str] = ["## Pool-Empfehlung — Schockchlorung", ""]

    # Messwert-Zusammenfassung
    ph = _eff_ph(ctx)
    L += [
        "**Messwerte:** "
        f"pH {_val(ph, '')}, FC {_val(ctx.fc, 'mg/l')}, CC {_val(ctx.cc, 'mg/l')}, "
        f"CYA {_val(ctx.cya, 'mg/l', 0)} ({ctx.volume_m3:.0f} m³ Pool)",
        "",
    ]

    # pH-Check
    if ph is None:
        L += ["### ❔ pH-Check", "pH noch nicht gemessen — vor Shock bitte messen.", ""]
    elif ph > 7.4:
        L += [
            "### ⚠ pH zu hoch für effektiven Shock",
            f"pH **{ph:.2f}** — Bei pH > 7.4 sinkt der HOCl-Anteil deutlich "
            "(pH 8.0 nur noch ~22 %). **Erst pH auf 7.0–7.2 senken**, dann schocken.",
            "",
        ]
    else:
        L += ["### ✅ pH-Check", f"pH {ph:.2f} — optimal für HOCl, sofort schocken möglich.", ""]

    L += ["---", "", "### Such dir das passende Szenario:", ""]

    # Breakpoint zuerst, falls CC erhöht
    if ctx.cc is not None and ctx.cc >= 0.5:
        target_bp = max(10.0, ctx.cc * 10.0)
        L += [
            f"### 🚨 Breakpoint *(empfohlen — CC {ctx.cc:.2f} erhöht!)*",
            f"CC {ctx.cc:.2f} → 10× Regel → FC-Ziel **{target_bp:.1f} mg/l**.",
        ]
        dose = _shock_dose(ctx, target_bp)
        if dose and dose[0] > 0:
            amount, unit = dose
            cya_add = _cya_from_shock(ctx, target_bp)
            cya_note = f" Bringt ~{cya_add:.1f} mg/l CYA mit." if cya_add > 0 else ""
            L += [
                "",
                f"Dosiere **{amount:.0f} {unit} {ctx.shock_display}**.{cya_note}",
                "Nach 24 h CC messen — sollte < 0.2 sein.",
                "",
            ]
        else:
            L += ["", "(Produkt nicht konfiguriert oder FC bereits im Ziel)", ""]
    elif ctx.cc is not None:
        L += [f"### ○ Breakpoint", f"CC {ctx.cc:.2f} unauffällig — kein Breakpoint nötig.", ""]

    L += _shock_scenario_block(ctx, SHOCK_TARGET_ROUTINE, "Shock Routine *(präventiv)*")
    L += _shock_scenario_block(
        ctx,
        SHOCK_TARGET_ALGEN_LEICHT,
        "Shock Algen leicht *(grünlicher Schleier)*",
        note="Zusätzlich Wände + Boden bürsten.",
    )
    L += _shock_scenario_block(
        ctx,
        SHOCK_TARGET_ALGEN_STARK,
        "Shock Algen stark *(grüne Brühe)*",
        note="Kräftig bürsten + Filter dauerhaft + ggf. 2. Dosis nach 48 h.",
    )
    L += _shock_scenario_block(
        ctx,
        SHOCK_TARGET_SCHWARZALGEN,
        "Shock Schwarzalgen *(schwarze Punkte)*",
        note="Mechanisch bürsten, ggf. Wochen-Prozess.",
    )

    # Hinweis zu stabilisiertem Chlor
    if ctx.shock_type in SHOCK_STABILIZED:
        L += [
            "---",
            "",
            f"> ⚠ Dein Shock-Produkt **{ctx.shock_display}** ist stabilisiert. "
            "Bei häufigem Shocken steigt CYA. Ab CYA > 75 mg/l Wasser teiltauschen "
            "oder auf Flüssig-Chlor / Cal-Hypo wechseln.",
            "",
        ]

    L += ["---", ""]
    L += _swim_ready_block(ctx)
    return "\n".join(L)


# ---------- Registry ----------


MODE_RENDERERS: dict[str, callable] = {
    MODE_NORMAL: render_normal,
    MODE_WASSERWECHSEL: render_wasserwechsel,
    MODE_SAISONSTART: render_saisonstart,
    MODE_SCHOCKCHLORUNG: render_schockchlorung,
}
