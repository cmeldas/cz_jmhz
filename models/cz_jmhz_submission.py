# -*- coding: utf-8 -*-
import base64

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..lib import xsd

SUBMISSION_STATES = [
    ("invalid", "Neprošlo XSD"),
    ("ready", "Připraveno k podání"),
    ("sent", "Podáno"),
    ("accepted", "Přijato"),
    ("rejected", "Zamítnuto"),
    ("superseded", "Nahrazeno"),
]


class CzJmhzSubmission(models.Model):
    _name = "cz.jmhz.submission"
    _description = "Podání ČSSZ (JMHZ)"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char("Podání", required=True)
    company_id = fields.Many2one("res.company", "Firma", required=True, default=lambda self: self.env.company)
    kind = fields.Selection(
        [("mh", "Měsíční hlášení"), ("regzec", "Registrace zaměstnance")], "Druh", required=True)
    report_id = fields.Many2one("cz.jmhz.report", "Hlášení", ondelete="cascade", index=True)
    employment_id = fields.Many2one("cz.jmhz.employment", "Dohoda", ondelete="cascade", index=True)
    employee_id = fields.Many2one(related="employment_id.employee_id", string="Brigádník")
    regzec_action = fields.Selection(
        [("1", "Přihláška (nástup)"), ("2", "Odhláška (skončení)"), ("3", "Změna údajů"), ("8", "Storno")],
        "Akce")
    submission_type = fields.Selection([("R", "Řádné"), ("O", "Opravné")], "Typ podání")
    guid = fields.Char("GUID podání", readonly=True)
    xml_file = fields.Binary("XML", attachment=True, readonly=True)
    xml_filename = fields.Char("Soubor")
    xsd_version = fields.Char("Verze XSD", readonly=True)
    xsd_errors = fields.Text("Chyby XSD", readonly=True)
    state = fields.Selection(SUBMISSION_STATES, "Stav", required=True, default="ready", tracking=True)
    sent_date = fields.Datetime("Podáno", readonly=True)
    response_file = fields.Binary("Protokol ČSSZ", attachment=True)
    response_filename = fields.Char("Název protokolu")
    note = fields.Text("Poznámka")

    @api.model
    def _product_version(self) -> str:
        module = self.env["ir.module.module"].sudo().search([("name", "=", "cz_jmhz")], limit=1)
        return module.latest_version or ""

    @api.model
    def _create_from_xml(self, vals: dict, xml: bytes):
        kind = "jmhz" if vals["kind"] == "mh" else "regzec"
        errors = xsd.validate(kind, xml)
        return self.create({
            **vals,
            "xml_file": base64.b64encode(xml),
            "xsd_version": xsd.default_version(kind),
            "xsd_errors": "\n".join(errors) or False,
            "state": "invalid" if errors else "ready",
        })

    def action_download(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/cz.jmhz.submission/{self.id}/xml_file/{self.xml_filename}?download=true",
            "target": "self",
        }

    def action_mark_sent(self):
        for submission in self:
            if submission.state != "ready":
                raise UserError("Jako podané lze označit jen podání, které prošlo kontrolou XSD a čeká na podání.")
            submission.write({"state": "sent", "sent_date": fields.Datetime.now()})
            if submission.report_id:
                submission.report_id._on_submission_sent(submission)
            if submission.employment_id:
                submission.employment_id._on_submission_sent(submission.regzec_action)

    def action_mark_accepted(self):
        for submission in self:
            if submission.state != "sent":
                raise UserError("Jako přijaté lze označit jen podané podání.")
            submission.state = "accepted"
            if submission.report_id:
                submission.report_id._on_submission_accepted(submission)
            if submission.employment_id:
                submission.employment_id._on_submission_accepted(submission.regzec_action)

    def action_mark_rejected(self):
        for submission in self:
            if submission.state != "sent":
                raise UserError("Jako zamítnuté lze označit jen podané podání.")
            submission.state = "rejected"
            if submission.report_id:
                submission.report_id._on_submission_rejected(submission)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_sent(self):
        if any(submission.state in ("sent", "accepted") for submission in self):
            raise UserError("Podané podání nejde smazat, je to doklad o splnění povinnosti.")
