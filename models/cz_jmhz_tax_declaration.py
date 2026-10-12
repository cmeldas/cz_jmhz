# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CzJmhzTaxDeclaration(models.Model):
    _name = "cz.jmhz.tax.declaration"
    _description = "Prohlášení poplatníka daně z příjmů ze závislé činnosti"
    _order = "date_from desc, id desc"

    employee_id = fields.Many2one("hr.employee", "Brigádník", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one(related="employee_id.company_id", store=True)
    date_from = fields.Date(
        "Platí od", required=True,
        help="Prohlášení platí pro celý měsíc, ve kterém bylo podepsáno, a pro další měsíce až do odvolání.")
    date_to = fields.Date("Platí do", help="Prázdné = do odvolání.")
    document = fields.Binary("Podepsané prohlášení", attachment=True)
    document_name = fields.Char("Název souboru")
    note = fields.Text("Poznámka")

    @api.constrains("date_from", "date_to", "employee_id")
    def _check_dates(self):
        for declaration in self:
            if declaration.date_to and declaration.date_to < declaration.date_from:
                raise ValidationError("Konec platnosti prohlášení je před jeho začátkem.")
            overlapping = self.search_count([
                ("id", "!=", declaration.id),
                ("employee_id", "=", declaration.employee_id.id),
                ("date_from", "<=", declaration.date_to or "9999-12-31"),
                "|", ("date_to", "=", False), ("date_to", ">=", declaration.date_from),
            ])
            if overlapping:
                raise ValidationError("Prohlášení poplatníka se u jednoho brigádníka nesmí časově překrývat.")

    @api.model
    def _covers(self, employee, first_day, last_day) -> bool:
        """Platí v měsíci [first_day, last_day] prohlášení poplatníka?"""
        return bool(self.search_count([
            ("employee_id", "=", employee.id),
            ("date_from", "<=", last_day),
            "|", ("date_to", "=", False), ("date_to", ">=", first_day),
        ]))
