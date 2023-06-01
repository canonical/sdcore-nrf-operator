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
            self, relation_name="database", database_name=DATABASE_NAME
        )
        self.nrf_provider = NRFProvides(self, NRF_RELATION_NAME)
        self.framework.observe(
            self.on.fiveg_nrf_relation_joined, self._on_fiveg_nrf_relation_joined
        )
        self.framework.observe(self.on.database_relation_joined, self._configure_pebble_layer)
        self.framework.observe(self.on.nrf_pebble_ready, self._configure_pebble_layer)
        self.framework.observe(self._database.on.database_created, self._on_database_created)
        self._service_patcher = KubernetesServicePatch(
            charm=self,
            ports=[
                ServicePort(name="sbi", port=NRF_SBI_PORT),
            ],
        )

    def _on_database_created(self, event: DatabaseCreatedEvent) -> None:
        """Handle database created event.

        Args:
            event: DatabaseCreatedEvent
        """
        if not self._container.can_connect():
            self.unit.status = WaitingStatus("Waiting for container to be ready")
            event.defer()
            return
        self._write_config_file(
            database_url=event.uris.split(",")[0],  # type: ignore[union-attr]
        )
        self._configure_pebble_layer(event)

    def _write_config_file(self, database_url: str) -> None:
        """Writes config file to workload.

        Args:
            database_url: Database URL
        """
        jinja2_environment = Environment(loader=FileSystemLoader("src/templates/"))
        template = jinja2_environment.get_template("nrfcfg.yaml.j2")
        content = template.render(
            database_name=DATABASE_NAME,
            database_url=database_url,
            nrf_sbi_port=NRF_SBI_PORT,
        )
        self._container.push(path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}", source=content)
        logger.info(f"Pushed {CONFIG_FILE_NAME} config file")

    def _configure_pebble_layer(
        self, event: Union[PebbleReadyEvent, RelationJoinedEvent, DatabaseCreatedEvent]
    ) -> None:
        """Adds pebble layer and manages Juju unit status.

        Args:
            event: Juju event
        """
        if not self._database_relation_is_created:
            self.unit.status = BlockedStatus("Waiting for database relation to be created")
            return
        if not self._container.can_connect():
            self.unit.status = WaitingStatus("Waiting for container to be ready")
            event.defer()
            return
        if not self._config_file_is_written:
            self.unit.status = WaitingStatus("Waiting for config file to be written")
            return
        self._container.add_layer("nrf", self._pebble_layer, combine=True)
        self._container.replan()
        self._publish_nrf_info_for_all_requirers(NRF_URL)
        self.unit.status = ActiveStatus()

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

    @property
    def _config_file_is_written(self) -> bool:
        """Returns whether the config file was written to the workload container.

        Returns:
            bool: Whether the config file was written.
        """
        if not self._container.exists(f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}"):
            logger.info(f"Config file is not written: {CONFIG_FILE_NAME}")
            return False
        logger.info("Config file is written")
        return True

    @property
    def _database_relation_is_created(self) -> bool:
        """Returns whether database relation is created.

        Returns:
            bool: Whether database relation is created.
        """
        return self._relation_created("database")

    def _relation_created(self, relation_name: str) -> bool:
        """Returns whether a given Juju relation was crated.

        Args:
            relation_name (str): Relation name

        Returns:
            bool: Whether the relation was created.
        """
        return bool(self.model.relations[relation_name])

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
