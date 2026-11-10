"""The extra intermediates: still verified, still in date, and on every client that reads a model-supplied URL."""

import ssl
from datetime import UTC, datetime, timedelta

import certifi
from cryptography import x509

from app.core.egress import INTERMEDIATES, TRUST, guarded_client


def certs() -> list[x509.Certificate]:
    return x509.load_pem_x509_certificates(INTERMEDIATES.read_bytes())


def test_verification_stays_on():
    assert TRUST.verify_mode == ssl.CERT_REQUIRED and TRUST.check_hostname


def test_each_is_an_intermediate_not_a_root():
    for cert in certs():
        assert cert.issuer != cert.subject
        assert cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca


def test_each_is_in_date_for_a_year_more():
    soon = datetime.now(UTC) + timedelta(days=365)
    assert all(cert.not_valid_after_utc > soon for cert in certs())


def test_its_root_is_already_trusted():
    roots = ssl.create_default_context(cafile=certifi.where()).get_ca_certs()
    trusted = {frozenset(pair for rdn in root["subject"] for pair in rdn) for root in roots}
    assert all(frozenset((a.oid._name, a.value) for a in cert.issuer) in trusted for cert in certs())


def test_the_shared_client_uses_it():
    assert guarded_client()._transport._pool._ssl_context is TRUST


def test_the_research_readers_client_uses_it():
    from app.ingest.tools.research_tools import _client

    assert _client("https://censusindia.gov.in/")._transport._pool._ssl_context is TRUST
