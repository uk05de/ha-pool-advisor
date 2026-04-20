# Pool Chemistry Advisor

Home Assistant custom integration that turns your pool water-chemistry readings
into concrete, split-dose handling recommendations — e.g.
*"Erhöhen: 2× 170 g Natron (NaHCO₃), dazwischen 6 h warten"*.

Works with any HA sensor that exposes numeric readings for pH, alkalinity,
free/combined/total chlorine, redox, temperature, cyanuric acid — no matter
whether the values come from a PoolLab cloud integration, a Bayrol dosing
controller, a photometer, or just manual `input_number` helpers.

## Features

- Recommendations for **pH**, **total alkalinity**, and **chlorine / shock**
- Each dose is automatically split (configurable max-single-dose + wait time)
  so you re-measure before over-correcting
- **Overall pool status** sensor + **Attention needed** binary sensor for
  automations & notifications
- Fully configurable: pool volume, chlorination type, target ranges, product
  types + strengths
- No API keys, no cloud — all calculations are local

## Installation

### HACS (recommended)

1. Add this repo as a custom repository in HACS → *Integrations*
   (category *Integration*): `https://github.com/uk05de/ha-pool-advisor`
2. Install **Pool Chemistry Advisor**, restart Home Assistant.
3. *Settings → Devices & Services → Add Integration* → **Pool Chemistry Advisor**.

### Manual

Copy `custom_components/pool_advisor/` to your HA `config/custom_components/`
folder, then restart Home Assistant.

## Configuration

The config flow walks you through five steps:

1. **Pool** — name, water volume (m³), salt electrolysis or classic
2. **Entities** — pick the HA sensors that hold each reading (all optional)
3. **Targets** — min/target/max for every parameter. Defaults match common
   guidelines (pH 7.0–7.4, TA 80–120 mg/l, free Cl 0.3–0.8 mg/l for salt pools)
4. **Chemicals** — product type + active strength (%) for pH−, pH+, TA+, shock
5. **Dosing** — max fraction per dose + hours between split doses

Everything is editable afterwards via *Configure* on the integration card.

## Entities created

| Entity | Type | Purpose |
|---|---|---|
| `sensor.<name>_empfehlung_ph` | sensor | Text summary of pH correction |
| `sensor.<name>_empfehlung_alkalitat` | sensor | TA correction |
| `sensor.<name>_empfehlung_chlor` | sensor | Free-Cl or shock dose |
| `sensor.<name>_pool_status` | sensor | `OK` / `Anpassung nötig` / `Shock empfohlen` |
| `binary_sensor.<name>_aufmerksamkeit_notig` | binary | On if any parameter out of range |

Each recommendation sensor exposes full detail as attributes:
`action`, `reason`, `delta`, `note`, and a `steps` list with
`{amount, unit, product, wait_hours}` per step.

## Formulas & safety notes

Formulas are conservative rules of thumb from standard pool-chemistry
references. They assume good water circulation and do not account for edge
cases like very high cyanuric-acid levels or extreme calcium hardness.

**Lowering alkalinity** is intentionally not given as a gram number — the
process is iterative (lower pH, aerate, re-measure) and can't be reduced to
a single dose. The advisor returns a guidance note instead.

**Salt-electrolysis pools**: manual chlorine dosing is only recommended for
shock corrections — for normal free-Cl control the advisor refers you to the
Bayrol production-rate / redox-setpoint.

**Always re-measure after each dose.** The split-dosing defaults (50% per
application, 6 h between) exist exactly for this reason.

## Example dashboard card

```yaml
type: entities
title: Pool
entities:
  - entity: sensor.pool_pool_status
  - entity: binary_sensor.pool_aufmerksamkeit_notig
  - entity: sensor.pool_empfehlung_ph
  - entity: sensor.pool_empfehlung_alkalitat
  - entity: sensor.pool_empfehlung_chlor
```

## License

MIT
