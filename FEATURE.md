# EV Charge Cost — Spécification fonctionnelle

Intégration Home Assistant (distribuée via HACS) qui détecte automatiquement les
sessions de recharge d'un véhicule électrique branché sur une prise/ligne
monitorée, et enregistre pour chaque session : **durée**, **énergie (kWh)** et
**coût (€)**.

## 1. Contexte / matériel de référence

Installation de référence : pince Tuya **PJ-1203A** (« Bidirectional energy meter
with 80A current clamp ») via Zigbee2MQTT, device `Pinces consommation`.

| Rôle | Entité | Unité | Notes |
|---|---|---|---|
| Puissance voiture | `sensor.pinces_consommation_power_b` | W | `measurement`, rafraîchi toutes les 10 s |
| Énergie voiture (compteur) | `sensor.pinces_consommation_energy_b` | kWh | `total_increasing` |

Profil observé : charge ~3,7 kW (16 A mono), puissance à 0 W hors charge.

L'intégration doit rester **générique** : tout capteur de puissance (W/kW) et,
en option, tout capteur d'énergie cumulée (Wh/kWh) doit fonctionner (prise
Shelly, Tuya, Zigbee, etc.).

## 2. Configuration (Config Flow UI, pas de YAML)

Une entrée de configuration = un point de charge. Plusieurs instances possibles.

### Étape 1 — Source
| Champ | Type | Obligatoire | Défaut |
|---|---|---|---|
| Nom | texte | oui | `Recharge VE` |
| Capteur de puissance | entity selector (`sensor`, device_class `power`) | oui | — |
| Capteur d'énergie cumulée | entity selector (`sensor`, device_class `energy`) | non | — |

### Étape 2 — Détection
| Champ | Type | Défaut |
|---|---|---|
| Seuil de démarrage (W) | nombre | 200 |
| Délai avant démarrage (s) — puissance > seuil pendant | nombre | 30 |
| Délai avant arrêt (s) — puissance < seuil pendant | nombre | 120 |
| Énergie minimale pour conserver une session (kWh) | nombre | 0.1 |

Les délais évitent les faux départs (pic bref) et les fausses fins (pauses de la
voiture en fin de charge / équilibrage batterie).

### Étape 3 — Tarif
Mode au choix :
- **Fixe** : prix en €/kWh (nombre, ex. `0.2516`).
- **Entité** : entity selector vers un `sensor` / `input_number` donnant le prix
  du kWh. Unités acceptées : `€/kWh`, `EUR/kWh`, `c€/kWh`, `€/MWh` (conversion
  automatique) ; sans unité → interprété comme €/kWh.

Toutes les options sont modifiables ensuite via l'**Options Flow** sans
supprimer l'intégration.

## 3. Détection d'une session (machine à états)

```
IDLE ──(P > seuil)──▶ PENDING_START ──(P > seuil pendant délai_start)──▶ CHARGING
  ▲                        │ (P ≤ seuil)                                   │
  │                        ▼                                               │ (P ≤ seuil)
  └──────────────────── IDLE                                               ▼
  ▲                                                                  PENDING_STOP
  │                                                                        │
  └──(P ≤ seuil pendant délai_stop)── finalisation ◀───────────────────────┘
                                                      (P > seuil → retour CHARGING)
```

- L'instant de début enregistré est le **premier** passage au-dessus du seuil
  (pas la fin du délai de confirmation) ; l'énergie consommée pendant
  `PENDING_START` est incluse.
- L'instant de fin enregistré est le **dernier** passage sous le seuil.
- Les délais sont évalués avec des timers (`async_call_later`), pas uniquement
  à la réception d'un nouvel état (le capteur peut ne pas republier une valeur
  identique).
- États `unavailable` / `unknown` du capteur de puissance : ignorés (ni départ
  ni arrêt). Si indisponible plus longtemps que `délai_stop`, la session reste
  ouverte et reprend au retour du capteur.
- Une session dont l'énergie < énergie minimale est écartée (pas d'event
  `ended`, pas de mise à jour de « dernière session » ni des totaux), mais un
  event `ev_charge_cost_charge_discarded` est émis.

## 4. Calcul de l'énergie

1. **Si un capteur d'énergie cumulée est configuré (prioritaire)** : à chaque
   changement d'état, `delta = valeur - valeur_précédente` (converti en kWh).
   - `delta < 0` (remise à zéro du compteur) → on prend `valeur` comme delta
     (comportement `total_increasing`).
   - Valeurs `unavailable`/`unknown` ignorées ; on garde la dernière valeur
     valide comme référence.
2. **Sinon** : intégration de la puissance par somme de Riemann **à gauche**
   (la dernière valeur est maintenue jusqu'à la mesure suivante). HA n'émet pas
   de changement d'état quand la valeur est identique : le tracker appelle donc
   aussi l'intégration périodiquement (tick ~60 s) pour ne pas sous-compter une
   puissance stable. Pendant une indisponibilité du capteur, rien n'est
   intégré.

## 5. Calcul du coût — prise en compte des changements de prix

Le coût n'est **jamais** calculé comme `énergie_totale × prix_final`. Il est
**accumulé par tranche** :

```
coût_session += delta_kWh × prix_kWh_en_vigueur_au_moment_du_delta
```

- Le prix en vigueur est la dernière valeur valide de l'entité prix (écoutée en
  continu via `async_track_state_change_event`).
- Quand le prix change pendant une session, on **clôture la tranche courante**
  (on lit/integre l'énergie jusqu'à cet instant au prix précédent) avant
  d'appliquer le nouveau prix. Exemple : passage HC → HP à 22h00 pendant une
  charge.
- Si l'entité prix est indisponible : on utilise le dernier prix connu et on
  marque la session `price_estimated: true`.
- La session conserve la liste des tranches tarifaires
  (`[{from, to, price, kwh, cost}]`) pour l'audit.

## 6. Entités exposées (par point de charge)

| Entité | Type | Description |
|---|---|---|
| `binary_sensor.<nom>_charging` | binary_sensor (`battery_charging`) | `on` pendant une session (état `CHARGING`/`PENDING_STOP`) |
| `sensor.<nom>_session_energy` | kWh, `total` | Énergie de la session en cours (0 hors session) |
| `sensor.<nom>_session_cost` | €, `total` | Coût de la session en cours |
| `sensor.<nom>_session_duration` | durée (min) | Durée de la session en cours |
| `sensor.<nom>_last_session_energy` | kWh | Énergie de la dernière session terminée |
| `sensor.<nom>_last_session_cost` | € | Coût de la dernière session terminée — attributs : start, end, durée, prix moyen, tranches |
| `sensor.<nom>_last_session_duration` | durée (min) | Durée de la dernière session |
| `sensor.<nom>_total_energy` | kWh, `total_increasing` | Cumul de toutes les sessions (utilisable dans le tableau Énergie) |
| `sensor.<nom>_total_cost` | €, `total_increasing` | Cumul des coûts |
| `sensor.<nom>_session_count` | compteur | Nombre de sessions retenues |
| `sensor.<nom>_current_price` | €/kWh | Prix utilisé actuellement (fixe ou entité) |

Toutes les entités sont rattachées à un device « EV Charge Cost – <nom> ».

## 7. Événements (bus HA)

Utilisables dans des automatisations (trigger `event`).

### `ev_charge_cost_charge_started`
```yaml
entry_id: "…"
name: "Recharge VE"
start: "2026-10-30T21:43:10+01:00"
power_entity: sensor.pinces_consommation_power_b
```

### `ev_charge_cost_charge_ended`
```yaml
entry_id: "…"
name: "Recharge VE"
start: "2026-10-30T21:43:10+01:00"
end: "2026-10-31T04:12:40+01:00"
duration_s: 23370
energy_kwh: 22.84
cost: 4.19
currency: EUR
avg_price: 0.1835
price_estimated: false
tranches:
  - {from: "2026-10-30T21:43:10+01:00", to: "2026-10-30T22:00:00+01:00", price: 0.2516, kwh: 1.05, cost: 0.26}
  - {from: "2026-10-30T22:00:00+01:00", to: "2026-10-31T04:12:40+01:00", price: 0.1802, kwh: 21.79, cost: 3.93}
```

### `ev_charge_cost_charge_discarded`
Mêmes champs que `ended`, émis quand l'énergie < minimum.

Les événements sont aussi décrits pour le **logbook** (`logbook.py`) afin
d'apparaître dans le journal HA.

## 8. Persistance / robustesse

- La session en cours (état machine, start, énergie, coût, tranches, dernière
  valeur compteur, dernier prix) est sauvegardée via `homeassistant.helpers.storage.Store`
  (`.storage/ev_charge_cost.<entry_id>`) à chaque tranche et périodiquement.
- Au redémarrage de HA : restauration de la session ; si la puissance est
  toujours > seuil → reprise ; sinon → passage en `PENDING_STOP` puis
  finalisation normale. Avec capteur d'énergie, l'énergie consommée pendant
  l'arrêt de HA est récupérée via le delta du compteur.
- Totaux et dernière session restaurés (Store), pas seulement via
  `RestoreEntity`.

## 9. Services

| Service | Description |
|---|---|
| `ev_charge_cost.stop_session` | Force la fin de la session en cours (finalisation + event `ended`) |
| `ev_charge_cost.reset_totals` | Remet à zéro totaux et compteur de sessions |

## 10. Packaging HACS

- `hacs.json` à la racine, `custom_components/ev_charge_cost/` avec
  `manifest.json` (`config_flow: true`, `iot_class: calculated`, `version`).
- Traductions `fr` et `en`.
- CI GitHub Actions : `hassfest` + `hacs/action` (validation) + tests pytest.
- README avec installation HACS (dépôt personnalisé), captures, exemple
  d'automatisation (notification en fin de charge avec le coût).

## 11. Hors périmètre (v1)

- Historique détaillé de toutes les sessions consultable dans l'UI (au-delà de
  la dernière session et des events/logbook) — envisageable en v2 (fichier
  Store ou entité `calendar`/`todo`).
- Pilotage de la charge (on/off de la prise, charge en heures creuses).
- Identification de plusieurs véhicules sur la même prise.

## 12. Critères d'acceptation

- [ ] Une charge réelle de ~3,7 kW sur `power_b` crée une session, la clôture
      après le délai d'arrêt et émet `charge_started` / `charge_ended`.
- [ ] Un pic < délai de démarrage ne crée pas de session.
- [ ] Une pause < délai d'arrêt ne coupe pas la session.
- [ ] Avec compteur d'énergie, `energy_kwh` de la session = écart du compteur
      entre début et fin (± 0,01 kWh).
- [ ] Un changement de prix en cours de session produit 2 tranches et le coût
      = somme des tranches.
- [ ] Un redémarrage de HA en pleine charge ne perd ni la session ni l'énergie.
- [ ] Mode prix fixe et mode prix entité fonctionnent, modifiables via Options.
- [ ] Validation `hassfest` et HACS OK ; tests unitaires verts.
