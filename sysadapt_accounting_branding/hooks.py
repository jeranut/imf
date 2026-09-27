ICON = 'sysadapt_accounting_branding,static/description/icon.png'
NAME = 'Comptabilité'


def post_init_hook(env):
    """Force le nom dans toutes les langues et recalcule l'icône du menu racine.

    ``name`` est traduisible : le XML n'écrit que la valeur en_US, alors que
    les traductions d'origine (fr_FR, fr_BE : « Facturation ») subsistent.
    """
    menu = env.ref('account.menu_finance')
    langs = {'en_US', 'fr_FR'} | {code for code, _name in env['res.lang'].get_installed()}
    for lang in sorted(langs):
        menu.with_context(lang=lang).write({'name': NAME})
    # réécrire web_icon recalcule web_icon_data (voir ir.ui.menu.write)
    menu.write({'web_icon': ICON})
    env.registry.clear_cache()
    env['ir.ui.menu'].clear_caches()
