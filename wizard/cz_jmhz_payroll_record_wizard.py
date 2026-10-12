# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CzJmhzPayrollRecordWizard(models.TransientModel):
    _name = "cz.jmhz.payroll.record.wizard"
    _description = "Mzdový list – výběr roku"

    year = fields.Integer("Rok", required=True, default=lambda self: fields.Date.context_today(self).year)
    employee_ids = fields.Many2many("hr.employee", string="Brigádníci", required=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if self.env.context.get("active_model") == "hr.employee" and "employee_ids" in fields_list:
            values["employee_ids"] = [(6, 0, self.env.context.get("active_ids", []))]
        return values

    def action_print(self):
        self.ensure_one()
        return self.env.ref("cz_jmhz.action_report_payroll_record").report_action(
            self.employee_ids, data={"year": self.year})
