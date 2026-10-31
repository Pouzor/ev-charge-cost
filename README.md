# EV Charge Cost

Intégration Home Assistant (HACS) qui détecte automatiquement les recharges
d'un véhicule électrique à partir d'une prise ou pince ampèremétrique
monitorée, et enregistre pour chaque session la **durée**, l'**énergie (kWh)**
et le **coût (€)** — avec un prix fixe ou issu d'une entité, y compris quand le
prix change pendant la charge (heures creuses / pleines).

> 🚧 En développement — voir [FEATURE.md](FEATURE.md) pour le périmètre.

## Installation (HACS)

1. HACS → menu ⋮ → *Dépôts personnalisés* → `https://github.com/Pouzor/ev-charge-cost`, catégorie *Intégration*.
2. Installer **EV Charge Cost**, redémarrer Home Assistant.
3. Paramètres → Appareils et services → *Ajouter une intégration* → **EV Charge Cost**.

## Configuration

- **Capteur de puissance** (W/kW) — obligatoire, sert à détecter la charge.
- **Compteur d'énergie** (kWh cumulés) — optionnel, plus précis que l'intégration de la puissance.
- **Détection** — seuil (200 W par défaut), délais de démarrage / d'arrêt, énergie minimale.
- **Prix** — fixe (€/kWh) ou entité (€/kWh, c€/kWh, €/MWh).

## Événements

`ev_charge_cost_charge_started`, `ev_charge_cost_charge_ended` (durée, énergie,
coût, tranches tarifaires) et `ev_charge_cost_charge_discarded`.

## Développement

```bash
uv venv -p 3.14 .venv && uv pip install -p .venv/bin/python -r requirements_test.txt
.venv/bin/pytest -q
./scripts/dev-ha.sh   # HA de test dans Docker sur http://localhost:8125
```
