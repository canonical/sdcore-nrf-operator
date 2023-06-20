#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed operator for the SD-Core NRF service."""

import logging
from ipaddress import IPv4Address
from subprocess import check_output
from typing import Optional

from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires  # type: ignore[import]
from charms.observability_libs.v1.kubernetes_service_patch import (  # type: ignore[import]
    KubernetesServicePatch,
)
from charms.sdcore_nrf.v0.fiveg_nrf import NRFProvides  # type: ignore[import]
from charms.tls_certificates_interface.v2.tls_certificates import (  # type: ignore[import]
    CertificateAvailableEvent,
    CertificateExpiringEvent,
    TLSCertificatesRequiresV2,
    generate_csr,
    generate_private_key,
)
from jinja2 import Environment, FileSystemLoader  # type: ignore[import]
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase, EventBase, RelationJoinedEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, ModelError, WaitingStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)

BASE_CONFIG_PATH = "/etc/nrf"
CONFIG_FILE_NAME = "nrfcfg.yaml"
DATABASE_NAME = "free5gc"
NRF_SBI_PORT = 29510
DATABASE_RELATION_NAME = "database"
NRF_RELATION_NAME = "fiveg-nrf"
CERTS_DIR_PATH = "/free5gc/support/TLS"  # Certificate paths are hardcoded in NRF code
PRIVATE_KEY_NAME = "nrf.key"
CSR_NAME = "nrf.csr"
CERTIFICATE_NAME = "nrf.pem"
CERTIFICATE_COMMON_NAME = "nrf.sdcore"


def _get_pod_ip() -> Optional[str]:
    """Returns the pod IP using juju client.

    Returns:
        str: The pod IP.
    """
    ip_address = check_output(["unit-get", "private-address"])
    return str(IPv4Address(ip_address.decode().strip())) if ip_address else None


def _render_config(
    database_name: str,
    database_url: str,
    nrf_ip: str,
    nrf_sbi_port: int,
    scheme: str,
) -> str:
    """Renders the nrfcfg config file.

    Args:
        database_name: Name of the database
        database_url: URL of the database
        nrf_ip: IP of the NRF service
        nrf_sbi_port: Port of the NRF service
        scheme: SBI interface scheme ("http" or "https")

    Returns:
        str: Rendered config file content
    """
    jinja2_environment = Environment(loader=FileSystemLoader("src/templates/"))
    template = jinja2_environment.get_template("nrfcfg.yaml.j2")
    content = template.render(
        database_name=database_name,
        database_url=database_url,
        nrf_sbi_port=nrf_sbi_port,
        nrf_ip=nrf_ip,
        scheme=scheme,
    )
    return content


class NRFOperatorCharm(CharmBase):
    """Main class to describe juju event handling for the SD-Core NRF operator."""

    def __init__(self, *args):
        """Initialize charm."""
        super().__init__(*args)
        self._container_name = self._service_name = "nrf"
        self._container = self.unit.get_container(self._container_name)
        self._database = DatabaseRequires(
            self, relation_name=DATABASE_RELATION_NAME, database_name=DATABASE_NAME
        )
        self.nrf_provider = NRFProvides(self, NRF_RELATION_NAME)
        self._certificates = TLSCertificatesRequiresV2(self, "certificates")

        self._service_patcher = KubernetesServicePatch(
            charm=self,
            ports=[
                ServicePort(name="sbi", port=NRF_SBI_PORT),
            ],
        )
        self.framework.observe(self.on.database_relation_joined, self._configure_nrf)
        self.framework.observe(self.on.nrf_pebble_ready, self._configure_nrf)
        self.framework.observe(self._database.on.database_created, self._configure_nrf)
        self.framework.observe(
            self.on.fiveg_nrf_relation_joined, self._on_fiveg_nrf_relation_joined
        )
        self.framework.observe(
            self.on.certificates_relation_created, self._on_certificates_relation_created
        )
        self.framework.observe(
            self.on.certificates_relation_joined, self._on_certificates_relation_joined
        )
        self.framework.observe(
            self.on.certificates_relation_broken, self._on_certificates_relation_broken
        )
        self.framework.observe(
            self._certificates.on.certificate_available, self._on_certificate_available
        )
        self.framework.observe(
            self._certificates.on.certificate_expiring, self._on_certificate_expiring
        )

    def _configure_nrf(self, event: EventBase) -> None:
        """Adds pebble layer and manages Juju unit status.

        Args:
            event: Juju event
        """
        if not self._container.can_connect():
            self.unit.status = WaitingStatus("Waiting for container to be ready")
            event.defer()
            return
        if not self._relation_created(DATABASE_RELATION_NAME):
            self.unit.status = BlockedStatus("Waiting for database relation to be created")
            return
        if not self._database_is_available():
            self.unit.status = WaitingStatus("Waiting for the database to be available")
            return
        if not self._get_database_uri():
            self.unit.status = WaitingStatus("Waiting for database URI")
            event.defer()
            return
        if not self._container.exists(path=BASE_CONFIG_PATH):
            self.unit.status = WaitingStatus("Waiting for storage to be attached")
            event.defer()
            return
        if not _get_pod_ip():
            self.unit.status = WaitingStatus("Waiting for pod IP address to be available")
            event.defer()
            return
        needs_restart = self._generate_config_file()
        self._configure_workload(restart=needs_restart)
        self._publish_nrf_info_for_all_requirers()
        self.unit.status = ActiveStatus()

    def _on_certificates_relation_created(self, EventBase) -> None:
        """Generates Private key."""
        if not self.unit.is_leader():
            return
        if not self._container.can_connect():
            event.defer()
            return
        self._generate_private_key()

    def _on_certificates_relation_broken(self, EventBase) -> None:
        """Deletes TLS related artifacts and reconfigures workload."""
        if not self.unit.is_leader():
            return
        if not self._container.can_connect():
            event.defer()
            return
        self._delete_private_key()
        self._delete_csr()
        self._delete_certificate()
        self._configure_nrf(event)

    def _on_certificates_relation_joined(self, EventBase) -> None:
        """Generates CSR and requests new certificate."""
        if not self.unit.is_leader():
            return
        if not self._container.can_connect():
            event.defer()
            return
        if not self._private_key_is_stored():
            event.defer()
            return
        self._request_new_certificate()

    def _on_certificate_available(self, event: CertificateAvailableEvent) -> None:
        """Pushes certificate to workload and configures workload."""
        if not self.unit.is_leader():
            return
        if not self._container.can_connect():
            event.defer()
            return
        if not self._csr_is_stored():
            logger.warning("Certificate is available but no CSR is stored")
            return
        if event.certificate_signing_request != self._get_stored_csr():
            logger.debug("Stored CSR doesn't match one in certificate available event")
            return
        self._store_certificate(event.certificate)
        self._configure_nrf(event)

    def _on_certificate_expiring(self, event: CertificateExpiringEvent) -> None:
        """Requests new certificate."""
        if not self.unit.is_leader():
            return
        if not self._container.can_connect():
            event.defer()
            return
        if event.certificate != self._get_stored_certificate():
            logger.debug("Expiring certificate is not the one stored")
            return
        self._request_new_certificate()

    def _generate_private_key(self) -> None:
        """Generates and stores private key."""
        private_key = generate_private_key()
        self._store_private_key(private_key.decode())

    def _request_new_certificate(self) -> None:
        """Generates and stores CSR, and uses to request new certificate."""
        private_key = self._get_stored_private_key()
        csr = generate_csr(
            private_key=private_key.encode(),
            subject=CERTIFICATE_COMMON_NAME,
            sans_dns=[CERTIFICATE_COMMON_NAME],
        )
        self._store_csr(csr.decode().strip())
        self._certificates.request_certificate_creation(certificate_signing_request=csr)

    def _delete_private_key(self):
        """Removes private key from workload."""
        if not self._private_key_is_stored():
            return
        self._container.remove_path(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")
        logger.info("Removed private key from workload")

    def _delete_csr(self):
        """Deletes CSR from workload."""
        if not self._csr_is_stored():
            return
        self._container.remove_path(path=f"{CERTS_DIR_PATH}/{CSR_NAME}")
        logger.info("Removed CSR from workload")

    def _delete_certificate(self):
        """Deletes certificate from workload."""
        if not self._certificate_is_stored():
            return
        self._container.remove_path(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")
        logger.info("Removed certificate from workload")

    def _private_key_is_stored(self) -> bool:
        """Returns whether private key is stored in workload."""
        return self._container.exists(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")

    def _csr_is_stored(self) -> bool:
        """Returns whether CSR is stored in workload."""
        return self._container.exists(path=f"{CERTS_DIR_PATH}/{CSR_NAME}")

    def _get_stored_certificate(self) -> str:
        """Returns stored certificate."""
        return str(self._container.pull(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}").read())

    def _get_stored_csr(self) -> str:
        """Returns stored CSR."""
        return str(self._container.pull(path=f"{CERTS_DIR_PATH}/{CSR_NAME}").read())

    def _get_stored_private_key(self) -> str:
        """Returns stored private key."""
        return str(self._container.pull(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}").read())

    def _certificate_is_stored(self) -> bool:
        """Returns whether certificate is stored in workload."""
        return self._container.exists(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")

    def _store_certificate(self, certificate: str) -> None:
        """Stores certificate in workload."""
        self._container.push(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}", source=certificate)
        logger.info("Pushed certificate pushed to workload")

    def _store_private_key(self, private_key: str) -> None:
        """Stores private key in workload."""
        self._container.push(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}", source=private_key)
        logger.info("Pushed private key to workload")

    def _store_csr(self, csr: str) -> None:
        """Stores CSR in workload."""
        self._container.push(path=f"{CERTS_DIR_PATH}/{CSR_NAME}", source=csr)
        logger.info("Pushed CSR to workload")

    def _generate_config_file(self) -> bool:
        """Handles creation of the NRF config file.

        Generates NRF config file based on a given template.
        Pushes NRF config file to the workload.
        Calls `_configure_workload` function to forcibly restart the NRF service in order
        to fetch new config.

        Returns:
            bool: Whether the config file was updated so the service should be restarted.
        """
        content = _render_config(
            database_url=self._database_info()["uris"].split(",")[0],
            nrf_ip=_get_pod_ip(),  # type: ignore[arg-type]
            database_name=DATABASE_NAME,
            nrf_sbi_port=NRF_SBI_PORT,
            scheme="https" if self._certificate_is_stored() else "http",
        )
        if not self._config_file_content_matches(content=content):
            self._push_config_file(
                content=content,
            )
            return True
        return False

    def _configure_workload(self, restart: bool = False) -> None:
        """Configures pebble layer for the nrf container."""
        plan = self._container.get_plan()
        layer = self._pebble_layer
        if plan.services != layer.services or restart:
            self._container.add_layer("nrf", layer, combine=True)
            self._container.restart(self._service_name)

    def _config_file_content_matches(self, content: str) -> bool:
        """Returns whether the nrfcfg config file content matches the provided content.

        Returns:
            bool: Whether the nrfcfg config file content matches
        """
        if not self._container.exists(path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}"):
            return False
        existing_content = self._container.pull(path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}")
        if existing_content.read() != content:
            return False
        return True

    def _on_fiveg_nrf_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Handle fiveg-nrf relation joined event.

        Args:
            event: RelationJoinedEvent
        """
        if not self.unit.is_leader():
            return
        if not self._nrf_service_is_running():
            return
        nrf_url = self._get_nrf_url()
        self.nrf_provider.set_nrf_information(
            url=nrf_url,
            relation_id=event.relation.id,
        )

    def _publish_nrf_info_for_all_requirers(self) -> None:
        """Publish nrf information in the databags of all relations requiring it."""
        if not self.unit.is_leader():
            return
        if not self._relation_created(NRF_RELATION_NAME):
            return
        nrf_url = self._get_nrf_url()
        self.nrf_provider.set_nrf_information_in_all_relations(nrf_url)

    def _relation_created(self, relation_name: str) -> bool:
        """Returns whether a given Juju relation was crated.

        Args:
            relation_name (str): Relation name

        Returns:
            bool: Whether the relation was created.
        """
        return bool(self.model.relations[relation_name])

    def _push_config_file(self, content: str) -> None:
        """Pushes config file to workload.

        Args:
            content: config file content
        """
        if not self._container.can_connect():
            return
        self._container.push(path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}", source=content)
        logger.info("Pushed %s config file", CONFIG_FILE_NAME)

    def _database_is_available(self) -> bool:
        """Returns True if the database is available.

        Returns:
            bool: True if the database is available.
        """
        return self._database.is_resource_created()

    def _database_info(self) -> dict:
        """Returns the database data.

        Returns:
            Dict: The database data.
        """
        if not self._database_is_available():
            raise RuntimeError(f"Database `{DATABASE_NAME}` is not available")
        return self._database.fetch_relation_data()[self._database.relations[0].id]

    def _get_database_uri(self) -> str:
        """Returns the database URI.

        Returns:
            str: The database URI.
        """
        try:
            return self._database_info()["uris"].split(",")[0]
        except KeyError:
            return ""

    @property
    def _pebble_layer(self) -> Layer:
        """Returns pebble layer for the charm.

        Returns:
            Layer: Pebble Layer
        """
        return Layer(
            {
                "summary": "nrf layer",
                "description": "pebble config layer for nrf",
                "services": {
                    "nrf": {
                        "override": "replace",
                        "startup": "enabled",
                        "command": f"/free5gc/nrf/nrf --nrfcfg {BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}",  # noqa: E501
                        "environment": self._environment_variables,
                    },
                },
            }
        )

    @property
    def _environment_variables(self) -> dict:
        """Returns workload service environment variables.

        Returns:
            dict: Environment variables
        """
        return {
            "GRPC_GO_LOG_VERBOSITY_LEVEL": "99",
            "GRPC_GO_LOG_SEVERITY_LEVEL": "info",
            "GRPC_TRACE": "all",
            "GRPC_VERBOSITY": "debug",
            "MANAGED_BY_CONFIG_POD": "true",
        }

    def _nrf_service_is_running(self) -> bool:
        """Returns whether the NRF service is running.

        Returns:
            bool: Whether the NRF service is running.
        """
        if not self._container.can_connect():
            return False
        try:
            service = self._container.get_service(self._service_name)
        except ModelError:
            return False
        return service.is_running()

    def _get_nrf_url(self) -> str:
        """Returns NRF URL."""
        scheme = "https" if self._certificate_is_stored() else "http"
        return f"{scheme}://nrf:{NRF_SBI_PORT}"


if __name__ == "__main__":
    main(NRFOperatorCharm)
