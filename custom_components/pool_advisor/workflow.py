"""Maintenance workflow engine for Pool Chemistry Advisor.

Each workflow is a linear sequence of Steps. The user drives progress
exclusively via the Analyse button:

- `run_analysis()` captures a fresh manual snapshot
- The current step's `satisfied(ctx)` function is evaluated
  - True  → advance one step
  - False → stay; the step's `render()` produces an updated instruction
            (e.g. a remaining dose based on the new measurement)

Each Step may also expose a `summary(ctx)` — a one-line overview of the
step's key values (current vs target). Summaries are shown on ALL steps
(completed + pending + active), so the user sees the whole chemistry
state at a glance.

`min_wait_hours` is a soft hint: a warning is rendered on the active step
only when the user has actually pressed Analyse during the step (i.e.
`analysis_at > step_started_at`) AND the elapsed time is below the
recommendation. Never hard-blocks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .calculator import cya_pre_dose_grams, estimate_fc_decay_hours, shock_dose_grams_or_ml
from .const import (
    MODE_FRISCHWASSER,
    MODE_NORMAL,
    MODE_SAISONSTART,
    MODE_SHOCK_ALGEN_LEICHT,
    MODE_SHOCK_ALGEN_STARK,
    MODE_SHOCK_BREAKPOINT,
    MODE_SHOCK_ROUTINE,
    MODE_SHOCK_SCHWARZALGEN,
    SHOCK_FC_TARGETS,
)


@dataclass
class WorkflowContext:
    volume_m3: float

    ph_minus_display: str
    ph_plus_display: str
    ta_plus_display: str
    routine_cl_display: str
    shock_display: str
    shock_type: str
    shock_strength_pct: float
    cya_display: str
    cya_strength_pct: float

    ph_auto: float | None
    ph_manual: float | None
    ta: float | None
    fc: float | None
    cc: float | None
    cya: float | None

    ph_target: float
    ta_target: float
    fc_target: float
    cya_target: float

    ph_min: float = 7.0
    ph_max: float = 7.4
    ta_min: float = 80.0
    ta_max: float = 120.0
    water_temp: float | None = None

    step_started_at: datetime | None = None
    analysis_at: datetime | None = None
    measured_at: dict[str, datetime | None] = field(default_factory=dict)

    def is_fresh(self, key: str) -> bool:
        if self.step_started_at is None:
            return False
        at = self.measured_at.get(key)
        return at is not None and at > self.step_started_at

    def any_fresh(self) -> bool:
        return any(self.is_fresh(k) for k in self.measured_at)

    def analyzed_during_step(self) -> bool:
        return (
            self.analysis_at is not None
            and self.step_started_at is not None
            and self.analysis_at > self.step_started_at
        )


def _always(_ctx: WorkflowContext) -> bool:
    return True


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    render: Callable[[WorkflowContext], str]
    satisfied: Callable[[WorkflowContext], bool] = _always
    # Short one-line value summary (e.g. "TA 95 mg/l — Ziel 100, Bereich 80–120")
    # Shown on every step regardless of its completion state.
    summary: Callable[[WorkflowContext], str] | None = None
    min_wait_hours: int = 0


# ---------- helpers ----------


def _fmt_val(val: float | None, unit: str, decimals: int = 2) -> str:
    if val is None:
        return "—"
    return f"{val:.{decimals}f} {unit}".rstrip()


def _shock_dose_block(ctx: WorkflowContext, target_fc: float, scenario_label: str) -> str:
    current_fc = ctx.fc if ctx.fc is not None else 0.0
    dose = shock_dose_grams_or_ml(
        current_fc=current_fc,
        target_fc=target_fc,
        volume_m3=ctx.volume_m3,
        shock_type=ctx.shock_type,
        shock_strength_pct=ctx.shock_strength_pct,
    )
    if dose is None:
        return (
            "⚠ Shock-Produkt nicht konfiguriert. "
            "Einstellungen → Chemikalien öffnen."
        )
    amount, unit = dose
    if amount <= 0:
        return f"FC bereits bei **{current_fc:.2f} mg/l** — Ziel {target_fc:.0f} erreicht."
    return (
        f"Dosiere **{amount:.0f} {unit} {ctx.shock_display}**.\n\n"
        f"- In Eimer Poolwasser auflösen, breit verteilen\n"
        f"- Filter **24 h** dauerhaft durchlaufen lassen\n"
        f"- Dann neu messen + **Analyse**"
    )


# ---------- normal ----------


def _normal_body(_ctx: WorkflowContext) -> str:
    return (
        "Normalbetrieb. Nach PoolLab-Messung **Analyse durchführen** drücken."
    )


# ---------- shock step (single self-looping step) ----------


def _shock_render(target_fc: float, scenario_label: str, include_brush: bool = False):
    def render(ctx: WorkflowContext) -> str:
        if ctx.fc is None or not ctx.any_fresh():
            return (
                "Bitte zuerst mit PoolLab messen (FC + CC) und Werte in HA übertragen.\n\n"
                "Dann **Analyse** drücken."
            )
        cc_text = f"{ctx.cc:.2f}" if ctx.cc is not None else "—"
        body = (
            f"**Ziel-FC:** {target_fc:.0f} mg/l — aktuell {ctx.fc:.2f}, CC {cc_text} mg/l.\n\n"
            + _shock_dose_block(ctx, target_fc, scenario_label)
        )
        # Pre-shock pH warning: at high pH, HOCl drops sharply → shock is wasted
        ph_eff = ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto
        if ph_eff is not None and ph_eff > 7.4:
            body += (
                f"\n\n⚠ **pH aktuell {ph_eff:.2f}** — bei pH > 7.4 sinkt der HOCl-Anteil "
                "deutlich (bei pH 8.0 nur noch ~22 %). Erwäge, pH zuerst auf 7.0–7.2 "
                "zu senken — sonst verschwendest du einen großen Teil der Shock-Dosis."
            )

        if include_brush:
            body += "\n\n**Zusätzlich:** Wände und Boden gründlich bürsten (2–3×)."
        from .const import SHOCK_CYA_PER_PPM_CL, SHOCK_STABILIZED

        if ctx.shock_type in SHOCK_STABILIZED:
            increase = max(0.0, target_fc - (ctx.fc or 0.0))
            if increase > 0:
                cya_add = increase * SHOCK_CYA_PER_PPM_CL.get(ctx.shock_type, 0.9)
                cya_after = (ctx.cya or 0.0) + cya_add
                body += (
                    f"\n\n⚠ {ctx.shock_display} bringt ~{cya_add:.0f} mg/l CYA mit. "
                    f"CYA danach ≈ **{cya_after:.0f} mg/l**."
                )
        body += (
            "\n\n_Hinweis: während hoher FC-Werte (>5 mg/l) ist die PoolLab pH-Messung "
            "unzuverlässig (Phenolrot-Reagenz wird gebleicht). Für pH-Kontrolle in den "
            "nächsten 1–2 Tagen auf die Bayrol-Elektrode verlassen._"
        )
        return body

    return render


def _shock_satisfied(target_fc: float):
    def check(ctx: WorkflowContext) -> bool:
        if ctx.fc is None or not ctx.is_fresh("fc"):
            return False
        fc_ok = ctx.fc >= target_fc * 0.8
        cc_ok = ctx.cc is None or ctx.cc <= 0.2
        return fc_ok and cc_ok

    return check


def _shock_summary(target_fc: float):
    def summary(ctx: WorkflowContext) -> str:
        fc = _fmt_val(ctx.fc, "mg/l")
        cc = _fmt_val(ctx.cc, "mg/l")
        return f"FC {fc} / CC {cc} — Ziel FC ≥ {target_fc:.0f}, CC ≤ 0.2"

    return summary


# ---------- breakpoint ----------


def _breakpoint_render(ctx: WorkflowContext) -> str:
    if ctx.cc is None or not ctx.any_fresh():
        return "Bitte erst CC messen. Dann Analyse drücken."
    target_fc = max(10.0, ctx.cc * 10.0)
    body = (
        f"CC **{ctx.cc:.2f} mg/l** → FC-Ziel **{target_fc:.1f} mg/l** (10× Regel).\n\n"
    )
    body += _shock_dose_block(ctx, target_fc, "Breakpoint")
    return body


def _breakpoint_satisfied(ctx: WorkflowContext) -> bool:
    return ctx.cc is not None and ctx.is_fresh("cc") and ctx.cc <= 0.2


def _breakpoint_summary(ctx: WorkflowContext) -> str:
    fc = _fmt_val(ctx.fc, "mg/l")
    cc = _fmt_val(ctx.cc, "mg/l")
    return f"FC {fc} / CC {cc} — Ziel CC ≤ 0.2"


# ---------- Swim-ready check (Badebetrieb-Freigabe) ----------

SWIM_FC_MAX: float = 3.0
SWIM_CC_MAX: float = 0.2
SWIM_PH_MIN: float = 7.0
SWIM_PH_MAX: float = 7.6


def _swim_ready_render(ctx: WorkflowContext) -> str:
    ph = ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto
    if ctx.fc is None or not ctx.any_fresh():
        return (
            "Warte bis FC abgebaut ist. Filter durchgehend laufen lassen, Abdeckung weg "
            "(UV beschleunigt den FC-Abbau). Regelmäßig messen und **Analyse** drücken."
        )
    reasons: list[str] = []
    if ctx.fc > SWIM_FC_MAX:
        reasons.append(f"FC **{ctx.fc:.2f} mg/l** noch zu hoch (Ziel ≤ {SWIM_FC_MAX:.1f})")
    if ctx.cc is not None and ctx.cc > SWIM_CC_MAX:
        reasons.append(f"CC **{ctx.cc:.2f} mg/l** noch zu hoch (Ziel ≤ {SWIM_CC_MAX:.1f})")
    if ph is not None and (ph < SWIM_PH_MIN or ph > SWIM_PH_MAX):
        reasons.append(
            f"pH **{ph:.2f}** außerhalb Badebetrieb {SWIM_PH_MIN:.1f}–{SWIM_PH_MAX:.1f}"
        )
    if not reasons:
        cc_str = f"{ctx.cc:.2f}" if ctx.cc is not None else "—"
        ph_str = f"{ph:.2f}" if ph is not None else "—"
        return (
            "### ✅ Badebetrieb freigegeben\n\n"
            f"FC {ctx.fc:.2f} mg/l, CC {cc_str} mg/l, pH {ph_str}.\n\n"
            "Pool ist sicher benutzbar. Analyse drücken → zurück auf Normalbetrieb."
        )
    body = "**Noch nicht badetauglich:**\n\n"
    for r in reasons:
        body += f"- {r}\n"

    # Näherungsweise Abklingzeit-Schätzung (nur wenn FC das Hauptproblem ist)
    if ctx.fc is not None and ctx.fc > SWIM_FC_MAX:
        hours = estimate_fc_decay_hours(
            fc_current=ctx.fc,
            fc_target=SWIM_FC_MAX,
            cya=ctx.cya,
            water_temp_c=ctx.water_temp,
        )
        if hours is not None and hours > 0:
            # Range ±25 % wegen Unsicherheit (UV, Bio-Last, Deckelstatus)
            lo_d = hours * 0.75 / 24
            hi_d = hours * 1.25 / 24
            if hi_d < 1.5:
                range_str = f"{max(1, int(hours * 0.75))}–{max(2, int(hours * 1.25))} h"
            else:
                range_str = f"{lo_d:.1f}–{hi_d:.1f} Tage"
            cya_str = f"CYA {ctx.cya:.0f}" if ctx.cya is not None else "CYA ~30"
            temp_str = f"{ctx.water_temp:.0f} °C" if ctx.water_temp is not None else "25 °C"
            body += (
                f"\n**⏳ Geschätzte Zeit bis FC ≤ {SWIM_FC_MAX:.1f}: ~{range_str}** "
                f"(bei {cya_str}, {temp_str} Wassertemp, Abdeckung ab + Sonne).\n"
                "→ Abdeckung zu verdoppelt die Zeit ungefähr."
            )

    body += (
        "\n\n**Aktives Senken nicht nötig — Zeit + Filter + UV reichen:**\n"
        "- Filterpumpe dauerhaft an\n"
        "- Abdeckung weg solange FC hoch (UV-Abbau)\n"
        "- Täglich messen\n"
        "- Notfall bei extremer Überdosierung: Natriumthiosulfat (\"Chlor-Neutralisator\") — "
        "für Privatpools selten nötig"
    )
    return body


def _swim_ready_satisfied(ctx: WorkflowContext) -> bool:
    if ctx.fc is None or not ctx.is_fresh("fc"):
        return False
    if ctx.fc > SWIM_FC_MAX:
        return False
    if ctx.cc is not None and ctx.cc > SWIM_CC_MAX:
        return False
    ph = ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto
    if ph is not None and (ph < SWIM_PH_MIN or ph > SWIM_PH_MAX):
        return False
    return True


def _swim_ready_summary(ctx: WorkflowContext) -> str:
    fc = _fmt_val(ctx.fc, "mg/l")
    return f"FC {fc} → Ziel ≤ {SWIM_FC_MAX:.1f} mg/l für Badebetrieb"


# ---------- Frischwasser steps ----------


def _fw_ta_render(ctx: WorkflowContext) -> str:
    if ctx.ta is None or not ctx.any_fresh():
        return (
            "**Voraussetzungen:**\n\n"
            "- Pool befüllt (bei Neuanlage) bzw. Abdeckung ab und sichtlich inspiziert (Saisonstart)\n"
            "- **Gründliches Rückspülen** des Filters — bei Saisonstart gehen dabei 1–3 m³ "
            "  altes Wasser raus, TA und CYA können dadurch merklich sinken\n"
            "- Filter **2–4 h dauerhaft** gelaufen (Mischung + CO₂-Ausgasung)\n"
            "- PoolLab-Messung: alle 5 Parameter (pH, TA, FC, CC, CYA)\n\n"
            "Werte in HA übertragen, dann **Analyse** drücken."
        )
    delta = ctx.ta_target - ctx.ta
    if ctx.ta_min <= ctx.ta <= ctx.ta_max:
        return f"**Bereits im Zielbereich.** Analyse drücken für den nächsten Schritt."
    if delta > 0:
        from .calculator import G_BICARB_PURE_PER_M3_PER_10_TA

        pure_g = G_BICARB_PURE_PER_M3_PER_10_TA * ctx.volume_m3 * (delta / 10.0)
        return (
            f"Anhebung um **{delta:.0f} mg/l** nötig.\n\n"
            f"Dosiere **{pure_g:.0f} g {ctx.ta_plus_display}**.\n\n"
            f"- In Eimer auflösen, verteilen\n"
            f"- Filter **12–24 h** durchlaufen lassen\n"
            f"- Neu messen + Analyse"
        )
    return (
        "TA senken ist ein mehrtägiger Prozess (pH gezielt senken + belüften + wiederholen). "
        "Keine einmalige Gramm-Empfehlung möglich."
    )


def _fw_ta_satisfied(ctx: WorkflowContext) -> bool:
    return (
        ctx.ta is not None
        and ctx.is_fresh("ta")
        and ctx.ta_min <= ctx.ta <= ctx.ta_max
    )


def _fw_ta_summary(ctx: WorkflowContext) -> str:
    cur = _fmt_val(ctx.ta, "mg/l", 0)
    return f"TA {cur} — Ziel **{ctx.ta_target:.0f}**, Bereich {ctx.ta_min:.0f}–{ctx.ta_max:.0f}"


def _fw_ph_render(ctx: WorkflowContext) -> str:
    ph = ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto
    if ph is None or not ctx.any_fresh():
        return "Bitte pH messen und Analyse drücken."
    if ctx.ph_min <= ph <= ctx.ph_max:
        return "**Bereits im Zielbereich.** Analyse drücken für den nächsten Schritt."
    from .calculator import (
        G_DRY_ACID_PURE_PER_M3_PER_01_PH,
        G_SODA_PURE_PER_M3_PER_01_PH,
        ML_HCL_33_PER_M3_PER_01_PH,
    )

    delta = ctx.ph_target - ph
    units = abs(delta) / 0.1
    if delta > 0:
        grams = G_SODA_PURE_PER_M3_PER_01_PH * ctx.volume_m3 * units
        return (
            f"Anhebung von {ph:.2f} → **{ctx.ph_target:.2f}**.\n\n"
            f"Dosiere **{grams:.0f} g {ctx.ph_plus_display}**.\n\n"
            f"- Filter **4–6 h** durchlaufen lassen\n"
            f"- Neu messen + Analyse"
        )
    grams = G_DRY_ACID_PURE_PER_M3_PER_01_PH * ctx.volume_m3 * units
    ml = ML_HCL_33_PER_M3_PER_01_PH * ctx.volume_m3 * units
    return (
        f"Senkung von {ph:.2f} → **{ctx.ph_target:.2f}**.\n\n"
        f"Dosiere **{grams:.0f} g {ctx.ph_minus_display}** (oder ca. {ml:.0f} ml Salzsäure).\n\n"
        f"- Filter **4–6 h** durchlaufen lassen\n"
        f"- Neu messen + Analyse"
    )


def _fw_ph_satisfied(ctx: WorkflowContext) -> bool:
    ph = ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto
    return (
        ph is not None
        and ctx.is_fresh("ph_manual")
        and ctx.ph_min <= ph <= ctx.ph_max
    )


def _fw_ph_summary(ctx: WorkflowContext) -> str:
    ph = ctx.ph_manual if ctx.ph_manual is not None else ctx.ph_auto
    cur = _fmt_val(ph, "")
    return f"pH {cur} — Ziel **{ctx.ph_target:.2f}**, Bereich {ctx.ph_min:.1f}–{ctx.ph_max:.1f}"


def _fw_ph_system_render(ctx: WorkflowContext) -> str:
    return (
        "**pH-Dosieranlage in Betrieb nehmen:**\n\n"
        "1. pH-Elektrode in **Pufferlösung pH 7** → an der Anlage kalibrieren\n"
        "2. In **Pufferlösung pH 4** → Zweipunkt-Kalibrierung abschließen\n"
        "3. Elektrode zurück ins Probenwasser\n"
        f"4. **pH-Sollwert auf {ctx.ph_target:.1f}** setzen\n"
        "5. pH-Dosierung **einschalten**\n\n"
        "Anlage übernimmt ab jetzt die Feinregelung. **Analyse** für weiter."
    )


def _fw_ph_system_summary(ctx: WorkflowContext) -> str:
    return f"Elektrode kalibrieren + Sollwert {ctx.ph_target:.2f} + Dosierung an"


def _fw_cya_render(ctx: WorkflowContext) -> str:
    cur = ctx.cya if ctx.cya is not None else 0.0
    if ctx.cya is not None and cur >= ctx.cya_target * 0.9:
        return "**Bereits im Zielbereich.** Analyse für weiter."
    if ctx.cya is None or not ctx.any_fresh():
        return "Bitte CYA messen und Analyse drücken."
    shock_target_fc = SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE]
    shock_increase = max(0.0, shock_target_fc - (ctx.fc or 0.0))
    pre_dose_g = cya_pre_dose_grams(
        current_cya=cur,
        target_cya=ctx.cya_target,
        shock_fc_increase=shock_increase,
        shock_type=ctx.shock_type,
        volume_m3=ctx.volume_m3,
        cya_strength_pct=ctx.cya_strength_pct,
    )
    if pre_dose_g <= 0:
        return (
            f"Aktuell **{cur:.0f} mg/l**. Der nachfolgende Routine-Shock bringt "
            "genug CYA mit — nichts vor-zu-dosieren. **Analyse** für weiter."
        )
    return (
        f"Aktuell **{cur:.0f} mg/l**, Ziel **{ctx.cya_target:.0f}**.\n\n"
        f"Dosiere **ca. {pre_dose_g * 0.8:.0f} g {ctx.cya_display}** (80 % Sicherheit).\n\n"
        "- In Skimmer-Sockel (Nylonsocke) oder Einsatzkorb geben — löst langsam\n"
        "- Filter **24–48 h** durchlaufen lassen bis vollständig gelöst\n"
        "- Dann messen + Analyse\n\n"
        f"_Hinweis: der folgende Shock bringt zusätzlich ~{shock_increase * 0.9:.0f} mg/l CYA mit._"
    )


def _fw_cya_satisfied(ctx: WorkflowContext) -> bool:
    return ctx.cya is not None and ctx.is_fresh("cya") and ctx.cya >= ctx.cya_target * 0.6


def _fw_cya_summary(ctx: WorkflowContext) -> str:
    cur = _fmt_val(ctx.cya, "mg/l", 0)
    return f"CYA {cur} — Ziel **{ctx.cya_target:.0f}** mg/l"


def _fw_cl_system_render(_ctx: WorkflowContext) -> str:
    return (
        "**Chlor-Dosieranlage in Betrieb nehmen:**\n\n"
        "1. **Redox-Elektrode** in Prüflösung 468 mV → kalibrieren\n"
        "2. Elektrode zurück ins Probenwasser\n"
        "3. **Chlor-Kanister** prüfen (voll? Haltbarkeit?)\n"
        "4. **Redox-Sollwert 700 mV** setzen\n"
        "5. Chlor-Dosierung **einschalten**\n\n"
        "Dosierung pausiert noch, bis FC abbaut. **Analyse** für weiter."
    )


def _fw_cl_system_summary(_ctx: WorkflowContext) -> str:
    return "Elektrode kalibrieren + Redox-Sollwert 700 mV + Dosierung an"


def _fw_shock_render(ctx: WorkflowContext) -> str:
    return _shock_render(SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE], "Routine-Shock")(ctx)


def _fw_shock_summary(ctx: WorkflowContext) -> str:
    fc = _fmt_val(ctx.fc, "mg/l")
    return f"FC {fc} — Shock-Ziel {SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE]:.0f} mg/l"


_fw_shock_satisfied = _shock_satisfied(SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE])


# ---------- workflow definitions ----------


def _shock_single_step(target_fc: float, scenario_label: str, include_brush: bool = False) -> list[Step]:
    return [
        Step(
            f"shock_{scenario_label.lower().replace(' ', '_')}",
            f"{scenario_label} — Dosieren & Nachmessen",
            _shock_render(target_fc, scenario_label, include_brush),
            satisfied=_shock_satisfied(target_fc),
            summary=_shock_summary(target_fc),
            min_wait_hours=24,
        ),
        Step(
            "swim_ready",
            "Badebetrieb-Freigabe",
            _swim_ready_render,
            satisfied=_swim_ready_satisfied,
            summary=_swim_ready_summary,
        ),
    ]


def _inbetriebnahme_steps(shock_target_fc: float, shock_label: str, include_brush: bool = False) -> list[Step]:
    """Shared workflow for Frischwasser und Saisonstart.

    Unterschied nur im Shock-Ziel (Frischwasser: Routine 10 mg/l, Saisonstart:
    Algen-leicht 15 mg/l) und dem Label. Alle anderen Schritte sind identisch
    — Steps die schon im Zielbereich liegen, advancen einfach durch.
    """
    return [
        Step("ta", "TA anpassen", _fw_ta_render, satisfied=_fw_ta_satisfied, summary=_fw_ta_summary, min_wait_hours=12),
        Step("ph", "pH grob", _fw_ph_render, satisfied=_fw_ph_satisfied, summary=_fw_ph_summary, min_wait_hours=4),
        Step("ph_system", "pH-Dosierung in Betrieb", _fw_ph_system_render, summary=_fw_ph_system_summary),
        Step("cya", "CYA vor-dosieren", _fw_cya_render, satisfied=_fw_cya_satisfied, summary=_fw_cya_summary, min_wait_hours=24),
        Step("cl_system", "Chlor-Dosierung in Betrieb", _fw_cl_system_render, summary=_fw_cl_system_summary),
        Step(
            "shock",
            shock_label,
            _shock_render(shock_target_fc, shock_label, include_brush=include_brush),
            satisfied=_shock_satisfied(shock_target_fc),
            summary=_shock_summary(shock_target_fc),
            min_wait_hours=24,
        ),
        Step(
            "swim_ready",
            "Badebetrieb-Freigabe",
            _swim_ready_render,
            satisfied=_swim_ready_satisfied,
            summary=_swim_ready_summary,
        ),
    ]


WORKFLOWS: dict[str, list[Step]] = {
    MODE_NORMAL: [Step("normal", "Normalbetrieb", _normal_body)],
    MODE_SHOCK_ROUTINE: _shock_single_step(
        SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE], "Shock Routine"
    ),
    MODE_SHOCK_ALGEN_LEICHT: _shock_single_step(
        SHOCK_FC_TARGETS[MODE_SHOCK_ALGEN_LEICHT], "Shock Algen leicht", include_brush=True
    ),
    MODE_SHOCK_ALGEN_STARK: _shock_single_step(
        SHOCK_FC_TARGETS[MODE_SHOCK_ALGEN_STARK], "Shock Algen stark", include_brush=True
    ),
    MODE_SHOCK_SCHWARZALGEN: _shock_single_step(
        SHOCK_FC_TARGETS[MODE_SHOCK_SCHWARZALGEN], "Shock Schwarzalgen", include_brush=True
    ),
    MODE_SHOCK_BREAKPOINT: [
        Step(
            "breakpoint",
            "Breakpoint — Dosieren & Nachmessen",
            _breakpoint_render,
            satisfied=_breakpoint_satisfied,
            summary=_breakpoint_summary,
            min_wait_hours=24,
        ),
        Step(
            "swim_ready",
            "Badebetrieb-Freigabe",
            _swim_ready_render,
            satisfied=_swim_ready_satisfied,
            summary=_swim_ready_summary,
        ),
    ],
    MODE_FRISCHWASSER: _inbetriebnahme_steps(
        SHOCK_FC_TARGETS[MODE_SHOCK_ROUTINE], "Routine-Shock"
    ),
    MODE_SAISONSTART: _inbetriebnahme_steps(
        SHOCK_FC_TARGETS[MODE_SHOCK_ALGEN_LEICHT], "Saisonstart-Shock", include_brush=True
    ),
}


def get_workflow(mode: str) -> list[Step]:
    return WORKFLOWS.get(mode, WORKFLOWS[MODE_NORMAL])


def step_count(mode: str) -> int:
    return len(get_workflow(mode))
