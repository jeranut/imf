# Statut dev — transfert_client
Dernière inspection : 2026-09-18

**Statut : À faire.** Chantier volontairement non implémenté : seul le blocage inter-agences
(`docs_dev/blocage_client_inter_agence/STATUS.md`) est livré, son message d'erreur renvoie déjà
vers ce transfert.

Besoin : un client dont le crédit est soldé peut demander le transfert de son compte vers une
autre agence (CEFOR, ~25 agences = autant de `res.company`).

Dépendance : chantier de blocage inter-agences (`docs_dev/blocage_client_inter_agence/`) — un client
avec un crédit en cours dans une autre agence ne peut être ni créé ni obtenir de crédit ; il doit
d'abord solder son crédit, puis demander le transfert.

## À faire / incomplet
- [ ] Implémenter le transfert de compte client entre agences (demande, validation, exécution) — `microfinance_loan_management/models/res_partner.py` — impact: moyen
- [ ] Question ouverte : sort de l'épargne et des comptes (`is_container`) au transfert — impact: moyen
- [ ] Question ouverte : comptabilité inter-agences, journal TRANS « Transit inter-agences » — impact: moyen
- [ ] Question ouverte : transfert du partenaire (changement de `company_id`) ou création d'un nouveau partenaire lié — impact: moyen
- [ ] Question ouverte : historique et scoring conservés ou non après transfert — impact: moyen
- [ ] Question ouverte : qui valide le transfert (les deux agences ?) — impact: moyen
- [ ] Question ouverte : impact sur la portée d'unicité du CIN (`_check_cin_unique`, `microfinance_loan_management/models/res_partner.py`, dont la recherche n'est pas en `sudo()` et ne voit donc que les agences accessibles à l'utilisateur) — impact: moyen
