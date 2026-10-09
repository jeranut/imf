# -*- coding: utf-8 -*-
"""Assistant de purge des fonds de crédit rotatif (microfinance.fond.credit).

Contexte : audit docs_dev/fond_credit/AUDIT_suppression_fonds.md (module
microfinance_loan_management). Quatre relations sont en ondelete='restrict' vers
microfinance.fond.credit (microfinance.fond.contribution.fond_id,
microfinance.fond.allocation.fond_id, microfinance.fond.partage.fond_id,
microfinance.portfolio.allocation.fond_id) : un unlink() direct échoue systématiquement en
base tant qu'une seule ligne fille existe. Ce wizard supprime donc explicitement ces lignes
filles avant le fonds lui-même (choix validé : purge en cascade, pas un simple archivage) —
les account.move déjà postés référencés par ces contributions ne sont JAMAIS touchés (leur
champ microfinance_fond_contribution_id passe seulement à NULL, ondelete='set null' natif).

Ordre de traitement par fonds : crédits non décaissés (selon blocking_loan_action) ->
contributions -> répartitions de portefeuille (microfinance.portfolio.allocation, annulées
d'abord si validées pour restituer amount_allocated aux portefeuilles ; leurs lignes partent
en cascade ORM/SQL) -> partages -> allocations d'agence résiduelles -> fonds. Les
répartitions de portefeuille passent AVANT les partages/allocations d'agence, dont elles
dépendent (reste_a_repartir_portefeuille). Dépendants en SET NULL, gérés par la base :
res_company.microfinance_fond_credit_default_id, microfinance.loan.fond_credit_id (traité
explicitement ci-dessous), microfinance.portfolio.allocation.line.fond_id.
"""
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MicrofinanceFondCreditPurgeWizard(models.TransientModel):
    _name = 'microfinance.fond.credit.purge.wizard'
    _description = 'Purge des fonds de crédit rotatif (microfinance.fond.credit)'

    # Clé dédiée à ce wizard : différente de MicrofinanceDataResetWizard._LOCK_KEY
    # (823476513) et de celle du RAZ générique EAT/MIIA (823476512) — même cluster
    # Postgres partagé, cf. commentaire sur ces deux constantes.
    _LOCK_KEY = 823476514

    APPLY_PARAM = 'microfinance.fond_credit_purge_apply'

    @api.model
    def _get_microfinance_company_ids(self):
        # Même heuristique que MicrofinanceDataResetWizard._get_microfinance_company_ids
        # (agency_code obligatoire pour toute société CEFOR) : périmètre explicite,
        # jamais un domaine vide. EAT/MIIA n'ont aucune société dans cette base (cf.
        # audit §4) — cette borne les exclurait de toute façon si c'était le cas.
        return self.env['res.company'].sudo().search([('agency_code', '!=', False)]).ids

    company_ids = fields.Many2many(
        'res.company', string='Agences ciblées', required=True,
        domain=lambda self: [('id', 'in', self._get_microfinance_company_ids())],
        help="Fonds visés : ceux dont company_id est dans cette liste (fonds « Agence "
             "unique »), plus tous les fonds « Multi-agences » dont TOUTES les allocations "
             "(s'il y en a) tombent dans cette liste. Un fonds « Multi-agences » ayant une "
             "allocation vers une société hors de cette liste est systématiquement exclu "
             "(jamais de purge partielle d'un fonds partagé).",
    )

    blocking_loan_action = fields.Selection([
        ('stop', "Arrêter et lister (défaut — aucun crédit touché)"),
        ('unlink_reference', "Délier la référence (fond_credit_id = False) sur les crédits non décaissés"),
        ('delete_test_loan', "Supprimer le crédit non décaissé (jeu de test uniquement)"),
    ], string='Crédits non décaissés référençant un fonds ciblé', default='stop', required=True,
        help="Un crédit DÉJÀ DÉCAISSÉ (disbursement_date renseigné) bloque TOUJOURS le fonds "
             "correspondant, quel que soit ce choix : jamais touché par ce wizard (risque "
             "comptable — cf. _check_fond_credit_id_locked_after_disbursement). Ce choix ne "
             "s'applique qu'aux crédits non décaissés.")

    i_confirm = fields.Boolean(
        string="Je confirme avoir fait un backup complet de la base et je "
               "veux supprimer définitivement ces fonds",
    )
    confirm_text = fields.Char(string='Tapez "SUPPRIMER" pour confirmer')

    is_dry_run = fields.Boolean(readonly=True)
    log = fields.Text(string='Journal', readonly=True)
    has_error = fields.Boolean(compute='_compute_has_error')

    @api.depends('log')
    def _compute_has_error(self):
        for rec in self:
            rec.has_error = bool(rec.log and 'ERREUR' in rec.log)

    # ------------------------------------------------------------------
    def _trace(self, lines, message):
        ts = datetime.now().strftime('%H:%M:%S')
        lines.append(f"[{ts}] {message}")

    def _acquire_lock_or_raise(self):
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", (self._LOCK_KEY,))
        if not self.env.cr.fetchone()[0]:
            raise UserError(_(
                "Une autre purge de fonds de crédit est déjà en cours. Patientez qu'elle "
                "se termine avant de réessayer."
            ))

    def _check_companies_in_scope(self):
        self.ensure_one()
        allowed_ids = set(self._get_microfinance_company_ids())
        out_of_scope = self.company_ids.filtered(lambda c: c.id not in allowed_ids)
        if out_of_scope:
            raise UserError(_(
                "Les sociétés suivantes n'ont pas de code agence (agency_code) et ne "
                "peuvent pas être ciblées par cette purge : %s"
            ) % ', '.join(out_of_scope.mapped('name')))

    # ------------------------------------------------------------------
    def action_preview(self):
        """Aperçu en lecture seule (aucune donnée modifiée)."""
        self.ensure_one()
        if not self.company_ids:
            raise UserError(_("Sélectionnez au moins une agence."))
        self._check_companies_in_scope()
        lines = []
        for fond, blockers in self._scan_funds():
            lines.append(self._describe_fund(fond, blockers))
        self.log = "APERÇU (aucune donnée modifiée) :\n\n" + ("\n".join(lines) if lines else "Aucun fonds dans le périmètre.")
        return self._reopen()

    def action_run_dry_run(self):
        self.ensure_one()
        return self._run(dry_run=True)

    def action_run_execute(self):
        self.ensure_one()
        if not self.i_confirm:
            raise UserError(_(
                "Vous devez cocher la case de confirmation (backup effectué) avant de "
                "lancer l'exécution réelle."
            ))
        if (self.confirm_text or '').strip().upper() != 'SUPPRIMER':
            raise UserError(_('Retapez exactement "SUPPRIMER" pour confirmer.'))
        # Double verrou volontaire : la case à cocher ci-dessus est par exécution
        # (n'importe quel manager microfinance peut la cocher), ce paramètre système est
        # un interrupteur global que seul un administrateur technique peut activer
        # (ir.config_parameter, group_system) — cf. demande initiale ("DRY-RUN par défaut
        # (paramètre système microfinance.fond_credit_purge_apply = False)").
        apply_param = self.env['ir.config_parameter'].sudo().get_param(self.APPLY_PARAM)
        if apply_param != 'True':
            raise UserError(_(
                "L'exécution réelle est désactivée par le paramètre système « %s » "
                "(actuellement absent ou différent de \"True\"). Un administrateur "
                "technique doit l'activer explicitement (Réglages > Technique > "
                "Paramètres système) avant toute exécution réelle."
            ) % self.APPLY_PARAM)
        return self._run(dry_run=False)

    # ------------------------------------------------------------------
    def _scan_funds(self):
        """Fonds dans le périmètre + leurs éventuels blocages (crédits décaissés,
        allocation hors périmètre). with_context(active_test=False) : inclut les fonds
        déjà archivés (active=False), qu'on doit pouvoir purger aussi."""
        self.ensure_one()
        cids = self.company_ids.ids
        Fond = self.env['microfinance.fond.credit'].sudo().with_context(active_test=False)
        # Domaine explicite, jamais vide (cids est garanti non vide par action_preview/_run).
        candidates = Fond.search([
            '|', ('company_id', 'in', cids), ('scope', '=', 'multi_company'),
        ])
        result = []
        for fond in candidates:
            blockers = []
            if fond.scope == 'multi_company':
                allocation_companies = fond.allocation_ids.mapped('company_id')
                out_of_scope = allocation_companies.filtered(lambda c: c.id not in cids)
                if out_of_scope:
                    blockers.append(_(
                        "fonds « Multi-agences » alloué à une société hors périmètre (%s) — exclu"
                    ) % ', '.join(out_of_scope.mapped('name')))
                    result.append((fond, blockers))
                    continue
            loans = fond.loan_ids
            disbursed = loans.filtered('disbursement_date')
            if disbursed:
                blockers.append(_(
                    "%d crédit(s) déjà décaissé(s) rattaché(s) (%s) — jamais touché par ce wizard"
                ) % (len(disbursed), ', '.join(disbursed.mapped('name'))))
            other_loans = loans - disbursed
            if other_loans and self.blocking_loan_action == 'stop':
                blockers.append(_(
                    "%d crédit(s) non décaissé(s) rattaché(s) (%s) — action « %s »"
                ) % (len(other_loans), ', '.join(other_loans.mapped('name')), _("Arrêter et lister")))
            result.append((fond, blockers))
        return result

    def _fund_counts(self, fond):
        """Nombre d'enregistrements liés au fonds, par modèle (lecture seule). Même
        périmètre que _purge : ce qui sera supprimé (contributions, répartitions de
        portefeuille + leurs lignes, partages, allocations d'agence) ou délié (crédits non
        décaissés selon l'action choisie, sociétés dont le fonds est le défaut)."""
        self.ensure_one()
        env = self.env
        domain = [('fond_id', '=', fond.id)]
        alloc_pf = env['microfinance.portfolio.allocation'].sudo().with_context(active_test=False)
        loans = fond.loan_ids
        return {
            'contribution': env['microfinance.fond.contribution'].sudo().search_count(domain),
            'portfolio_allocation': alloc_pf.search_count(domain),
            'portfolio_allocation_validated': alloc_pf.search_count(domain + [('state', '=', 'validated')]),
            'portfolio_allocation_line': env['microfinance.portfolio.allocation.line'].sudo().search_count(
                [('allocation_id.fond_id', '=', fond.id)]),
            'partage': env['microfinance.fond.partage'].sudo().search_count(domain),
            'allocation': env['microfinance.fond.allocation'].sudo().search_count(domain),
            'loan_not_disbursed': len(loans.filtered(lambda l: not l.disbursement_date)),
            'company_default': env['res.company'].sudo().search_count(
                [('microfinance_fond_credit_default_id', '=', fond.id)]),
        }

    def _format_counts(self, counts):
        action = self.blocking_loan_action
        loan_effect = {
            'stop': _('bloquant'), 'unlink_reference': _('déliés'), 'delete_test_loan': _('supprimés'),
        }[action]
        return (
            "%(c)d contribution(s), %(pa)d répartition(s) de portefeuille (dont %(pav)d validée(s) "
            "à annuler) avec %(pal)d ligne(s), %(p)d partage(s), %(a)d allocation(s) d'agence ; "
            "crédits non décaissés : %(l)d (%(le)s) ; sociétés au fonds par défaut (remis à vide) : %(cd)d"
        ) % {
            'c': counts['contribution'], 'pa': counts['portfolio_allocation'],
            'pav': counts['portfolio_allocation_validated'], 'pal': counts['portfolio_allocation_line'],
            'p': counts['partage'], 'a': counts['allocation'],
            'l': counts['loan_not_disbursed'], 'le': loan_effect, 'cd': counts['company_default'],
        }

    def _describe_fund(self, fond, blockers):
        company_label = fond.company_id.name if fond.company_id else _('Multi-agences')
        line = _(
            "[%(id)d] %(code)s « %(name)s » (%(company)s, %(scope)s%(active)s) : %(counts)s"
        ) % {
            'id': fond.id, 'code': fond.code, 'name': fond.name, 'company': company_label,
            'scope': fond.scope, 'active': '' if fond.active else ', ARCHIVÉ',
            'counts': self._format_counts(self._fund_counts(fond)),
        }
        if blockers:
            line += "\n    BLOQUÉ : " + " ; ".join(blockers)
        else:
            line += "\n    -> supprimable"
        return line

    # ------------------------------------------------------------------
    def _run(self, dry_run):
        self.ensure_one()
        if not self.company_ids:
            raise UserError(_("Sélectionnez au moins une agence."))
        self._check_companies_in_scope()
        self._acquire_lock_or_raise()

        cr = self.env.cr
        lines = []
        self._trace(lines, "MODE SIMULATION (dry-run)" if dry_run else "MODE EXÉCUTION RÉELLE")
        sp = cr.savepoint() if dry_run else None
        # Toute l'opération dans une seule transaction : un savepoint en dry-run (annulé
        # à la fin, quoi qu'il arrive), un vrai commit unique en exécution réelle — pas de
        # commit par lot ici (volumes attendus faibles, quelques fonds), contrairement à
        # MicrofinanceDataResetWizard._batch_unlink() qui traite des milliers de lignes.
        try:
            summary = self._purge(lines)
            if dry_run:
                sp.rollback()
                cr.rollback()
                self._trace(lines, "SIMULATION TERMINÉE (rollback, rien de modifié)")
            else:
                cr.commit()
                self._trace(lines, "EXÉCUTION TERMINÉE (modifications validées)")
            self._trace(lines, "Résumé : " + ", ".join(
                f"{company_name} : {n} fonds supprimé(s)" for company_name, n in summary.items()
            ) if summary else "Résumé : aucun fonds supprimé.")
        except Exception as e:
            if dry_run and sp:
                sp.rollback()
            cr.rollback()
            self._trace(lines, f"ERREUR : {type(e).__name__}: {e}")
            self._trace(lines, "Rollback effectué — aucune donnée modifiée.")

        self.write({'is_dry_run': dry_run, 'log': "\n".join(lines)})
        return self._reopen()

    def _purge(self, lines):
        """Cœur de la purge, exécuté dans la transaction en cours (jamais de commit ici
        — géré par _run). Retourne {nom_société_ou_'Multi-agences': nb_fonds_supprimés}."""
        summary = {}
        # sudo() ciblé (pas self.sudo() global) : uniquement sur les modèles métier
        # traversés (fonds/contributions/allocations/partages/crédits), qui vivent sur
        # plusieurs sociétés à la fois — nécessaire pour dépasser les ir.rule société par
        # société depuis un wizard qui agit délibérément multi-agences, mais rien d'autre
        # n'est élevé en sudo (jamais un sudo() sur self ou sur le wizard lui-même).
        # with_context(microfinance_skip_parent_check=True) : ce wizard est déjà réservé à
        # group_microfinance_manager (accès ir.model.access) et agit délibérément à travers
        # toutes les agences — la garde « société mère uniquement » de _check_parent_only()
        # (contributions/partages) n'a pas de sens ici, elle suppose une saisie utilisateur
        # depuis la société courante. Idem pour ALLOCATION_TECHNICAL_CONTEXT
        # (microfinance.fond.allocation._check_technical_context) : seule voie légitime pour
        # supprimer une allocation hors du flux normal « Partage des fonds ».
        Contribution = self.env['microfinance.fond.contribution'].sudo().with_context(
            microfinance_skip_parent_check=True)
        Allocation = self.env['microfinance.fond.allocation'].sudo().with_context(
            microfinance_skip_parent_check=True, fond_partage_technique=True)
        Partage = self.env['microfinance.fond.partage'].sudo().with_context(
            microfinance_skip_parent_check=True)
        # active_test=False : une répartition n'a pas de champ active aujourd'hui, mais ne
        # jamais laisser un filtre implicite masquer un dépendant RESTRICT.
        PortfolioAllocation = self.env['microfinance.portfolio.allocation'].sudo().with_context(
            active_test=False)

        for fond, blockers in self._scan_funds():
            fond = fond.sudo()
            company_label = fond.company_id.name if fond.company_id else _('Multi-agences')
            if blockers:
                self._trace(lines, f"[{fond.id}] {fond.code} « {fond.name} » ignoré : " + " ; ".join(blockers))
                continue

            # Détail par modèle AVANT toute suppression (visible aussi en dry-run).
            self._trace(lines, f"[{fond.id}] {fond.code} « {fond.name} » à traiter : "
                        + self._format_counts(self._fund_counts(fond)))

            other_loans = fond.loan_ids.filtered(lambda l: not l.disbursement_date)
            if other_loans and self.blocking_loan_action == 'unlink_reference':
                other_loans.write({'fond_credit_id': False})
                self._trace(lines, f"[{fond.id}] {fond.code} : {len(other_loans)} crédit(s) déliés (fond_credit_id = False)")
            elif other_loans and self.blocking_loan_action == 'delete_test_loan':
                for loan in other_loans:
                    # Garde-fou : même choisi explicitement, on ne supprime jamais un
                    # crédit qui a des lignes filles en ondelete='restrict' ailleurs dans
                    # le module (microfinance.loan.payment, microfinance.transfert.
                    # remboursement — cf. AUDIT du 14/09 dans microfinance_data_reset_
                    # wizard) : un crédit 'enquete'/'approved' n'en a normalement aucune,
                    # mais on vérifie plutôt que de laisser une IntegrityError remonter en
                    # cours de purge et faire échouer tout le fonds sans message clair.
                    blocking = []
                    if loan.payment_ids:
                        blocking.append(_('remboursements existants'))
                    if 'microfinance.transfert.remboursement' in self.env and self.env['microfinance.transfert.remboursement'].sudo().search_count([('loan_id', '=', loan.id)]):
                        blocking.append(_('transferts inter-agences existants'))
                    if blocking:
                        self._trace(lines, f"    crédit {loan.name} NON supprimé ({', '.join(blocking)}) — fonds ignoré")
                        blockers.append(_('crédit %s non supprimable') % loan.name)
                        break
                if blockers:
                    self._trace(lines, f"[{fond.id}] {fond.code} « {fond.name} » ignoré : " + " ; ".join(blockers))
                    continue
                loan_names = other_loans.mapped('name')
                other_loans.unlink()
                self._trace(lines, f"[{fond.id}] {fond.code} : {len(loan_names)} crédit(s) de test supprimé(s) ({', '.join(loan_names)})")

            n_contrib = Contribution.search_count([('fond_id', '=', fond.id)])
            if n_contrib:
                Contribution.search([('fond_id', '=', fond.id)]).unlink()
                self._trace(lines, f"[{fond.id}] {fond.code} : {n_contrib} contribution(s) supprimée(s) (account.move déjà postés conservés, juste déliés)")

            # Répartitions agence -> portefeuilles (FK RESTRICT sur le fonds). Une répartition
            # 'validated' ne peut pas être supprimée telle quelle (unlink() la refuse) : on
            # l'annule d'abord via action_cancel(), qui retire sa part de amount_allocated des
            # portefeuilles (et bloque si un portefeuille a déjà utilisé sa part : le fonds est
            # alors légitimement non purgeable, l'erreur remonte et tout est annulé). Les
            # lignes partent en ondelete='cascade'. À traiter avant les partages/allocations
            # d'agence : elles en dépendent (reste_a_repartir_portefeuille).
            repartitions = PortfolioAllocation.search([('fond_id', '=', fond.id)])
            if repartitions:
                n_rep, n_lines = len(repartitions), len(repartitions.line_ids)
                rep_cancel = repartitions.filtered(lambda r: r.state == 'validated')
                if rep_cancel:
                    rep_cancel.action_cancel()
                repartitions.unlink()
                self._trace(lines, f"[{fond.id}] {fond.code} : {n_rep} répartition(s) de portefeuille supprimée(s) "
                            f"({n_lines} ligne(s), {len(rep_cancel)} annulée(s) au préalable)")

            # Un partage 'validated' ne peut pas être supprimé tel quel (fond_partage.unlink()
            # le refuse explicitement) : il faut d'abord l'annuler via action_cancel(), qui
            # réduit/supprime lui-même proprement les allocations correspondantes (et bloque si
            # une agence a déjà utilisé sa part — montant_utilise > 0 —, auquel cas ce fonds est
            # légitimement bloqué, pas de contournement ici). L'annulation traite donc les
            # partages ET la plupart des allocations ; le nettoyage Allocation ci-dessous n'est
            # qu'un filet de sécurité pour un reliquat improbable (arrondi, partages multiples).
            partages = Partage.search([('fond_id', '=', fond.id)])
            n_partage = len(partages)
            to_cancel = partages.filtered(lambda p: p.state == 'validated')
            if to_cancel:
                to_cancel.action_cancel()
            if partages:
                partages.unlink()
                self._trace(lines, f"[{fond.id}] {fond.code} : {n_partage} partage(s) supprimé(s) ({len(to_cancel)} annulé(s) au préalable)")

            n_alloc = Allocation.search_count([('fond_id', '=', fond.id)])
            if n_alloc:
                Allocation.search([('fond_id', '=', fond.id)]).unlink()
                self._trace(lines, f"[{fond.id}] {fond.code} : {n_alloc} allocation(s) restante(s) supprimée(s) (reliquat après annulation des partages)")

            fond_id, fond_code, fond_name = fond.id, fond.code, fond.name
            fond.with_context(microfinance_skip_parent_check=True).unlink()
            self._trace(lines, f"[{fond_id}] {fond_code} « {fond_name} » ({company_label}) : fonds supprimé")
            summary[company_label] = summary.get(company_label, 0) + 1

        return summary

    # ------------------------------------------------------------------
    def action_reset_wizard(self):
        self.ensure_one()
        self.write({'is_dry_run': False, 'log': False, 'i_confirm': False, 'confirm_text': False})
        return self._reopen()

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'microfinance.fond.credit.purge.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
