# -*- coding: utf-8 -*-
"""Outil unique de traçabilité dans le chatter : mf.trace.

Chaque trace est une NOTE INTERNE (sous-type « note », aucune notification, aucun e-mail, aucun abonné ajouté) en HTML
structuré : titre court, liste de détails (valeurs avant/après, montants en Ariary entiers, comptes, journaux, pièces)
et liens cliquables vers les enregistrements liés.

  self.env['mf.trace'].mf_trace(record, titre, details=[(libellé, valeur), ...], liens=[enregistrement, ...])
  self.env['mf.trace'].mf_trace_batch([(record, titre, details, liens), ...])   # un seul INSERT par modèle

La trace est posée en sudo (seul le message l'est : les droits de l'utilisateur ne changent pas), ce qui permet de
l'écrire sur une pièce d'une autre société que la sienne. Un échec de trace n'annule JAMAIS l'opération comptable :
il est journalisé (warning, avec l'identifiant de l'enregistrement) et l'opération continue (décorateur mf_safe).
"""
import functools
import logging

from markupsafe import Markup

from odoo import api, models

_logger = logging.getLogger(__name__)

# Au-delà, les messages par pièce d'une même opération sont omis (la synthèse, elle, reste posée).
MAX_PIECES = 500
TRACE_CLASS = 'o_mf_trace'


def mf_amount(value):
    """Montant en Ariary entiers, séparateur de milliers insécable : « 40 000 000 Ar »."""
    return '{:,}'.format(int(round(value or 0.0))).replace(',', ' ') + ' Ar'


def mf_link(record, label=None):
    """Lien cliquable du chatter vers un enregistrement (lecture du nom en sudo)."""
    record = record.sudo()
    return Markup('<a href="#" data-oe-model="%s" data-oe-id="%s">%s</a>') % (
        record._name, record.id, label or record.display_name)


def mf_selection_label(record, field_name):
    """Libellé affiché de la valeur d'un champ Selection."""
    field = record._fields[field_name]
    value = record[field_name]
    return dict(field._description_selection(record.env)).get(value, value) if value else False


def _render_value(value):
    if isinstance(value, (list, tuple)):
        return Markup('<ul>%s</ul>') % Markup('').join(Markup('<li>%s</li>') % _render_value(v) for v in value)
    return Markup('%s') % value


def _render(titre, details, liens):
    parts = [Markup('<p><strong>%s</strong></p>') % titre]
    items = [(key, value) for key, value in (details or []) if value is not None and value is not False and value != '']
    if items:
        parts.append(Markup('<ul>%s</ul>') % Markup('').join(
            Markup('<li><strong>%s</strong> : %s</li>') % (key, _render_value(value)) for key, value in items))
    links = [mf_link(rec) if hasattr(rec, '_name') else Markup('%s') % rec for rec in (liens or [])]
    if links:
        parts.append(Markup('<p>%s</p>') % Markup(' · ').join(links))
    return Markup('<div class="%s">%s</div>') % (TRACE_CLASS, Markup('').join(parts))


def mf_safe(func):
    """Isole une méthode de trace : savepoint, et toute erreur est journalisée (warning) puis ignorée. Les écritures en
    attente sont vidées AVANT le savepoint : un retour arrière ne peut donc jamais emporter autre chose que la trace."""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        self.env.flush_all()
        try:
            with self.env.cr.savepoint():
                return func(self, *args, **kwargs)
        except Exception:  # noqa: BLE001 - une trace ne bloque jamais l'opération
            _logger.warning("Trace du chatter ignorée (%s sur %s%s)", func.__name__, self._name, self.ids, exc_info=True)
            return None
    return wrapper


class MfTrace(models.AbstractModel):
    _name = 'mf.trace'
    _description = "Traces détaillées du chatter (notes internes)"

    @api.model
    def mf_trace(self, record, titre, details=None, liens=None):
        """Une note interne sur `record`. Retourne True si elle a été posée."""
        return self.mf_trace_batch([(record, titre, details, liens)])

    @api.model
    def mf_trace_batch(self, entries):
        """Plusieurs notes d'un coup : [(enregistrement, titre, détails, liens)]. Un seul INSERT par modèle, jamais une
        boucle de message_post. Au-delà de MAX_PIECES notes, aucune n'est posée (l'appelant a sa synthèse)."""
        entries = [entry for entry in entries if entry[0]]
        if not entries:
            return False
        if len(entries) > MAX_PIECES:
            _logger.warning("mf_trace: %s notes demandées, plafond %s : aucune note par pièce n'est posée.",
                            len(entries), MAX_PIECES)
            return False
        self.env.flush_all()
        try:
            with self.env.cr.savepoint():
                bodies = {}
                for record, titre, details, liens in entries:
                    record = record.sudo()
                    if not hasattr(record, '_message_log_batch'):
                        continue
                    body = _render(titre, details, liens)
                    per_model = bodies.setdefault(record._name, {})
                    per_model[record.id] = per_model[record.id] + body if record.id in per_model else body
                for model, per_model in bodies.items():
                    self.env[model].sudo().browse(list(per_model))._message_log_batch(per_model, message_type='comment')
        except Exception:  # noqa: BLE001
            _logger.warning("mf_trace: échec de la trace sur %s", [(r._name, r.ids) for r, *_rest in entries],
                            exc_info=True)
            return False
        return True
