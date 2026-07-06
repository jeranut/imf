# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError
from datetime import timedelta, datetime
from collections import defaultdict
from dateutil.relativedelta import relativedelta


# -------------------------
# Journal Mobile principal
# -------------------------
class AccountDailyBalanceMobile(models.Model):
    _name = 'account.daily.balance.mobile'
    _description = 'Rapport journalier Encaissements/Décaissements par journal'
    _inherit = ['mail.thread']
    _rec_name = 'date'
    _check_company_auto = True

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, readonly=True)
    total_debit = fields.Float(string='Total Décaissements', readonly=True)
    total_credit = fields.Float(string='Total Encaissements', readonly=True)
    ancien_solde = fields.Float(string='Ancien solde', readonly=True)
    nouveau_solde = fields.Float(string='Nouveau solde', readonly=True)
    show_lines = fields.Boolean(string='Afficher les lignes', default=False)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company.id
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    operator_id = fields.Many2one(
        'mobile.money.operator',
        string='Journal de trésorerie',
        domain="[('company_id', '=', company_id)]",
        check_company=True,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal comptable',
        related='operator_id.journal_id',
        store=True,
        readonly=True,
        check_company=True,
    )

    line_ids = fields.One2many('account.daily.balance.mobile.line', 'balance_id', string='Détails')

    _sql_constraints = [
        (
            'unique_date_company_operator',
            'unique(date, company_id, operator_id)',
            'Une seule balance est autorisée par jour, société et journal.',
        )
    ]
    etats = fields.Selection(
        [('ouvert', 'OUVERT ✏️'), ('cloturer', '🔒 CLOTURER')],
        string="État",
        default='ouvert',
        readonly=True
    )
    closing_move_id = fields.Many2one(
        'account.move',
        string='Écriture de clôture',
        readonly=True,
        copy=False,
        help="Écriture comptable générée à la clôture, transférant le solde "
             "net du jour des comptes d'attente vers le compte de trésorerie "
             "réel de cet opérateur Mobile Money.",
    )

    def get_dashboard_chart_data(self, period='day'):
        self.ensure_one()
        if period not in ('day', 'month'):
            raise UserError(_("La période du dashboard doit être 'day' ou 'month'."))

        date_from = self.date
        date_to = self.date
        if period == 'month':
            date_from = self.date.replace(day=1)
            date_to = date_from + relativedelta(months=1, days=-1)

        lines = self.env['account.daily.balance.mobile.line'].search([
            ('company_id', '=', self.company_id.id),
            ('balance_id.operator_id', '=', self.operator_id.id),
            ('balance_id.date', '>=', date_from),
            ('balance_id.date', '<=', date_to),
        ])
        expenses = defaultdict(float)
        sales = defaultdict(float)

        for line in lines:
            label = line.libelle or line.reference or _("Sans libellé")
            if line.debit > 0:
                expenses[label] += line.debit
            if line.credit > 0:
                sales[label] += line.credit

        def chart_values(values):
            ordered = sorted(values.items(), key=lambda item: item[1], reverse=True)
            return {
                'labels': [label for label, amount in ordered],
                'series': [amount for label, amount in ordered],
            }

        return {
            'expenses': chart_values(expenses),
            'sales': chart_values(sales),
            'currency': {
                'symbol': self.company_currency_id.symbol or self.company_currency_id.name,
                'position': self.company_currency_id.position,
            },
        }

    def action_open_dashboard_lines(self, period, section, label):
        self.ensure_one()
        if period not in ('day', 'month') or section not in ('expenses', 'sales'):
            raise UserError(_("Filtre du dashboard invalide."))

        date_from = self.date
        date_to = self.date
        if period == 'month':
            date_from = self.date.replace(day=1)
            date_to = date_from + relativedelta(months=1, days=-1)

        lines = self.env['account.daily.balance.mobile.line'].search([
            ('company_id', '=', self.company_id.id),
            ('operator_id', '=', self.operator_id.id),
            ('balance_id.date', '>=', date_from),
            ('balance_id.date', '<=', date_to),
            ('debit' if section == 'expenses' else 'credit', '>', 0),
        ]).filtered(
            lambda line: (line.libelle or line.reference or _("Sans libellé")) == label
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _("%(label)s - lignes d'origine", label=label),
            'res_model': 'account.daily.balance.mobile.line',
            'view_mode': 'tree,form',
            'views': [
                (self.env.ref('custom_paid_totals.view_account_daily_balance_mobile_line_dashboard_tree').id, 'tree'),
                (False, 'form'),
            ],
            'domain': [('id', 'in', lines.ids)],
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    def action_open_retrait_wizard(self):
        self.ensure_one()
        return {
            "name": _("Veuillez entrer la description et la référence de la transaction et le montant"),
            "type": "ir.actions.act_window",
            "res_model": "retrait.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_balance_id": self.id},
        }

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        operator_id = defaults.get('operator_id') or self.env.context.get('default_operator_id')
        if not operator_id and self.env.context.get('default_journal_id'):
            operator = self.env['mobile.money.operator'].search([
                ('journal_id', '=', self.env.context['default_journal_id']),
                ('company_id', '=', self.env.context.get('default_company_id') or self.env.company.id),
            ], limit=1)
            operator_id = operator.id
        if not operator_id:
            return defaults

        operator = self.env['mobile.money.operator'].browse(operator_id).exists()
        if not operator:
            return defaults
        if operator.company_id != self.env.company:
            raise UserError(_(
                "Le journal « %(journal)s » appartient à la société « %(journal_company)s », "
                "mais la société active est « %(active_company)s ».\n\n"
                "Rechargez la page après avoir sélectionné la bonne société.",
                journal=operator.display_name,
                journal_company=operator.company_id.display_name,
                active_company=self.env.company.display_name,
            ))
        defaults['company_id'] = operator.company_id.id

        today = fields.Date.context_today(self)
        last_balance = self.search(
            [
                ('company_id', '=', operator.company_id.id),
                ('operator_id', '=', operator_id),
                ('date', '<=', today),
            ],
            order="date desc",
            limit=1
        )

        if last_balance:
            if last_balance.date == today:
                if last_balance.etats == 'cloturer':
                    raise UserError(_(
                        "Le journal Mobile du jour est déjà clôturé.\n"
                        "Veuillez créer une nouvelle balance après 00:00 h."
                    ))
                else:
                    raise UserError(_(
                        "L’exercice mobile du jour a déjà été créé et est encore ouvert.\n"
                        "Veuillez utiliser la balance existante pour ajouter les opérations."
                    ))
            elif last_balance.date < today and last_balance.etats == 'ouvert':
                raise UserError(_(
                    "Le journal Mobile de la dernière balance n'est pas encore clôturé.\n"
                    "Veuillez d'abord clôturer le journal précédent."
                ))

        return defaults

    @api.model
    def create(self, vals):
        """Créer ou réutiliser la balance Mobile Money du jour."""
        today = fields.Date.context_today(self)
        operator_id = vals.get('operator_id')
        if not operator_id and vals.get('journal_id'):
            operator = self.env['mobile.money.operator'].search([
                ('journal_id', '=', vals['journal_id']),
                ('company_id', '=', vals.get('company_id') or self.env.company.id),
            ], limit=1)
            operator_id = operator.id
            vals['operator_id'] = operator_id
        if not operator_id:
            raise UserError(_("Veuillez sélectionner un opérateur Mobile Money."))
        operator = self.env['mobile.money.operator'].browse(operator_id).exists()
        if not operator:
            raise UserError(_("Le journal de trésorerie sélectionné n'existe plus."))
        company_id = operator.company_id.id
        vals['company_id'] = company_id

        date_record = vals.get('date') or today
        if isinstance(date_record, str):
            date_record = fields.Date.from_string(date_record)
        vals.setdefault('date', date_record)
        vals['etats'] = 'ouvert'

        # 1) Vérifier si une balance de la date existe déjà
        today_balance = self.search([
            ('company_id', '=', company_id),
            ('date', '=', date_record),
            ('operator_id', '=', operator_id),
        ], limit=1)

        if today_balance:
            # Si elle existe : on met à jour et on la renvoie
            today_balance.action_update_totals_mobile()
            return today_balance

        # 2) Récupérer la dernière balance
        last_balance = self.search([
            ('company_id', '=', company_id),
            ('operator_id', '=', operator_id),
            ('date', '<=', date_record),
        ], order="date desc", limit=1)

        # 4) Cas où aucune balance précédente n'existe ou la dernière est déjà clôturée
        if not last_balance or last_balance.etats == 'cloturer':
            # Ancien solde = dernier nouveau solde, sinon 0
            vals['ancien_solde'] = last_balance.nouveau_solde if last_balance else 0.0
            vals['company_id'] = company_id
            return super().create(vals)

        # Si la dernière balance est ouverte, continuer à l'utiliser.
        if last_balance.date < date_record and last_balance.etats == 'ouvert':
            last_balance.action_update_totals_mobile()
            return last_balance

        if last_balance.date == date_record - timedelta(days=1):
            vals['ancien_solde'] = last_balance.nouveau_solde
            vals['company_id'] = company_id
            return super().create(vals)

        vals['ancien_solde'] = last_balance.nouveau_solde
        vals['company_id'] = company_id
        return super().create(vals)

    def action_update_totals_mobile(self):
        for record in self:
            # Vérifier que le journal est ouvert
            if record.etats != 'ouvert':
                raise UserError(_("Journal déjà clôturé, impossible de recalculer."))

            # Ancien solde depuis la dernière balance clôturée
            last_closed_balance = self.search([
                ('company_id', '=', record.company_id.id),
                ('operator_id', '=', record.operator_id.id),
                ('etats', '=', 'cloturer'),
                ('date', '<', record.date),
            ], order='date desc', limit=1)
            record.ancien_solde = last_closed_balance.nouveau_solde if last_closed_balance else 0.0

            payments = record._get_mobile_payments()
            for payment in payments:
                reconciled_moves = payment.reconciled_invoice_ids | payment.reconciled_bill_ids
                expense = (
                    payment.move_id.line_ids.expense_id[:1]
                    or reconciled_moves.line_ids.expense_id[:1]
                )
                if expense:
                    self.env['account.daily.balance.mobile.line']._upsert_hr_expense_payment(
                        record, expense, payment
                    )
                    continue
                for move in reconciled_moves:
                    self.env['account.daily.balance.mobile.line']._upsert_invoice_payment(
                        record, move, payment
                    )

            # ───────────────
            # Recalcul des totaux
            # ───────────────
            total_credit = sum(record.line_ids.mapped('credit'))
            total_debit = sum(record.line_ids.mapped('debit'))
            record.nouveau_solde = record.ancien_solde + (total_credit - total_debit)

            # Mise à jour des totaux dans la balance
            record.write({
                'total_credit': total_credit,
                'total_debit': total_debit,
                'show_lines': True,
            })

    def _get_mobile_payments(self):
        """Paiements de CET opérateur contribuant aux totaux de cette
        balance : même requête que action_update_totals_mobile(), réutilisée
        telle quelle pour que la clôture réconcilie exactement les paiements
        qui ont produit les montants déjà affichés à l'utilisateur. Filtrer
        par journal_id de l'opérateur (donc implicitement par opérateur) est
        indispensable : plusieurs opérateurs d'une même société partagent le
        même compte d'attente natif Odoo (cf. discussion de conception)."""
        self.ensure_one()
        return self.env['account.payment'].search([
            ('state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
            ('journal_id', '=', self.operator_id.journal_id.id),
            ('date', '>=', self.date),
        ])

    def action_cloturer_mobile(self):
        self.ensure_one()

        if self.etats == 'cloturer':
            raise UserError(_("Le journal Mobile Money est déjà clôturé."))

        if not self.closing_move_id:
            self._generate_closing_move_mobile()

        self.etats = 'cloturer'
        return True

    def _generate_closing_move_mobile(self):
        """Équivalent Mobile Money de AccountDailyBalance._generate_closing_move() :
        transfère le solde net du jour des comptes d'attente natifs Odoo vers
        le compte de trésorerie réel de CET opérateur (operator_id.
        journal_account_id), en ne réconciliant que les lignes d'attente
        provenant des paiements de cet opérateur précis (_get_mobile_payments,
        filtré par journal_id)."""
        self.ensure_one()

        if not self.total_credit and not self.total_debit:
            return

        treasury_account = self.operator_id.journal_account_id
        if not treasury_account:
            raise UserError(_(
                "Le journal « %(journal)s » de l'opérateur « %(operator)s » n'a "
                "pas de compte comptable par défaut configuré.",
                journal=self.operator_id.journal_id.display_name,
                operator=self.operator_id.display_name,
            ))
        receipts_account, payments_account = self.company_id._get_cash_suspense_accounts()

        receipts_lines = self.env['account.move.line']
        payments_lines = self.env['account.move.line']
        for payment in self._get_mobile_payments():
            suspense_lines = payment.move_id.line_ids.filtered(lambda l: not l.reconciled)
            receipts_lines |= suspense_lines.filtered(lambda l: l.account_id == receipts_account)
            payments_lines |= suspense_lines.filtered(lambda l: l.account_id == payments_account)

        operator_name = self.operator_id.display_name
        move_lines = []
        if self.total_credit:
            move_lines.append((0, 0, {
                'name': _("Clôture %(op)s du %(date)s - Trésorerie", op=operator_name, date=self.date),
                'account_id': treasury_account.id,
                'debit': self.total_credit,
                'credit': 0.0,
            }))
            move_lines.append((0, 0, {
                'name': _("Clôture %(op)s du %(date)s - Encaissements", op=operator_name, date=self.date),
                'account_id': receipts_account.id,
                'debit': 0.0,
                'credit': self.total_credit,
            }))
        if self.total_debit:
            move_lines.append((0, 0, {
                'name': _("Clôture %(op)s du %(date)s - Décaissements", op=operator_name, date=self.date),
                'account_id': payments_account.id,
                'debit': self.total_debit,
                'credit': 0.0,
            }))
            move_lines.append((0, 0, {
                'name': _("Clôture %(op)s du %(date)s - Trésorerie", op=operator_name, date=self.date),
                'account_id': treasury_account.id,
                'debit': 0.0,
                'credit': self.total_debit,
            }))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.operator_id.journal_id.id,
            'date': self.date,
            'ref': _("Clôture %(op)s du %(date)s", op=operator_name, date=self.date),
            'line_ids': move_lines,
        })
        move.action_post()
        self.closing_move_id = move.id

        if self.total_credit:
            self._reconcile_closing_lines_mobile(move, receipts_account, receipts_lines, self.total_credit)
        if self.total_debit:
            self._reconcile_closing_lines_mobile(move, payments_account, payments_lines, self.total_debit)

    def _reconcile_closing_lines_mobile(self, move, account, existing_lines, expected_amount):
        """Équivalent Mobile Money de
        AccountDailyBalance._reconcile_closing_lines() : ne bloque jamais la
        clôture, consigne un message clair sur la balance en cas d'absence de
        ligne, d'écart de montant ou d'échec technique du lettrage."""
        self.ensure_one()
        new_line = move.line_ids.filtered(lambda l: l.account_id == account)

        if not existing_lines:
            self.message_post(body=_(
                "Clôture %(op)s du %(date)s : aucune ligne d'attente trouvée sur "
                "le compte %(account)s à lettrer avec l'écriture de clôture "
                "(montant attendu : %(amount)s). À vérifier manuellement.",
                op=self.operator_id.display_name, date=self.date,
                account=account.display_name, amount=expected_amount,
            ))
            return

        matched_amount = abs(sum(existing_lines.mapped('debit')) - sum(existing_lines.mapped('credit')))
        if abs(matched_amount - expected_amount) > 0.01:
            self.message_post(body=_(
                "Clôture %(op)s du %(date)s : écart détecté sur le compte "
                "%(account)s — montant attendu %(expected)s, montant des lignes "
                "d'attente identifiées %(matched)s. Le lettrage a quand même été "
                "tenté ; vérifier manuellement.",
                op=self.operator_id.display_name, date=self.date,
                account=account.display_name,
                expected=expected_amount, matched=matched_amount,
            ))

        try:
            (existing_lines | new_line).reconcile()
        except Exception as error:
            self.message_post(body=_(
                "Clôture %(op)s du %(date)s : le lettrage automatique du compte "
                "%(account)s a échoué (%(error)s). Merci de lettrer manuellement "
                "les lignes concernées.",
                op=self.operator_id.display_name, date=self.date,
                account=account.display_name, error=str(error),
            ))

    def _check_reouvrir_access(self):
        """Équivalent Mobile Money de
        AccountDailyBalance._check_reouvrir_access()."""
        allowed_groups = (
            'custom_paid_totals.group_paid_totals_manager',
            'account.group_account_manager',
            'base.group_system',
        )
        if not any(self.env.user.has_group(group) for group in allowed_groups):
            raise AccessError(_(
                "Seuls les gestionnaires Trésorerie, les gestionnaires comptables "
                "ou les administrateurs peuvent rouvrir une balance clôturée."
            ))

    def action_reouvrir_mobile(self):
        self.ensure_one()
        self._check_reouvrir_access()

        if self.etats != 'cloturer':
            raise UserError(_("Cette balance n'est pas clôturée."))

        if not self.closing_move_id:
            self._reouvrir_sans_mouvement_mobile()
            return True

        return {
            'type': 'ir.actions.act_window',
            'name': _('Réouvrir la balance'),
            'res_model': 'reopen.balance.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_balance_mobile_id': self.id},
        }

    def _reouvrir_sans_mouvement_mobile(self):
        self.ensure_one()
        self.etats = 'ouvert'
        self.message_post(body=_(
            "Balance rouverte par %(user)s le %(datetime)s (aucun mouvement "
            "comptable à défaire — clôture historique sans mouvement).",
            user=self.env.user.display_name,
            datetime=fields.Datetime.now(),
        ))

    def _reouvrir_avec_mouvement_mobile(self, reason):
        """Équivalent Mobile Money de
        AccountDailyBalance._reouvrir_avec_mouvement()."""
        self.ensure_one()
        move = self.closing_move_id
        reversal = move._reverse_moves(default_values_list=[{
            'date': fields.Date.context_today(self),
            'ref': _("Contrepassation clôture %(op)s (réouverture)", op=self.operator_id.display_name),
        }], cancel=True)

        self.closing_move_id = False
        self.etats = 'ouvert'
        self.message_post(body=_(
            "Balance rouverte par %(user)s le %(datetime)s.\n"
            "Motif : %(reason)s\n"
            "Écriture de clôture contrepassée : %(move)s → %(reversal)s",
            user=self.env.user.display_name,
            datetime=fields.Datetime.now(),
            reason=reason,
            move=move.name or move.ref,
            reversal=(reversal.name or reversal.ref) if reversal else _("(échec de la contrepassation)"),
        ))

    def action_update_totals_wizard_mobile(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Veuillez entrer la description et la référence de la recette et le montant'),
            'res_model': 'update.totals.mobile.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_balance_id': self.id},
        }

    def action_init_solde_mobile(self):
        """Ouvre le wizard d'initialisation du solde pour ce journal mobile."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Saisir le solde initial Mobile Money'),
            'res_model': 'account.daily.balance.mobile.init.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_balance_id': self.id},
        }


# -------------------------
# Wizard REC Mobile
# -------------------------
class UpdateTotalsMobileWizard(models.TransientModel):
    _name = 'update.totals.mobile.wizard'
    _description = 'Wizard Mettre à jour les totaux Mobile'

    balance_id = fields.Many2one('account.daily.balance.mobile', string='Balance liée')
    recette = fields.Float(string="Montant RECETTE", required=True)
    libelle = fields.Char(string='Libellé', default='RECETTE')
    def action_confirm(self):
        self.ensure_one()
        if not self.balance_id:
            raise UserError(_("Aucune balance n'est liée au wizard."))

        if self.recette <= 0:
            raise UserError(_("Veuillez saisir un montant supérieur à 0."))

        current_year = datetime.now().year

        last_line = self.env['account.daily.balance.mobile.line'].search([
            ('reference', 'like', f"REC-MM/{current_year}/%"),
            ('company_id', '=', self.balance_id.company_id.id),
        ], order="reference desc", limit=1)

        if last_line:
            try:
                last_number = int(last_line.reference.split('/')[-1])
            except Exception:
                last_number = 0
            new_number = last_number + 1
        else:
            new_number = 1

        new_ref = "REC-MM/%s/%05d" % (current_year, new_number)

        self.env['account.daily.balance.mobile.line'].create({
            'balance_id': self.balance_id.id,
            'reference': new_ref,
            'categorie': "DEPOT",
            'libelle': self.libelle,
            'payment': 'mobile',
            'debit': 0.0,
            'credit': self.recette,
        })

        # Recalculer
        self.balance_id.action_update_totals_mobile()
        return {'type': 'ir.actions.act_window_close'}


# -------------------------
# Lignes Mobile
# -------------------------
class AccountDailyBalanceMobileLine(models.Model):
    _name = 'account.daily.balance.mobile.line'
    _description = 'Ligne du journal de trésorerie'
    _order = 'id asc'
    _rec_name = 'reference'
    _check_company_auto = True

    balance_id = fields.Many2one(
        'account.daily.balance.mobile',
        string='Balance',
        ondelete='cascade',
        required=True,
        check_company=True,
    )
    operator_id = fields.Many2one(
        'mobile.money.operator',
        string='Journal de trésorerie',
        related='balance_id.operator_id',
        store=True,
        readonly=True,
    )
    reference = fields.Char(string='REFERENCE FACTURE')
    libelle = fields.Char(string='LIBELLE')
    payment = fields.Char(string='PAYMENT')
    debit = fields.Float(string='DÉCAISSEMENT')
    credit = fields.Float(string='ENCAISSEMENT')
    regule_badge = fields.Char(string="Badge", compute="_compute_regule_badge", store=True)
    origin_line_id = fields.Many2one(
        'account.daily.balance.mobile.line',
        string="Ligne d'origine",
        readonly=True,
        check_company=True,
    )
    expense_id = fields.Many2one('hr.expense', string='Dépense RH', readonly=True, check_company=True)
    categorie = fields.Char(string="Catégorie")
    payment_id = fields.Many2one(
        'account.payment', string='Paiement comptable', readonly=True, index=True, check_company=True
    )
    move_id = fields.Many2one(
        'account.move', string='Facture', readonly=True, index=True, check_company=True
    )
    journal_id = fields.Many2one(
        'account.journal', string='Journal', readonly=True, index=True, check_company=True
    )
    payment_date = fields.Date(string='Date du paiement', readonly=True, index=True)
    payment_key = fields.Char(string='Clé anti-doublon', readonly=True, index=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        readonly=True,
    )

    _sql_constraints = [
        ('unique_payment', 'unique(payment_id)', 'Ce paiement existe déjà dans une balance Mobile Money.'),
        (
            'unique_payment_key_company',
            'unique(payment_key, company_id)',
            'Cette opération existe déjà dans une balance Mobile Money.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            balance = self.env['account.daily.balance.mobile'].browse(vals.get('balance_id')).exists()
            if balance:
                vals['company_id'] = balance.company_id.id
            normalized_vals_list.append(vals)
        return super().create(normalized_vals_list)

    def write(self, vals):
        if vals.get('balance_id'):
            balance = self.env['account.daily.balance.mobile'].browse(vals['balance_id']).exists()
            if balance:
                vals = dict(vals, company_id=balance.company_id.id)
        return super().write(vals)

    @api.model
    def _payment_key(self, move, payment):
        return '%s:%s:%s:%s' % (
            move.id,
            payment.journal_id.id,
            payment.amount,
            payment.date,
        )

    @api.model
    def _upsert_invoice_payment(self, balance, move, payment):
        expense = payment.move_id.line_ids.expense_id[:1] or move.line_ids.expense_id[:1]
        if expense:
            return self._upsert_hr_expense_payment(balance, expense, payment)

        payment_key = False if payment.id else self._payment_key(move, payment)
        existing = self.search([('payment_id', '=', payment.id)], limit=1)
        if not existing and payment_key:
            existing = self.search([
                ('payment_key', '=', payment_key),
                ('company_id', '=', balance.company_id.id),
            ], limit=1)
        if not existing:
            legacy_lines = self.search([
                ('balance_id', '=', balance.id),
                ('reference', '=', move.name),
                ('payment_id', '=', False),
                ('move_id', '=', False),
            ])
            existing = legacy_lines[:1]
            if len(legacy_lines) > 1:
                legacy_lines[1:].unlink()

        amount = abs(payment.amount_company_currency_signed or payment.amount)
        vals = {
            'balance_id': balance.id,
            'reference': payment.name or move.name,
            'categorie': 'FACTURE CLIENT' if move.move_type == 'out_invoice' else 'FACTURE FOURNISSEUR',
            'libelle': getattr(move, 'journal_label', False) or move.name,
            'payment': 'mobile',
            'debit': amount if move.move_type == 'in_invoice' else 0.0,
            'credit': amount if move.move_type == 'out_invoice' else 0.0,
            'payment_id': payment.id,
            'move_id': move.id,
            'journal_id': payment.journal_id.id,
            'payment_date': payment.date,
            'payment_key': payment_key,
        }
        if existing:
            if existing.balance_id.etats == 'ouvert':
                existing.write(vals)
            return existing
        return self.create(vals)

    @api.model
    def _upsert_hr_expense_payment(self, balance, expense, payment):
        existing = self.search([('payment_id', '=', payment.id)], limit=1)
        if not existing:
            existing = self.search([
                ('expense_id', '=', expense.id),
                ('company_id', '=', balance.company_id.id),
            ], limit=1)

        amount = abs(payment.amount_company_currency_signed or payment.amount)
        vals = {
            'balance_id': balance.id,
            'expense_id': expense.id,
            'reference': payment.name,
            'categorie': expense.product_id.name or 'DÉPENSE RH',
            'libelle': expense.name,
            'payment': 'mobile',
            'debit': amount,
            'credit': 0.0,
            'payment_id': payment.id,
            'move_id': payment.move_id.id,
            'journal_id': payment.journal_id.id,
            'payment_date': payment.date,
            'payment_key': False,
        }
        if existing:
            if existing.balance_id.etats == 'ouvert':
                existing.write(vals)
            return existing
        return self.create(vals)

    @api.depends('balance_id.line_ids.origin_line_id', 'balance_id.line_ids.libelle')
    def _compute_regule_badge(self):
        for line in self:
            if line.libelle == 'REGULE':
                line.regule_badge = ''
                continue

            regulated = self.env['account.daily.balance.mobile.line'].search_count([
                ('origin_line_id', '=', line.id),
                ('libelle', '=', 'REGULE'),
                ('company_id', '=', line.company_id.id),
            ])
            line.regule_badge = "REGULE" if regulated >= 1 else ""


# -------------------------
# Init wizard Mobile
# -------------------------
class AccountDailyBalanceMobileInitWizard(models.TransientModel):
    _name = 'account.daily.balance.mobile.init.wizard'
    _description = 'Wizard pour initialiser le solde Mobile'

    balance_id = fields.Many2one('account.daily.balance.mobile', string='Balance liée')
    initial_balance = fields.Float(string='Solde initial', required=True)

    def action_confirm(self):
        if not self.balance_id:
            raise UserError(_("Aucune balance liée au wizard."))
        self.balance_id.ancien_solde = self.initial_balance
        self.balance_id.action_update_totals_mobile()
        return {'type': 'ir.actions.act_window_close'}


# -------------------------
# Wizard Régule Mobile
# -------------------------
class ReguleMobileWizard(models.TransientModel):
    _name = 'regule.mobile.wizard'
    _description = "Wizard Regule Mobile"

    balance_id = fields.Many2one('account.daily.balance.mobile', string="Balance", required=True)
    reference_id = fields.Many2one('account.daily.balance.mobile.line', string="Référence", required=True)
    montant = fields.Float(string="Montant", readonly=True, store=True)
    company_id = fields.Many2one('res.company', string="Société",
                                 related='balance_id.company_id', store=True, readonly=True)

    @api.onchange('balance_id')
    def _onchange_balance_id(self):
        if not self.balance_id:
            return {}
        reguled_refs = self.balance_id.line_ids.filtered(lambda l: l.libelle == 'REGULE').mapped('reference')
        return {
            'domain': {
                'reference_id': [
                    ('balance_id', '=', self.balance_id.id),
                    ('company_id', '=', self.balance_id.company_id.id),
                    ('libelle', '!=', 'REGULE'),
                    ('reference', 'not in', reguled_refs)
                ]
            }
        }

    @api.onchange('reference_id')
    def _onchange_reference_id(self):
        if self.reference_id:
            self.montant = abs(self.reference_id.debit or self.reference_id.credit or 0)

    def action_confirm_regule(self):
        self.ensure_one()
        if self.reference_id.libelle == 'REGULE':
            raise UserError(_("Impossible de réguler une ligne REGULE."))

        if self.balance_id.etats == 'cloturer':
            raise UserError(_("Journal déjà clôturé, régulation impossible."))

        regule_count = self.env['account.daily.balance.mobile.line'].search_count([
            ('balance_id', '=', self.balance_id.id),
            ('reference', '=', self.reference_id.reference),
            ('libelle', '=', 'REGULE'),
            ('company_id', '=', self.balance_id.company_id.id),
        ])
        if regule_count >= 1:
            raise UserError(_("Cette référence a déjà été régulée, opération impossible."))

        montant = abs(self.reference_id.debit or self.reference_id.credit or 0)
        if self.reference_id.credit > 0:
            debit = montant
            credit = 0.0
        else:
            debit = 0.0
            credit = montant

        # Création ligne REGULE
        self.env['account.daily.balance.mobile.line'].create({
            'balance_id': self.balance_id.id,
            'reference': self.reference_id.reference,
            'libelle': 'REGULE',
            'payment': self.reference_id.payment,
            'debit': debit,
            'credit': credit,
            'origin_line_id': self.reference_id.id,
        })

        # Annulation facture/paiement/dépense si trouvée
        invoice = self.env['account.move'].search([
            ('name', '=', self.reference_id.reference),
            ('company_id', '=', self.balance_id.company_id.id),
        ], limit=1)
        if invoice and invoice.state not in ('cancel'):
            try:
                invoice.button_cancel()
            except Exception:
                pass
        else:
            payment = self.env['account.payment'].search([
                ('name', '=', self.reference_id.reference),
                ('company_id', '=', self.balance_id.company_id.id),
            ], limit=1)
            if payment and payment.state != 'cancelled':
                try:
                    payment.action_cancel()
                except Exception:
                    pass

            expense = self.env['hr.expense.sheet'].search([
                ('name', '=', self.reference_id.reference),
                ('company_id', '=', self.balance_id.company_id.id)
            ], limit=1)
            if expense and expense.payment_state != 'reversed':
                expense.write({'payment_state': 'reversed'})

        # Mise à jour totaux
        self.balance_id.action_update_totals_mobile()
        return {'type': 'ir.actions.act_window_close'}


class RetraitWizard(models.TransientModel):
    _name = "retrait.wizard"
    _description = "Wizard Retrait Mobile Money"

    reference = fields.Char(string="Référence", readonly=True)
    motif = fields.Char(string="Motif", required=True)
    montant = fields.Float(string="Montant", required=True)
    balance_id = fields.Many2one(
        'account.daily.balance.mobile',
        string='Balance Mobile Money',
        required=True,
        domain="[('company_id', '=', company_id), ('etats', '=', 'ouvert')]",
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='balance_id.company_id',
        readonly=True,
    )

    def _generate_reference(self, company_id=None):
        current_year = datetime.now().year
        prefix = f"RET/{current_year}/"
        company_id = company_id or self.env.company.id

        last_line = self.env["account.daily.balance.mobile.line"].search(
            [("reference", "like", prefix + "%"), ("company_id", "=", company_id)],
            order="id desc",
            limit=1
        )

        if last_line:
            last_number = int(last_line.reference.split("/")[-1])
            new_number = last_number + 1
        else:
            new_number = 1

        return prefix + str(new_number).zfill(5)

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        balance_id = res.get("balance_id") or self.env.context.get("default_balance_id")
        balance = self.env["account.daily.balance.mobile"].browse(balance_id).exists()
        res["reference"] = self._generate_reference(
            balance.company_id.id if balance else self.env.company.id
        )
        return res

    def action_confirm_retrait(self):
        balance_obj = self.balance_id

        # Vérification du solde
        if self.montant > balance_obj.nouveau_solde:
            raise UserError(_("Solde mobile money insuffisant."))

        # Enregistrement de la ligne de retrait
        line_vals = {
            "balance_id": balance_obj.id,
            "reference": self.reference,
            "libelle": self.motif,
            "categorie": "RETRAIT",
            "payment": "mobile",
            "debit": self.montant,
            "credit": 0.0,
            "regule_badge": "",
        }

        self.env["account.daily.balance.mobile.line"].create(line_vals)

        # Mise à jour du solde
        balance_obj.action_update_totals_mobile()

        return {"type": "ir.actions.act_window_close"}
