from __future__ import annotations

from app.services.sms_service import render_template


def test_render_template_all_variables():
    template = "Hi <first_name> <last_name>, we help <company_name> (<title>) at <website>."
    contact = {
        "first_name": "John",
        "last_name": "Smith",
        "company_name": "ACME Corp",
        "title": "COO",
        "website": "https://acme.com",
    }
    result = render_template(template, contact)
    assert result == "Hi John Smith, we help ACME Corp (COO) at https://acme.com."


def test_render_template_missing_values():
    template = "Hi <first_name>, this is Hexa. We'd love to help <company_name>."
    contact = {
        "first_name": "Jane",
        "company_name": "",
    }
    result = render_template(template, contact)
    assert result == "Hi Jane, this is Hexa. We'd love to help ."


def test_render_template_no_placeholders():
    template = "Hello, this is a static message."
    result = render_template(template, {})
    assert result == "Hello, this is a static message."
