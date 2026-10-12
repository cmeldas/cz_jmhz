# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    jmhz_variable_symbol = fields.Char(related="company_id.jmhz_variable_symbol", readonly=False)
    jmhz_ossz_code = fields.Char(related="company_id.jmhz_ossz_code", readonly=False)
    jmhz_employer_name = fields.Char(related="company_id.jmhz_employer_name", readonly=False)
    jmhz_work_city = fields.Char(related="company_id.jmhz_work_city", readonly=False)
    jmhz_work_city_code = fields.Char(related="company_id.jmhz_work_city_code", readonly=False)
    jmhz_notification_email = fields.Char(related="company_id.jmhz_notification_email", readonly=False)
    jmhz_responsible_user_id = fields.Many2one(related="company_id.jmhz_responsible_user_id", readonly=False)
    jmhz_live_mode = fields.Boolean(related="company_id.jmhz_live_mode", readonly=False)
