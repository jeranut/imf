# -*- coding: utf-8 -*-
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class DataResetWizard(models.TransientModel):
    _name = 'data.reset.wizard'
    _description = "Assistant de remise à zéro des données transactionnelles"
    _LOCK_KEY = 823476512
    _BATCH_SIZE = 100
    _TRACE_MAX_LINES = 30

    company_ids = fields.Many2many(
        'res.company',
        string="Sociétés à nettoyer",
        required=True,
        help="Sélectionnez uniquement les sociétés à remettre à zéro. "
             "Les autres sociétés ne seront jamais touchées.",
    )

    # --- Périmètre : chaque bloc peut être désactivé indépendamment ---
    do_payments = fields.Boolean(string="Paiements (account.payment)", default=True)
    do_intercompany = fields.Boolean(
        string="Casser les liens de facturation inter-société",
        default=True,
        help="Nécessaire avant de supprimer des factures liées à une facture "
             "miroir dans une autre société (sinon Odoo bloque la suppression).",
    )
    do_advance_payment = fields.Boolean(
        string="Avances sur paiement (custom.paid.advance.payment)", default=True,
        help="Référence account.move via move_id/invoice_ids : traité avant "
             "les factures, comme les autres blocs liés à la comptabilité.",
    )
    do_invoices = fields.Boolean(string="Factures / avoirs (account.move)", default=True)
    do_purchase = fields.Boolean(string="Commandes fournisseurs (purchase.order)", default=True)
    do_sale = fields.Boolean(string="Commandes clients (sale.order)", default=True)
    do_stock = fields.Boolean(string="Transferts de stock (stock.picking/move)", default=True)
    do_quants = fields.Boolean(string="Quantités en stock (stock.quant)", default=True)
    do_daily_balance = fields.Boolean(
        string="Soldes journaliers (account.daily.balance)", default=True)
    do_daily_balance_mobile = fields.Boolean(
        string="Soldes journaliers mobile money (account.daily.balance.mobile)", default=True)
    do_hr_expense = fields.Boolean(
        string="Notes de frais (hr.expense)", default=True,
        help="Les dépenses approuvées/comptabilisées sont d'abord repassées "
             "en brouillon (write state='draft') avant suppression, sinon "
             "Odoo bloque l'unlink().",
    )

    i_confirm = fields.Boolean(
        string="Je confirme avoir fait un backup complet de la base et je "
               "veux supprimer définitivement ces données",
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
    do_intercompany_pending = fields.Boolean(readonly=True, default=False)
    pending_company_ids = fields.Many2many(
        'res.company', 'data_reset_wizard_pending_rel',
        string="Sociétés restantes", readonly=True,
    )
    current_label = fields.Char(readonly=True, string="Étape en cours")
    batch_progress = fields.Char(
        readonly=True, string="Avancement du lot en cours",
        help="Détail fin de la progression par lots de _BATCH_SIZE au sein "
             "de l'étape courante (ex: '3500 / 4652 factures traitées').",
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
                "Une autre opération de RAZ est déjà en cours (dans cet onglet ou "
                "un autre). Patientez qu'elle se termine ou fermez les autres onglets "
                "avant de réessayer."
            ))

    # ------------------------------------------------------------------
    # Trace fine, horodatée, committée immédiatement (mode réel) pour donner
    # une visibilité en direct pendant qu'un lot est en cours de traitement.
    # En dry-run, un commit ici casserait le rollback global de la
    # simulation : on se contente d'accumuler le message dans le journal
    # principal (self.log), sans toucher live_trace ni committer.
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
            raise UserError(_("Sélectionnez au moins une société."))

        lines = []
        Payment = self.env['account.payment'].sudo()
        for company in self.company_ids:
            cid = company.id
            n_payments = Payment.search_count([('move_id.company_id', '=', cid)])
            n_moves = self.env['account.move'].sudo().search_count([('company_id', '=', cid)])
            n_po = self.env['purchase.order'].sudo().search_count([('company_id', '=', cid)])
            n_so = self.env['sale.order'].sudo().search_count([('company_id', '=', cid)])
            n_picking = self.env['stock.picking'].sudo().search_count([('company_id', '=', cid)])
            n_quant = self.env['stock.quant'].sudo().search_count([('company_id', '=', cid)])
            lines.append(
                f"[{cid}] {company.name} : "
                f"{n_payments} paiements, {n_moves} factures, "
                f"{n_po} commandes fourn., {n_so} commandes clients, "
                f"{n_picking} transferts stock, {n_quant} quants"
            )

        self.log = "APERÇU (aucune donnée modifiée) :\n\n" + "\n".join(lines)
        return self._reopen()

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
        return self._start(dry_run=False)

    def _start(self, dry_run):
        self.ensure_one()
        if not self.company_ids:
            raise UserError(_("Sélectionnez au moins une société."))
        self._acquire_lock_or_raise()

        total = len(self.company_ids) + (1 if self.do_intercompany else 0)
        self.write({
            'state': 'running',
            'is_dry_run': dry_run,
            'total_steps': total,
            'step_index': 0,
            'do_intercompany_pending': self.do_intercompany,
            'pending_company_ids': [(6, 0, self.company_ids.ids)],
            'current_label': _("Prêt à démarrer…"),
            'batch_progress': False,
            'live_trace': False,
            'log': ("MODE SIMULATION (dry-run)\n" if dry_run else "MODE EXÉCUTION RÉELLE\n"),
        })
        return self._reopen()

    # ------------------------------------------------------------------
    # Traiter une seule étape (bouton "Étape suivante")
    # ------------------------------------------------------------------
    def action_process_next_step(self):
        self.ensure_one()
        self._acquire_lock_or_raise()
        self._process_one_step()
        return self._reopen()

    # ------------------------------------------------------------------
    # Traiter tout le reste d'un coup (bouton "Tout traiter")
    # ------------------------------------------------------------------
    def action_process_all_remaining(self):
        self.ensure_one()
        while self.state == 'running':
            self._acquire_lock_or_raise()
            self._process_one_step()
        return self._reopen()

    # ------------------------------------------------------------------
    # Cœur du traitement : une étape = le bloc inter-société OU une société
    # ------------------------------------------------------------------
    def _process_one_step(self):
        self.ensure_one()
        self = self.sudo()
        cr = self.env.cr
        dry_run = self.is_dry_run
        new_log = []
        # Compteur de lots réellement committés pendant cette étape. En mode
        # réel, chaque bloc de _process_company commit lot par lot : si une
        # exception survient en cours de route, ce compteur (rempli par
        # référence avant que l'exception ne remonte) permet de savoir
        # combien de lots sont déjà acquis en base et ne seront PAS annulés
        # par le rollback ci-dessous.
        company_stats = {'batches_committed': 0}

        sp = cr.savepoint() if dry_run else None
        try:
            if self.do_intercompany_pending:
                cids = tuple(self.company_ids.ids)
                self.current_label = _("Cassage des liens inter-société…")
                cr.execute("""
                    UPDATE account_move
                    SET auto_invoice_id = NULL
                    WHERE company_id IN %s
                       OR auto_invoice_id IN (
                           SELECT id FROM account_move WHERE company_id IN %s
                       )
                """, (cids, cids))
                n_broken = cr.rowcount
                new_log.append(f"Liens inter-société cassés : {n_broken} lignes")
                self._trace(
                    f"Cassage liens inter-société : UPDATE account_move "
                    f"SET auto_invoice_id = NULL ({n_broken} lignes)"
                )
                self.env.registry.clear_cache()
                self.do_intercompany_pending = False

            elif self.pending_company_ids:
                company = self.pending_company_ids[0]
                cid = company.id
                self.current_label = _("Traitement de %s…") % company.name
                self.batch_progress = False
                new_log.extend(self._process_company(cid, company.name, dry_run, company_stats))
                self.pending_company_ids = [(3, cid, 0)]  # retire de la liste

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
                    "validé(s) (commit) pour cette société : ces suppressions sont "
                    "définitives et NE SERONT PAS annulées. Seul le lot en cours au "
                    "moment de l'erreur a été annulé (rollback partiel). Relancez "
                    "l'étape pour reprendre là où ça s'est arrêté."
                )
            else:
                new_log.append("Rollback effectué — aucune donnée modifiée pour cette étape.")

        self.log = (self.log or '') + "\n" + "\n".join(new_log)

    # ------------------------------------------------------------------
    # Supprime les enregistrements d'un modèle par lots de _BATCH_SIZE.
    # En mode réel (dry_run=False), commit après chaque lot pour limiter la
    # durée de chaque transaction et rendre la RAZ interruptible/reprenable.
    # En dry-run, on boucle quand même (pour la cohérence de la progression
    # affichée) mais sans jamais committer : le savepoint global de
    # _process_one_step annule tout à la fin, comme avant.
    # ------------------------------------------------------------------
    def _batch_unlink(self, model_name, domain, label, cid, company_name,
                       dry_run, stats, pre_unlink=None):
        Model = self.env[model_name].sudo()
        all_ids = Model.search(domain).ids
        total = len(all_ids)
        self._trace(
            f"Société [{cid}] {company_name} : lecture de {total} {label} à traiter"
        )
        if not total:
            return 0

        nb_batches = -(-total // self._BATCH_SIZE)  # ceil division
        for i in range(0, total, self._BATCH_SIZE):
            batch_ids = all_ids[i:i + self._BATCH_SIZE]
            records = Model.browse(batch_ids)
            if pre_unlink:
                pre_unlink(records)
            records.unlink()
            done = i + len(batch_ids)
            batch_num = i // self._BATCH_SIZE + 1
            self.current_label = _("Société %s : %s (%s/%s)…") % (
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
    # Suppression SQL directe par lots (DELETE ... WHERE id IN (SELECT ...
    # LIMIT _BATCH_SIZE)) : utilisé pour le stock, trop volumineux pour
    # passer par l'ORM. `delete_params` ne doit PAS inclure la taille de
    # lot, elle est ajoutée automatiquement en dernier paramètre.
    # ------------------------------------------------------------------
    def _batch_delete_sql(self, dry_run, stats, count_sql, count_params,
                           delete_sql, delete_params, label, company_name,
                           cid=None):
        cr = self.env.cr
        cr.execute(count_sql, count_params)
        total = cr.fetchone()[0]
        cid_label = cid if cid is not None else count_params[0]
        self._trace(
            f"Société [{cid_label}] {company_name} : lecture de {total} {label} à traiter"
        )
        if not total:
            return 0

        nb_batches = -(-total // self._BATCH_SIZE)  # ceil division
        done = 0
        batch_num = 0
        while True:
            cr.execute(delete_sql, delete_params + (self._BATCH_SIZE,))
            deleted = cr.rowcount
            if not deleted:
                break
            done += deleted
            batch_num += 1
            self.current_label = _("Société %s : %s (%s/%s)…") % (
                company_name, label, done, total)
            self.batch_progress = _("%s / %s %s supprimés") % (done, total, label)
            self._trace(
                f"Lot {label} {batch_num}/{nb_batches} : DELETE ({deleted} lignes, "
                f"company={cid_label})"
            )
            if not dry_run:
                stats['batches_committed'] += 1

        return total

    # ------------------------------------------------------------------
    # Traitement complet d'une société (tous les blocs cochés)
    # ------------------------------------------------------------------
    def _process_company(self, cid, company_name, dry_run, stats):
        lines = []

        if self.do_payments:
            Payment = self.env['account.payment']
            payments = Payment.sudo().search([('move_id.company_id', '=', cid)])
            reconciled = payments.move_id.line_ids.filtered(
                lambda l: l.matched_debit_ids or l.matched_credit_ids
            )
            reconciled.remove_move_reconcile()
            n = len(payments)
            payments.unlink()
            lines.append(f"  - {n} account.payment supprimés")

        if self.do_advance_payment:
            # move_id (Many2one vers account.move) est en ondelete='set null'
            # et invoice_ids est un many2many : aucun des deux ne bloque la
            # suppression, mais on traite ce bloc avant les factures pour
            # rester cohérent avec account.payment (même famille "paiement").
            n_adv = self._batch_unlink(
                'custom.paid.advance.payment', [('company_id', '=', cid)],
                "avances sur paiement", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n_adv} custom.paid.advance.payment supprimées (par lots de {self._BATCH_SIZE})")

        if self.do_invoices:
            n_moves = self._batch_unlink(
                'account.move', [('company_id', '=', cid)], "factures",
                cid, company_name, dry_run, stats,
                pre_unlink=lambda recs: recs.filtered(lambda m: m.state == 'posted').button_draft(),
            )
            lines.append(f"  - {n_moves} account.move supprimées (par lots de {self._BATCH_SIZE})")

        if self.do_purchase:
            n_po = self._batch_unlink(
                'purchase.order', [('company_id', '=', cid)], "commandes fournisseurs",
                cid, company_name, dry_run, stats,
                pre_unlink=lambda recs: recs.write({'state': 'cancel'}),
            )
            lines.append(f"  - {n_po} purchase.order supprimées (par lots de {self._BATCH_SIZE})")

        if self.do_sale:
            n_so = self._batch_unlink(
                'sale.order', [('company_id', '=', cid)], "commandes clients",
                cid, company_name, dry_run, stats,
                pre_unlink=lambda recs: recs.write({'state': 'cancel'}),
            )
            lines.append(f"  - {n_so} sale.order supprimées (par lots de {self._BATCH_SIZE})")

        if self.do_stock:
            n_sml = self._batch_delete_sql(
                dry_run, stats,
                count_sql="""
                    SELECT count(*) FROM stock_move_line sml
                    JOIN stock_picking sp ON sp.id = sml.picking_id
                    WHERE sp.company_id = %s
                """,
                count_params=(cid,),
                delete_sql="""
                    DELETE FROM stock_move_line WHERE id IN (
                        SELECT sml.id FROM stock_move_line sml
                        JOIN stock_picking sp ON sp.id = sml.picking_id
                        WHERE sp.company_id = %s LIMIT %s
                    )
                """,
                delete_params=(cid,),
                label="lignes de mouvement (stock.move.line)",
                company_name=company_name,
                cid=cid,
            )

            n_sm = self._batch_delete_sql(
                dry_run, stats,
                count_sql="""
                    SELECT count(*) FROM stock_move sm
                    LEFT JOIN stock_picking sp ON sp.id = sm.picking_id
                    WHERE sp.company_id = %s OR sm.company_id = %s
                """,
                count_params=(cid, cid),
                delete_sql="""
                    DELETE FROM stock_move WHERE id IN (
                        SELECT sm.id FROM stock_move sm
                        LEFT JOIN stock_picking sp ON sp.id = sm.picking_id
                        WHERE sp.company_id = %s OR sm.company_id = %s LIMIT %s
                    )
                """,
                delete_params=(cid, cid),
                label="mouvements de stock (stock.move)",
                company_name=company_name,
                cid=cid,
            )

            n_sp = self._batch_delete_sql(
                dry_run, stats,
                count_sql="SELECT count(*) FROM stock_picking WHERE company_id = %s",
                count_params=(cid,),
                delete_sql="""
                    DELETE FROM stock_picking WHERE id IN (
                        SELECT id FROM stock_picking WHERE company_id = %s LIMIT %s
                    )
                """,
                delete_params=(cid,),
                label="transferts de stock (stock.picking)",
                company_name=company_name,
                cid=cid,
            )

            self.env.registry.clear_cache()
            lines.append(
                f"  - {n_sp} stock.picking, {n_sm} stock.move, {n_sml} stock.move.line "
                f"supprimés par lots de {self._BATCH_SIZE} (SQL)"
            )

        if self.do_quants:
            n_q = self._batch_unlink(
                'stock.quant', [('company_id', '=', cid)], "quants",
                cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n_q} stock.quant supprimés (par lots de {self._BATCH_SIZE})")

        if self.do_daily_balance:
            n_db = self._batch_unlink(
                'account.daily.balance', [('company_id', '=', cid)],
                "soldes journaliers", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n_db} account.daily.balance supprimés (par lots de {self._BATCH_SIZE})")

        if self.do_daily_balance_mobile:
            n_dbm = self._batch_unlink(
                'account.daily.balance.mobile', [('company_id', '=', cid)],
                "soldes journaliers mobile money", cid, company_name, dry_run, stats,
            )
            lines.append(f"  - {n_dbm} account.daily.balance.mobile supprimés (par lots de {self._BATCH_SIZE})")

        if self.do_hr_expense:
            # hr.expense bloque unlink() sur les états 'approved'/'done'
            # (UserError "Vous ne pouvez pas supprimer une dépense
            # comptabilisée ou approuvée."). On repasse en 'draft' avant de
            # supprimer, comme pour purchase.order/sale.order. Note : les
            # hr.expense.sheet associées ne sont pas dans le périmètre de ce
            # bloc et resteront en base (vides de leurs lignes de dépense).
            n_exp = self._batch_unlink(
                'hr.expense', [('company_id', '=', cid)], "notes de frais",
                cid, company_name, dry_run, stats,
                pre_unlink=lambda recs: recs.write({'state': 'draft'}),
            )
            lines.append(f"  - {n_exp} hr.expense supprimées (par lots de {self._BATCH_SIZE})")

        return [f"Société [{cid}] {company_name} :"] + lines

    # ------------------------------------------------------------------
    def action_reset_wizard(self):
        """Revenir à l'état brouillon pour relancer une nouvelle opération."""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'total_steps': 0,
            'step_index': 0,
            'do_intercompany_pending': False,
            'pending_company_ids': [(5, 0, 0)],
            'current_label': False,
            'batch_progress': False,
            'live_trace': False,
            'log': False,
            'i_confirm': False,
        })
        return self._reopen()

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'data.reset.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
