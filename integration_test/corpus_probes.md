# Corpus probes — planted inferences & insights

Ground truth for the extended Helios Robotics fixture. None of these are answerable by copying a
single sentence: each requires connecting facts across documents (inference) or synthesizing across
many (insight). Use them to build inference-style `ask` eval cases (L4) and insight fixtures (L5).

The four deliberate **conflicts** stay unresolved by design and must remain so: Series B $40M (board)
vs $45M (press); Atlas Q2 (board) vs Q3 (roadmap/engineering); Dana Okafor CTO (board) vs VP
Engineering (wiki); Vertex Dynamics competitor (board/sales) vs partner (offsite). The new docs
reference these without picking a side.

## New entities added (graph density)

- **Nadia Rahman** — leads the Atlas gripper firmware team; reports to Leo Zhang. (org_chart, supply_chain_review)
- **Tomas Berg** — leads Project Beacon out of Berlin; reports to Dana Okafor. (org_chart)
- **Meridian Robotics** — sole-source actuator supplier for the Atlas gripper; rumored Vertex supplier. (supply_chain_review, competitive_intel)
- **Rosa Méndez** — VP Operations at Acme Logistics; contract signatory. (customer_contract_summary)
- **Elena Sokolova** — founder of Quanta Labs; built its perception stack. (quanta_diligence_brief)
- **Greta Holm** — Northwind Capital partner; Helios board member. (quanta_diligence_brief, board_prep_notes — personal)

New relationship shapes: REPORTS_TO chains, SUPPLIES (sole-source), FOUNDED, board representation,
customer signatory.

## Multi-hop inference probes (answer not stated in any single doc)

| #  | Question | Docs to connect | Expected answer |
|----|----------|-----------------|-----------------|
| I1 | Who does Nadia Rahman ultimately report to? | org_chart (Nadia → Leo; Leo → Dana) | Dana Okafor, via Leo Zhang. |
| I2 | Who leads the team behind the biggest remaining Atlas risk? | engineering_update / supply_chain_review (risk = gripper firmware) + org_chart (Nadia leads gripper firmware) | Nadia Rahman. |
| I3 | Does Helios share a supplier with a competitor? | supply_chain_review (Meridian → Atlas) + competitive_intel (Meridian → Vertex) | Yes — Meridian Robotics supplies both Helios (Atlas gripper) and Vertex Dynamics. |
| I4 | If the Quanta acquisition closes, whose technology strengthens Beacon first? | quanta_diligence_brief (Elena Sokolova built Quanta perception) + product_roadmap / engineering_update (Quanta folds into Beacon first) | Elena Sokolova's perception technology. |
| I5 | Which board member represents Helios's largest investor? | quanta_diligence_brief (Greta Holm = Northwind partner on board) + board_meeting / press_release (Northwind led the Series B) | Greta Holm (Northwind Capital). |
| I6 | What single unresolved decision blocks the Acme expansion? | customer_contract_summary (expansion gated on Atlas shipping by end-Q3) + the Q2/Q3 date conflict | Resolving the Atlas ship date. |

## Synthesizable insights (for L5 — derived docs + reasoning subgraph)

- **S1 — The Atlas date is a systemic single point of failure.** The unresolved Q2/Q3 ship date gates
  the Acme expansion clause, Northwind's confidence, Sam's sales credibility, and Beacon's GA at once.
  Sources: board_meeting, product_roadmap, engineering_update, sales_update, customer_contract_summary,
  investor_thoughts (personal), board_prep_notes (personal).
- **S2 — Leo Zhang is a key-person (bus-factor) risk.** Leo runs Atlas, owns the platform, leads the
  gripper-firmware team via Nadia, and is the Quanta technical evaluator; losing him breaks three
  things at once. Sources: candid_team_assessment, org_chart, supply_chain_review,
  acquisition_notes_quanta, 1on1_priya, succession_planning (personal).
- **S3 — The Quanta acquisition is double-edged.** Meant to accelerate Beacon, it could endanger the
  Atlas launch by splitting Leo's focus, worrying Dana, and forcing a Berlin-expansion delay.
  Sources: strategy_offsite, quanta_diligence_brief, acquisition_notes_quanta, 1on1_priya, 1on1_dana,
  board_prep_notes (personal).
- **S4 — The Vertex relationship is three-way.** Vertex Dynamics is at once a competitor, a potential
  safety-standards partner, and a supply-chain sibling (shared supplier Meridian Robotics) — which
  complicates any move for or against them. Sources: board_meeting, strategy_offsite, sales_update,
  competitive_intel, supply_chain_review.
