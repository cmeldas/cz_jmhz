# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ReportPayrollRecord(models.AbstractModel):
    _name = "report.cz_jmhz.report_payroll_record"
    _description = "Mzdový list brigádníka"

    @api.model
    def _get_report_values(self, docids, data=None):
        year = int((data or {}).get("year") or fields.Date.context_today(self).year)
        employees = self.env["hr.employee"].browse(docids)
        lines = self.env["cz.jmhz.report.line"].search([
            ("employee_id", "in", employees.ids),
            ("period", ">=", f"{year}-01-01"),
            ("period", "<=", f"{year}-12-31"),
        ], order="period, id")
        return {
            "doc_ids": employees.ids,
            "doc_model": "hr.employee",
            "docs": employees.sudo(),
            "year": year,
            "lines_by_employee": {employee.id: lines.filtered(lambda line: line.employee_id == employee)
                                  for employee in employees},
        }
