# -*- coding: utf-8 -*-
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MicrofinanceDataResetWizard(models.TransientModel):
    _name = 'microfinance.data.reset.wizard'
    _description = "Assistant de remise à zéro des données transactionnelles microfinance"
    # Clé dédiée, différente de data.reset.wizard._LOCK_KEY (823476512) : les deux
    # wizards tournent sur des bases Postgres distinctes (MOWGLI vs EATDATA/...) mais
    # partagent le même cluster, or pg_try_advisory_xact_lock est une clé GLOBALE au
    # cluster, pas à la base. Réutiliser la même clé bloquerait deux RAZ qui ne
    # touchent jamais les mêmes données, sans aucun conflit réel.
    _LOCK_KEY = 823476513
    _BATCH_SIZE = 100
    _TRACE_MAX_LINES = 30

    @api.model
    def _get_microfinance_company_ids(self):
        # agency_code est obligatoire (NOT NULL + validation) pour toute société de
        # cette instance dès que microfinance_loan_management est installé
        # (res_company.py : create()/write() lèvent une ValidationError sinon).
        # Aujourd'hui, la base ne contient d'ailleurs que des agences CEFOR (11),
        # aucune société EAT/MIIA n'y existe. Domaine volontairement simple plutôt
        # que l'heuristique "a un produit de crédit" : plus direct, et le champ
        # agency_code est le marqueur explicite d'agence CEFOR sur res.company.
        return self.env['res.company'].sudo().search([('agency_code', '!=', False)]).ids

    company_ids = fields.Many2many(
        'res.company',
        string="Agences à nettoyer",
        required=True,
        domain=lambda self: [('id', 'in', self._get_microfinance_company_ids())],
        help="Seules les agences ayant un code agence (agency_code) apparaissent ici. "
             "Une société sans code agence n'est jamais proposée.",
    )

    # --- Périmètre : chaque bloc peut être désactivé indépendamment ---
    do_collection_visits = fields.Boolean(
        string="Visites de recouvrement (microfinance.collection.visit)", default=True,
        help="loan_id est en ondelete='cascade' : disparaissent automatiquement avec le "
             "crédit. Traitées d'abord, explicitement, uniquement pour un journal clair.",
    )
    do_loan_guarantees = fields.Boolean(
        string="Garanties de crédit (microfinance.loan.guarantee)", default=True,
        help="loan_id est en ondelete='cascade'. Les profils/règles de valorisation des "
             "garanties (configuration) ne sont jamais touchés.",
    )
    do_scoring_lines = fields.Boolean(
        string="Lignes de scoring appliquées (microfinance.scoring.line)", default=True,
        help="Détail de scoring par crédit (loan_id en ondelete='cascade'). Les profils et "
             "règles de scoring (configuration) ne sont jamais touchés.",
    )
    do_reschedule_history = fields.Boolean(
        string="Historique de rééchelonnement (microfinance.loan.reschedule.history)",
        default=True,
        help="loan_id en ondelete='cascade' ; les lignes d'ancien échéancier associées "
             "disparaissent avec l'historique (history_id en ondelete='cascade').",
    )
    do_loan_payments = fields.Boolean(
        string="Remboursements crédit (microfinance.loan.payment)", default=True,
        help="loan_id est en ondelete='restrict' : doivent être supprimés avant le crédit "
             "lui-même, quel que soit leur état (aucune surcharge unlink() ne bloque un "
             "paiement posté, contrairement à hr.expense dans le RAZ générique).",
    )
    do_loan_installments = fields.Boolean(
        string="Échéanciers (microfinance.loan.installment)", default=True,
        help="loan_id est en ondelete='cascade'. Traitées explicitement pour le journal.",
    )
    do_loans = fields.Boolean(
        string="Crédits (microfinance.loan)", default=True,
        help="Aucune surcharge unlink() ne bloque un crédit selon son état : la seule "
             "contrainte réelle est l'ordre (paiements supprimés avant, cf. ondelete "
             "restrict). Les écritures de décaissement/frais/radiation sont traitées par "
             "le bloc comptable ci-dessous, pas ici.",
    )
    do_savings_transactions = fields.Boolean(
        string="Transactions d'épargne (microfinance.savings.transaction)", default=True,
        help="account_id est en ondelete='restrict' : doivent être supprimées avant le "
             "compte épargne.",
    )
    do_savings_accounts = fields.Boolean(
        string="Comptes d'épargne (microfinance.savings.account)", default=True,
    )
    do_accounting_entries = fields.Boolean(
        string="Écritures comptables liées (account.move)", default=True,
        help="Ne supprime que les account.move de la société ayant l'un des champs "
             "microfinance_loan_id, microfinance_payment_id, "
             "microfinance_savings_account_id ou microfinance_savings_transaction_id "
             "renseigné, plus les écritures de contre-passation (reversal_move_id) des "
             "remboursements annulés — ces dernières perdent le tag microfinance_* lors "
             "de la contre-passation (copy=False) et ne seraient sinon jamais détectées. "
             "Les écritures manuelles hors microfinance ne sont jamais touchées, même "
             "dans une agence sélectionnée. Si un journal est en mode sécurisé "
             "(restrict_mode_hash_table), Odoo refusera lui-même de repasser en "
             "brouillon une écriture postée : l'opération s'arrêtera avec une erreur "
             "claire plutôt que de contourner la sécurité comptable.",
    )

    i_confirm = fields.Boolean(
        string="Je confirme avoir fait un backup complet de la base et je "
               "veux supprimer définitivement ces données",
    )
    confirm_text = fields.Char(
        string='Tapez "SUPPRIMER" pour confirmer',
        help="Sécurité supplémentaire vu la sensibilité des données financières "
             "(contexte réglementé CSBF, décaissements réels en jeu).",
    )

    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('running', 'En cours'),
        ('done', 'Terminé'),
    ], default='draft', readonly=True)

    is_dry_run = fields.Boolean(readonly=True)

    # --- Suivi de progression ---
    total_steps = fields.Integer(readonly=True, default=0)
    step_index = fields.Integer(readonly=True, default=0)
    pending_company_ids = fields.Many2many(
        'res.company', 'microfinance_data_reset_wizard_pending_rel',
        string="Agences restantes", readonly=True,
    )
    current_label = fields.Char(readonly=True, string="Étape en cours")
    batch_progress = fields.Char(
        readonly=True, string="Avancement du lot en cours",
        help="Détail fin de la progression par lots de _BATCH_SIZE au sein "
             "de l'étape courante (ex: '350 / 652 remboursements traités').",
    )
    progress = fields.Float(compute='_compute_progress', store=True, string="Progression (%)")
    live_trace = fields.Text(
        readonly=True, string="Trace en direct",
        help="Dernières lignes horodatées de l'opération en cours, "
             "mises à jour et committées à chaque petite action pour donner "
             "une visibilité fine (contrairement au journal final).",
    )

    log = fields.Text(string="Journal", readonly=True)

    @api.depends('total_steps', 'step_index')
    def _compute_progress(self):
        for rec in self:
            rec.progress = (rec.step_index / rec.total_steps * 100.0) if rec.total_steps else 0.0

    # ------------------------------------------------------------------
    # Verrou anti-concurrence : empêche deux RAZ de tourner en même temps
    # ------------------------------------------------------------------
    def _acquire_lock_or_raise(self):
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", (self._LOCK_KEY,))
        acquired = self.env.cr.fetchone()[0]
        if not acquired:
            raise UserError(_(
                "Une autre opération de RAZ microfinance est déjà en cours (dans cet "
                "onglet ou un autre). Patientez qu'elle se termine ou fermez les autres "
                "onglets avant de réessayer."
            ))

    # ------------------------------------------------------------------
    # Garde-fou serveur : même si l'UI restreint le domaine, un contournement (write
    # direct, import) sur company_ids ne doit jamais pouvoir lancer une exécution sur
    # une société hors périmètre microfinance.
    # ------------------------------------------------------------------
    def _check_companies_in_scope(self):
        self.ensure_one()
        allowed_ids = set(self._get_microfinance_company_ids())
        out_of_scope = self.company_ids.filtered(lambda c: c.id not in allowed_ids)
        if out_of_scope:
            raise UserError(_(
                "Les sociétés suivantes n'ont pas de code agence (agency_code) et ne "
                "peuvent pas être traitées par ce RAZ microfinance : %s"
            ) % ', '.join(out_of_scope.mapped('name')))

    # ------------------------------------------------------------------
    def _trace(self, message):
        ts = datetime.now().strftime('%H:%M:%S')
        line = f"[{ts}] {message}"
        if self.is_dry_run:
            self.log = (self.log or '') + "\n" + line
            return
        lines = [l for l in (self.live_trace or '').split('\n') if l]
        lines.append(line)
        self.live_trace = '\n'.join(lines[-self._TRACE_MAX_LINES:])
        self.env.cr.commit()

    # ------------------------------------------------------------------
    # Aperçu des volumes avant toute action (lecture seule)
    # ------------------------------------------------------------------
    def action_preview_counts(self):
        self.ensure_one()
        if not self.company_ids:
            raise UserError(_("Sélectionnez au moins une agence."))
        self._check_companies_in_scope()

        lines = []
        Move = self.env['account.move'].sudo()
        for company in self.company_ids:
            cid = company.id
            n_visits = self.env['microfinance.collection.visit'].sudo().search_count([('company_id', '=', cid)])
            n_guarantees = self.env['microfinance.loan.guarantee'].sudo().search_count([('company_id', '=', cid)])
            n_scoring = self.env['microfinance.scoring.line'].sudo().search_count([('company_id', '=', cid)])
            n_reschedule = self.env['microfinance.loan.reschedule.history'].sudo().search_count([('company_id', '=', cid)])
            n_payments = self.env['microfinance.loan.payment'].sudo().search_count([('company_id', '=', cid)])
            n_installments = self.env['microfinance.loan.installment'].sudo().search_count([('company_id', '=', cid)])
            n_loans = self.env['microfinance.loan'].sudo().search_count([('company_id', '=', cid)])
            n_sav_txn = self.env['microfinance.savings.transaction'].sudo().search_count([('company_id', '=', cid)])
            n_sav_acc = self.env['microfinance.savings.account'].sudo().search_count([('company_id', '=', cid)])
            n_moves = Move.search_count(self._accounting_domain(cid))
            lines.append(
                f"[{cid}] {company.name} : "
                f"{n_loans} crédits, {n_installments} échéances, {n_payments} remboursements, "
                f"{n_guarantees} garanties, {n_scoring} lignes de scoring, "
                f"{n_reschedule} historiques de rééchelonnement, {n_visits} visites de recouvrement, "
                f"{n_sav_acc} comptes épargne, {n_sav_txn} transactions épargne, "
                f"{n_moves} écritures comptables liées"
            )

        self.log = "APERÇU (aucune donnée modifiée) :\n\n" + "\n".join(lines)
        return self._reopen()

    def _accounting_domain(self, cid, extra_move_ids=None):
        domain = [
            ('company_id', '=', cid),
            '|', '|', '|',
            ('microfinance_loan_id', '!=', False),
            ('microfinance_payment_id', '!=', False),
            ('microfinance_savings_account_id', '!=', False),
            ('microfinance_savings_transaction_id', '!=', False),
        ]
        if extra_move_ids:
            domain = ['|'] + domain + [('id', 'in', list(extra_move_ids))]
        return domain

    # ------------------------------------------------------------------
    # Initialisation d'une simulation ou d'une exécution réelle
    # ------------------------------------------------------------------
    def action_start_dry_run(self):
        self.ensure_one()
        return self._start(dry_run=True)

    def action_start_execute(self):
        self.ensure_one()
        if not self.i_confirm:
            raise UserError(_(
                "Vous devez cocher la case de confirmation (backup effectué) "
                "avant de lancer l'exécution réelle."
            ))
        if (self.confirm_text or '').strip().upper() != 'SUPPRIMER':
            raise UserError(_('Retapez exactement "SUPPRIMER" pour confirmer.'))
        return self._start(dry_run=False)

    def _start(self, dry_run):
        self.ensure_one()
        if not self.company_ids:
            raise UserError(_("Sélectionnez au moins une agence."))
        self._check_companies_in_scope()
        self._acquire_lock_or_raise()

        total = len(self.company_ids)
        self.write({
            'state': 'running',
            'is_dry_run': dry_run,
            'total_steps': total,
            'step_index': 0,
            'pending_company_ids': [(6, 0, self.company_ids.ids)],
            'current_label': _("Prêt à démarrer…"),
            'batch_progress': False,
            'live_trace': False,
            'log': ("MODE SIMULATION (dry-run)\n" if dry_run else "MODE EXÉCUTION RÉELLE\n"),
        })
        return self._reopen()

    # ------------------------------------------------------------------
    def action_process_next_step(self):
        self.ensure_one()
        self._acquire_lock_or_raise()
        self._process_one_step()
        return self._reopen()

    def action_process_all_remaining(self):
        self.ensure_one()
        while self.state == 'running':
            self._acquire_lock_or_raise()
            self._process_one_step()
        return self._reopen()

    # ------------------------------------------------------------------
    # Cœur du traitement : une étape = une agence
    # ------------------------------------------------------------------
    def _process_one_step(self):
        self.ensure_one()
        self = self.sudo()
        cr = self.env.cr
        dry_run = self.is_dry_run
        new_log = []
        company_stats = {'batches_committed': 0}

        sp = cr.savepoint() if dry_run else None
        try:
            if self.pending_company_ids:
                company = self.pending_company_ids[0]
                cid = company.id
                self.current_label = _("Traitement de %s…") % company.name
                self.batch_progress = False
                new_log.extend(self._process_company(cid, company.name, dry_run, company_stats))
                self.pending_company_ids = [(3, cid, 0)]

            self.step_index += 1
            self.batch_progress = False

            if not dry_run:
                cr.commit()
            else:
                sp.rollback()
                cr.rollback()

            if self.step_index >= self.total_steps:
                self.state = 'done'
                self.current_label = _("Terminé.")
                new_log.append(
                    "\n=== SIMULATION TERMINÉE (rollback, rien de modifié) ==="
                    if dry_run else
                    "\n=== EXÉCUTION TERMINÉE (modifications validées) ==="
                )

        except Exception as e:
            if dry_run and sp:
                sp.rollback()
            cr.rollback()
            self.state = 'done'
            self.current_label = _("Erreur — arrêté.")
            new_log.append(f"\nERREUR : {type(e).__name__}: {e}")
            if not dry_run and company_stats['batches_committed']:
                new_log.append(
                    f"Erreur après {company_stats['batches_committed']} lot(s) déjà "
                    "validé(s) (commit) pour cette agence : ces suppressions sont "
                    "définitives et NE SERONT PAS annulées. Seul le lot en cours au "
                    "moment de l'erreur a été annulé (rollback partiel). Relancez "
                    "l'étape pour reprendre là où ça s'est arrêté (l'agence en tête de "
                    "pending_company_ids n'a pas encore été retirée)."
                )
            else:
                new_log.append("Rollback effectué — aucune donnée modifiée pour cette étape.")

        self.log = (self.log or '') + "\n" + "\n".join(new_log)

    # ------------------------------------------------------------------
    def _batch_unlink(self, model_name, domain, label, cid, company_name,
                       dry_run, stats, pre_unlink=None):
        Model = self.env[model_name].sudo()
        all_ids = Model.search(domain).ids
        total = len(all_ids)
        self._trace(
            f"Agence [{cid}] {company_name} : lecture de {total} {label} à traiter"
        )
        if not total:
            return 0

        nb_batches = -(-total // self._BATCH_SIZE)
        for i in range(0, total, self._BATCH_SIZE):
            batch_ids = all_ids[i:i + self._BATCH_SIZE]
            records = Model.browse(batch_ids)
            if pre_unlink:
                pre_unlink(records)
            records.unlink()
            done = i + len(batch_ids)
            batch_num = i // self._BATCH_SIZE + 1
            self.current_label = _("Agence %s : %s (%s/%s)…") % (
                company_name, label, done, total)
            self.batch_progress = _("%s / %s %s traités") % (done, total, label)
            self._trace(
                f"Lot {label} {batch_num}/{nb_batches} : suppression de "
                f"{len(batch_ids)} {model_name} (IDs {batch_ids[0]}-{batch_ids[-1]})"
            )
            if not dry_run:
                stats['batches_committed'] += 1

        return total

    # ------------------------------------------------------------------
    # Traitement complet d'une agence (tous les blocs cochés). Ordre contraint par
    # deux types de FK différents :
    # - ondelete='restrict' (loan.payment.loan_id, savings.transaction.account_id) :
    #   l'enfant doit être supprimé avant son parent, sinon Odoo lève une erreur FK.
    # - ondelete='set null' (les 4 tags microfinance_* sur account.move) : le bloc
    #   comptable doit au contraire tourner AVANT loans/payments/savings, sinon leur
    #   suppression met les tags à NULL et les écritures deviennent invisibles au
    #   filtre — orphelines, jamais supprimées (voir commentaire détaillé plus bas).
    # Les blocs purement cascade (collection_visit, guarantee, scoring_line,
    # reschedule_history) sont traités en premier, explicitement, pour un journal
    # détaillé — leur ordre entre eux n'a pas d'impact fonctionnel.
    # ------------------------------------------------------------------
    def _process_company(self, cid, company_name, dry_run, stats):
        lines = []

        if self.do_collection_visits:
            n = self._batch_unlink(
                'microfinance.collection.visit', [('company_id', '=', cid)],
                "visites de recouvrement", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n} microfinance.collection.visit supprimées (par lots de {self._BATCH_SIZE})")

        if self.do_loan_guarantees:
            n = self._batch_unlink(
                'microfinance.loan.guarantee', [('company_id', '=', cid)],
                "garanties de crédit", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n} microfinance.loan.guarantee supprimées (par lots de {self._BATCH_SIZE})")

        if self.do_scoring_lines:
            n = self._batch_unlink(
                'microfinance.scoring.line', [('company_id', '=', cid)],
                "lignes de scoring", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n} microfinance.scoring.line supprimées (par lots de {self._BATCH_SIZE})")

        if self.do_reschedule_history:
            n = self._batch_unlink(
                'microfinance.loan.reschedule.history', [('company_id', '=', cid)],
                "historiques de rééchelonnement", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n} microfinance.loan.reschedule.history supprimés (par lots de {self._BATCH_SIZE}, lignes liées en cascade)")

        # CRITIQUE : le bloc comptable doit tourner ICI, avant loan_payments/loans/
        # savings_transactions/savings_accounts. microfinance_loan_id,
        # microfinance_payment_id, microfinance_savings_account_id et
        # microfinance_savings_transaction_id sur account.move sont tous en
        # ondelete='set null' (pas 'cascade', pas 'restrict') : supprimer le crédit/
        # paiement/compte AVANT ces écritures met leur tag à NULL, les rendant
        # invisibles au domaine ci-dessous et les laissant orphelines, postées, jamais
        # supprimées — écart comptable silencieux (constaté en pratique : deux
        # écritures orphelines sur CEFOR Isotry après un essai avec l'ordre inversé).
        # reversal_move_id (contre-passation d'un remboursement annulé) est collecté
        # ici aussi, tant que les paiements existent encore : ce champ est copy=False
        # et ne porte donc pas le tag microfinance_payment_id lui-même.
        if self.do_accounting_entries:
            reversal_move_ids = self.env['microfinance.loan.payment'].sudo().search([
                ('company_id', '=', cid), ('reversal_move_id', '!=', False),
            ]).mapped('reversal_move_id').ids
            n = self._batch_unlink(
                'account.move', self._accounting_domain(cid, reversal_move_ids),
                "écritures comptables", cid, company_name, dry_run, stats,
                pre_unlink=lambda recs: recs.filtered(lambda m: m.state == 'posted').button_draft(),
            )
            lines.append(f"  - {n} account.move supprimées (par lots de {self._BATCH_SIZE})")

        if self.do_loan_payments:
            n = self._batch_unlink(
                'microfinance.loan.payment', [('company_id', '=', cid)],
                "remboursements crédit", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n} microfinance.loan.payment supprimés (par lots de {self._BATCH_SIZE})")

        if self.do_loan_installments:
            n = self._batch_unlink(
                'microfinance.loan.installment', [('company_id', '=', cid)],
                "échéances", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n} microfinance.loan.installment supprimées (par lots de {self._BATCH_SIZE})")

        if self.do_loans:
            n = self._batch_unlink(
                'microfinance.loan', [('company_id', '=', cid)],
                "crédits", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n} microfinance.loan supprimés (par lots de {self._BATCH_SIZE})")

        if self.do_savings_transactions:
            n = self._batch_unlink(
                'microfinance.savings.transaction', [('company_id', '=', cid)],
                "transactions d'épargne", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n} microfinance.savings.transaction supprimées (par lots de {self._BATCH_SIZE})")

        if self.do_savings_accounts:
            n = self._batch_unlink(
                'microfinance.savings.account', [('company_id', '=', cid)],
                "comptes d'épargne", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n} microfinance.savings.account supprimés (par lots de {self._BATCH_SIZE})")

        return [f"Agence [{cid}] {company_name} :"] + lines

    # ------------------------------------------------------------------
    def action_reset_wizard(self):
        """Revenir à l'état brouillon pour relancer une nouvelle opération."""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'total_steps': 0,
            'step_index': 0,
            'pending_company_ids': [(5, 0, 0)],
            'current_label': False,
            'batch_progress': False,
            'live_trace': False,
            'log': False,
            'i_confirm': False,
            'confirm_text': False,
        })
        return self._reopen()

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'microfinance.data.reset.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
