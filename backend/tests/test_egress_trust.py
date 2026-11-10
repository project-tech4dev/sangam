"""The extra intermediates: still verified, still in date, and on every client that reads a model-supplied URL."""

import ssl
from datetime import UTC, datetime, timedelta

import certifi
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.core.egress import INTERMEDIATES, TRUST, guarded_client, trust


def certs() -> list[x509.Certificate]:
    pem = INTERMEDIATES.read_bytes()
    return x509.load_pem_x509_certificates(pem) if b"BEGIN CERTIFICATE" in pem else []


def a_ca_pem() -> bytes:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Sangam Test CA")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


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


def test_a_bundle_with_no_certificate_loads(tmp_path):
    empty = tmp_path / "intermediates.pem"
    empty.write_text("# no intermediates\n")
    assert len(trust(empty).get_ca_certs()) == len(
        ssl.create_default_context(cafile=certifi.where()).get_ca_certs()
    )


def test_a_certificate_in_the_bundle_is_trusted(tmp_path):
    bundle = tmp_path / "intermediates.pem"
    bundle.write_bytes(b"# a site's intermediate\n" + a_ca_pem())
    subjects = {
        dict(pair for rdn in c["subject"] for pair in rdn).get("commonName")
        for c in trust(bundle).get_ca_certs()
    }
    assert "Sangam Test CA" in subjects


def test_no_emsign_certificate_is_trusted():
    assert not any("emSign" in str(cert.subject) or "emSign" in str(cert.issuer) for cert in certs())


def test_the_shared_client_uses_it():
    assert guarded_client()._transport._pool._ssl_context is TRUST


def test_the_research_readers_client_uses_it():
    from app.ingest.tools.research_tools import _client

    assert _client("https://example.gov.in/")._transport._pool._ssl_context is TRUST
