#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed operator for the 5G NRF service."""

import logging
from typing import Union

from charms.data_platform_libs.v0.data_interfaces import (  # type: ignore[import]
    DatabaseCreatedEvent,
    DatabaseRequires,
)
from charms.observability_libs.v1.kubernetes_service_patch import (  # type: ignore[import]
    KubernetesServicePatch,
)
from charms.sdcore_nrf.v0.fiveg_nrf import NRFProvides  # type: ignore[import]
from jinja2 import Environment, FileSystemLoader  # type: ignore[import]
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase, PebbleReadyEvent, RelationJoinedEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, ModelError, WaitingStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)

BASE_CONFIG_PATH = "/etc/nrf"
CONFIG_FILE_NAME = "nrfcfg.yaml"
DATABASE_NAME = "free5gc"
NRF_SBI_PORT = 29510
DATABASE_RELATION_NAME = "database"
NRF_URL = f"http://nrf:{NRF_SBI_PORT}"
NRF_RELATION_NAME = "fiveg-nrf"


class NRFOperatorCharm(CharmBase):
    """Main class to describe juju event handling for the 5G NRF operator."""

    def __init__(self, *args):
        """Initialize charm."""
        super().__init__(*args)
        self._container_name = self._service_name = "nrf"
        self._container = self.unit.get_container(self._container_name)
        self._database = DatabaseRequires(
            self, relation_name=DATABASE_RELATION_NAME, database_name=DATABASE_NAME
        )
        self.framework.observe(self.on.database_relation_joined, self._configure_nrf)
        self.framework.observe(self.on.nrf_pebble_ready, self._configure_nrf)
        self.framework.observe(self._database.on.database_created, self._configure_nrf)
        self.nrf_provider = NRFProvides(self, NRF_RELATION_NAME)
        self.framework.observe(
            self.on.fiveg_nrf_relation_joined, self._on_fiveg_nrf_relation_joined
        )
        self._service_patcher = KubernetesServicePatch(
            charm=self,
            ports=[
                ServicePort(name="sbi", port=NRF_SBI_PORT),
            ],
        )

    def _configure_nrf(
        self, event: Union[PebbleReadyEvent, RelationJoinedEvent, DatabaseCreatedEvent]
    ) -> None:
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
            event.defer()
            return
        if not self._database_is_available():
            self.unit.status = WaitingStatus("Waiting for the database to be available")
            event.defer()
            return
        if not self._database_info():
            self.unit.status = WaitingStatus("Waiting for database info to be available")
            event.defer()
            return
        if not self._container.exists(path=BASE_CONFIG_PATH):
            self.unit.status = WaitingStatus("Waiting for storage to be attached")
            event.defer()
            return
        self._generate_config_file()
        self._configure_workload()
        self._publish_nrf_info_for_all_requirers(NRF_URL)
        self.unit.status = ActiveStatus()

    def _generate_config_file(
        self,
    ) -> None:
        """Handles creation of the NRF config file.

        Generates NRF config file based on a given template.
        Pushes NRF config file to the workload.
        Calls `_configure_workload` function to forcibly restart the NRF service in order
        to fetch new config.
        """
        content = self._render_config(
            database_url=self._database_info()["uris"].split(",")[0],
            database_name=DATABASE_NAME,
            nrf_sbi_port=NRF_SBI_PORT,
        )
        if not self._config_file_content_matches(content=content):
            self._push_config_file(
                content=content,
            )
            self._configure_workload(restart=True)

    def _configure_workload(self, restart: bool = False) -> None:
        """Configures pebble layer for the amf container."""
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
        self.nrf_provider.set_nrf_information(
            url=NRF_URL,
            relation_id=event.relation.id,
        )

    def _publish_nrf_info_for_all_requirers(self, url: str) -> None:
        """Publish nrf information in the databags of all relations requiring it.

        Args:
            url: URL of the NRF service
        """
        if not self.unit.is_leader():
            return
        if not self._relation_created(NRF_RELATION_NAME):
            return
        self.nrf_provider.set_nrf_information_in_all_relations(url)

    def _relation_created(self, relation_name: str) -> bool:
        """Returns whether a given Juju relation was crated.

        Args:
            relation_name (str): Relation name

        Returns:
            bool: Whether the relation was created.
        """
        return bool(self.model.get_relation(relation_name))

    @staticmethod
    def _render_config(
        database_name: str,
        database_url: str,
        nrf_sbi_port: int,
    ) -> str:
        jinja2_environment = Environment(loader=FileSystemLoader("src/templates/"))
        template = jinja2_environment.get_template("nrfcfg.yaml.j2")
        content = template.render(
            database_name=database_name,
            database_url=database_url,
            nrf_sbi_port=nrf_sbi_port,
        )
        return content

    def _push_config_file(self, content: str) -> None:
        """Pushes config file to workload.

        Args:
            content: config file content
        """
        if not self._container.can_connect():
            return
        self._container.push(path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}", source=content)
        logger.info(f"Pushed {CONFIG_FILE_NAME} config file")

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


if __name__ == "__main__":
    main(NRFOperatorCharm)
