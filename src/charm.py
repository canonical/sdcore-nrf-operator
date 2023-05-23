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
from jinja2 import Environment, FileSystemLoader  # type: ignore[import]
from lightkube.models.core_v1 import ServicePort
from ops.charm import CharmBase, PebbleReadyEvent, RelationJoinedEvent
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)

BASE_CONFIG_PATH = "/etc/nrf"
CONFIG_FILE_NAME = "nrfcfg.yaml"
DATABASE_NAME = "free5gc"
NRF_SBI_PORT = 29510
DATABASE_RELATION_NAME = "database"


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
        if not self._database_info:
            self.unit.status = WaitingStatus("Waiting for database info to be available")
            event.defer()
            return
        if not self._container.exists(path=BASE_CONFIG_PATH):
            self.unit.status = WaitingStatus("Waiting for storage to be attached")
            event.defer()
            return
        content = self._render_config(database_url=self._database_info["uris"].split(",")[0])
        self._push_config_file(content=content)
        if not self._config_file_is_written():
            self.unit.status = WaitingStatus("Waiting for config file to be written")
            event.defer()
            return
        self._configure_workload()
        self.unit.status = ActiveStatus()

    def _configure_workload(self):
        """Configures pebble layer for the amf container."""
        plan = self._container.get_plan()
        layer = self._pebble_layer
        if plan.services != layer.services:
            self._container.add_layer("nrf", layer, combine=True)
            self._container.restart(self._service_name)

    def _config_file_is_written(self) -> bool:
        """Returns whether the config file was written to the workload container.

        Returns:
            bool: Whether the config file was written.
        """
        if not self._container.exists(f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}"):
            return False
        return True

    def _relation_created(self, relation_name: str) -> bool:
        """Returns whether a given Juju relation was crated.

        Args:
            relation_name (str): Relation name

        Returns:
            bool: Whether the relation was created.
        """
        return bool(self.model.get_relation(relation_name))

    @staticmethod
    def _render_config(database_url: str) -> str:
        jinja2_environment = Environment(loader=FileSystemLoader("src/templates/"))
        template = jinja2_environment.get_template("nrfcfg.yaml.j2")
        content = template.render(
            database_name=DATABASE_NAME,
            database_url=database_url,
            nrf_sbi_port=NRF_SBI_PORT,
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

    @property
    def _database_is_available(self) -> bool:
        """Returns True if the database is available.

        Returns:
            bool: True if the database is available.
        """
        return self._database.is_resource_created()

    @property
    def _database_info(self) -> dict:
        """Returns the database data.

        Returns:
            Dict: The database data.
        """
        if not self._database_is_available:
            return {}
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


if __name__ == "__main__":
    main(NRFOperatorCharm)
