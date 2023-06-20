# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from io import StringIO
from unittest.mock import Mock, patch

from ops import testing
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus

from charm import NRFOperatorCharm  # type: ignore[import]

DB_APPLICATION_NAME = "mongodb-k8s"
BASE_CONFIG_PATH = "/etc/nrf"
CONFIG_FILE_NAME = "nrfcfg.yaml"


class TestCharm(unittest.TestCase):
    @patch(
        "charm.KubernetesServicePatch",
        lambda charm, ports: None,
    )
    def setUp(self):
        self.harness = testing.Harness(NRFOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def _create_database_relation(self) -> int:
        """Create a database relation.

        Returns:
            relation_id: ID of the created relation
        """
        relation_id = self.harness.add_relation(
            relation_name="database",
            remote_app=DB_APPLICATION_NAME,
        )
        self.harness.add_relation_unit(
            relation_id=relation_id,
            remote_unit_name=f"{DB_APPLICATION_NAME}/0",
        )
        return relation_id

    def _database_is_available(self) -> None:
        """Create a database relation and set the database information."""
        database_relation_id = self._create_database_relation()
        self.harness.update_relation_data(
            relation_id=database_relation_id,
            app_or_unit=DB_APPLICATION_NAME,
            key_values={
                "username": "dummy",
                "password": "dummy",
                "uris": "http://dummy",
            },
        )

    @staticmethod
    def _read_file(path: str) -> str:
        """Reads a file and returns as a string.

        Args:
            path (str): path to the file.

        Returns:
            str: content of the file.
        """
        with open(path, "r") as f:
            content = f.read()
        return content

    def test_given_database_relation_not_created_when_pebble_ready_then_status_is_blocked(self):
        self.harness.container_pebble_ready(container_name="nrf")

        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Waiting for database relation to be created"),
        )

    def test_given_database_not_available_when_pebble_ready_then_status_is_waiting(
        self,
    ):
        self._create_database_relation()
        self.harness.container_pebble_ready(container_name="nrf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for the database to be available"),
        )

    @patch("charms.data_platform_libs.v0.data_interfaces.DatabaseRequires.is_resource_created")
    def test_given_database_information_not_available_when_pebble_ready_then_status_is_waiting(
        self,
        patch_is_resource_created,
    ):
        patch_is_resource_created.return_value = True
        self._create_database_relation()
        self.harness.container_pebble_ready(container_name="nrf")
        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for database URI"),
        )

    def test_given_storage_not_attached_when_pebble_ready_then_status_is_waiting(
        self,
    ):
        self._database_is_available()
        self.harness.container_pebble_ready(container_name="nrf")

        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for storage to be attached"),
        )

    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("ops.model.Container.pull")
    @patch("charm.check_output")
    def test_given_database_info_and_storage_attached_when_pebble_ready_then_config_file_is_rendered_and_pushed(  # noqa: E501
        self,
        patch_check_output,
        patch_pull,
        patch_push,
        patch_exists,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_pull.return_value = StringIO("dummy")
        patch_exists.side_effect = [True, False, False]
        self._database_is_available()
        self.harness.container_pebble_ready(container_name="nrf")
        with open("tests/unit/expected_config/config.conf") as expected_config_file:
            expected_content = expected_config_file.read()
            patch_push.assert_called_with(
                path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}",
                source=expected_content.strip(),
            )

    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("ops.model.Container.pull")
    @patch("charm.check_output")
    def test_given_content_of_config_file_not_changed_when_pebble_ready_then_config_file_is_not_pushed(  # noqa: E501
        self,
        patch_check_output,
        patch_pull,
        patch_push,
        patch_exists,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_pull.side_effect = [
            StringIO(self._read_file("tests/unit/expected_config/config.conf").strip()),
        ]
        patch_exists.side_effect = [True, False, True]
        self._database_is_available()
        self.harness.container_pebble_ready(container_name="nrf")
        patch_push.assert_not_called()

    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("ops.model.Container.pull")
    @patch("charm.check_output")
    def test_given_config_pushed_when_pebble_ready_then_pebble_plan_is_applied(
        self,
        patch_check_output,
        patch_pull,
        patch_push,
        patch_exists,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_exists.return_value = True

        self._database_is_available()

        self.harness.container_pebble_ready(container_name="nrf")

        expected_plan = {
            "services": {
                "nrf": {
                    "override": "replace",
                    "command": "/free5gc/nrf/nrf --nrfcfg /etc/nrf/nrfcfg.yaml",
                    "startup": "enabled",
                    "environment": {
                        "GRPC_GO_LOG_VERBOSITY_LEVEL": "99",
                        "GRPC_GO_LOG_SEVERITY_LEVEL": "info",
                        "GRPC_TRACE": "all",
                        "GRPC_VERBOSITY": "debug",
                        "MANAGED_BY_CONFIG_POD": "true",
                    },
                }
            },
        }

        updated_plan = self.harness.get_container_pebble_plan("nrf").to_dict()

        self.assertEqual(expected_plan, updated_plan)

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    def test_given_database_relation_is_created_and_config_file_is_written_when_pebble_ready_then_status_is_active(  # noqa: E501
        self,
        patch_check_output,
        patch_push,
        patch_exists,
        patch_pull,
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_exists.return_value = True

        self._database_is_available()

        self.harness.container_pebble_ready(container_name="nrf")
        self.harness.container_pebble_ready("nrf")

        self.assertEqual(self.harness.model.unit.status, ActiveStatus())

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    def test_given_ip_not_available_when_pebble_ready_then_status_is_waiting(
        self,
        patch_check_output,
        patch_push,
        patch_exists,
        patch_pull,
    ):
        patch_check_output.return_value = b""
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )
        patch_exists.return_value = True

        self._database_is_available()

        self.harness.container_pebble_ready(container_name="nrf")
        self.harness.container_pebble_ready("nrf")

        self.assertEqual(
            self.harness.model.unit.status,
            WaitingStatus("Waiting for pod IP address to be available"),
        )

    def test_given_service_is_not_running_when_fiveg_nrf_relation_joined_then_nrf_url_is_not_in_relation_databag(  # noqa: E501
        self,
    ):
        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)
        relation_id = self.harness.add_relation(
            relation_name="fiveg-nrf",
            remote_app="nrf-requirer",
        )
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="nrf-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data, {})

    @patch("ops.model.Container.push", new=Mock)
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("charm.check_output")
    def test_given_unit_is_not_leader_when_fiveg_nrf_relation_joined_then_nrf_url_is_not_in_relation_databag(  # noqa: E501
        self, patch_check_output, patch_exists, patch_pull
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_exists.return_value = True
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )

        self._database_is_available()

        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=False)
        self.harness.container_pebble_ready("nrf")

        relation_id = self.harness.add_relation(
            relation_name="fiveg-nrf",
            remote_app="nrf-requirer",
        )
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="nrf-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data, {})

    @patch("ops.model.Container.push", new=Mock)
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("charm.check_output")
    def test_given_http_nrf_url_and_service_is_running_when_fiveg_nrf_relation_joined_then_nrf_url_is_in_relation_databag(  # noqa: E501
        self, patch_check_output, patch_exists, patch_pull
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_exists.side_effect = [True, False, False, False]
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )

        self._database_is_available()

        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)
        self.harness.container_pebble_ready("nrf")

        relation_id = self.harness.add_relation(
            relation_name="fiveg-nrf",
            remote_app="nrf-requirer",
        )
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="nrf-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["url"], "http://nrf:29510")

    @patch("ops.model.Container.push", new=Mock)
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("charm.check_output")
    def test_given_https_nrf_url_and_service_is_running_when_fiveg_nrf_relation_joined_then_nrf_url_is_in_relation_databag(  # noqa: E501
        self, patch_check_output, patch_exists, patch_pull
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_exists.return_value = True
        patch_pull.return_value = StringIO(
            self._read_file("tests/unit/expected_config/config.conf").strip()
        )

        self._database_is_available()

        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)
        self.harness.container_pebble_ready("nrf")

        relation_id = self.harness.add_relation(
            relation_name="fiveg-nrf",
            remote_app="nrf-requirer",
        )
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="nrf-requirer/0")
        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_data["url"], "https://nrf:29510")

    @patch("ops.model.Container.push", new=Mock)
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("charm.check_output")
    def test_service_starts_running_after_nrf_relation_joined_when_fiveg_pebble_ready_then_nrf_url_is_in_relation_databag(  # noqa: E501
        self, patch_check_output, patch_exists, patch_pull
    ):
        patch_check_output.return_value = b"1.1.1.1"
        patch_exists.side_effect = [True, False, False, False]
        patch_pull.side_effect = [
            StringIO(self._read_file("tests/unit/expected_config/config.conf").strip()),
            StringIO(self._read_file("tests/unit/expected_config/config.conf").strip()),
        ]

        self.harness.set_can_connect(container="nrf", val=False)

        self.harness.set_leader(is_leader=True)

        relation_1_id = self.harness.add_relation(
            relation_name="fiveg-nrf",
            remote_app="nrf-requirer-1",
        )

        relation_2_id = self.harness.add_relation(
            relation_name="fiveg-nrf",
            remote_app="nrf-requirer-2",
        )
        self.harness.add_relation_unit(
            relation_id=relation_1_id, remote_unit_name="nrf-requirer-1/0"
        )
        self.harness.add_relation_unit(
            relation_id=relation_2_id, remote_unit_name="nrf-requirer-2/0"
        )

        self._database_is_available()

        self.harness.container_pebble_ready("nrf")

        relation_1_data = self.harness.get_relation_data(
            relation_id=relation_1_id, app_or_unit=self.harness.charm.app.name
        )
        relation_2_data = self.harness.get_relation_data(
            relation_id=relation_2_id, app_or_unit=self.harness.charm.app.name
        )
        self.assertEqual(relation_1_data["url"], "http://nrf:29510")
        self.assertEqual(relation_2_data["url"], "http://nrf:29510")

    @patch("charm.generate_private_key")
    @patch("ops.model.Container.push")
    def test_given_can_connect_when_on_certificates_relation_created_then_private_key_is_generated(
        self, patch_push, patch_generate_private_key
    ):
        private_key = b"whatever key content"
        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)
        patch_generate_private_key.return_value = private_key

        self.harness.charm._on_certificates_relation_created(event=Mock)

        patch_push.assert_called_with(
            path="/free5gc/support/TLS/nrf.key", source=private_key.decode()
        )

    @patch("ops.model.Container.remove_path")
    @patch("ops.model.Container.exists")
    def test_given_certificates_are_stored_when_on_certificates_relation_broken_then_certificates_are_removed(  # noqa: E501
        self, patch_exists, patch_remove_path
    ):
        patch_exists.return_value = True
        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)

        self.harness.charm._on_certificates_relation_broken(event=Mock)

        patch_remove_path.assert_any_call(path="/free5gc/support/TLS/nrf.pem")
        patch_remove_path.assert_any_call(path="/free5gc/support/TLS/nrf.key")
        patch_remove_path.assert_any_call(path="/free5gc/support/TLS/nrf.csr")

    @patch(
        "charms.tls_certificates_interface.v2.tls_certificates.TLSCertificatesRequiresV2.request_certificate_creation",  # noqa: E501
        new=Mock,
    )
    @patch("ops.model.Container.push")
    @patch("charm.generate_csr")
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    def test_given_private_key_exists_when_on_certificates_relation_joined_then_csr_is_generated(
        self, patch_exists, patch_pull, patch_generate_csr, patch_push
    ):
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        patch_pull.return_value = StringIO("private key content")
        patch_exists.return_value = True
        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)

        self.harness.charm._on_certificates_relation_joined(event=Mock)

        patch_push.assert_called_with(path="/free5gc/support/TLS/nrf.csr", source=csr.decode())

    @patch(
        "charms.tls_certificates_interface.v2.tls_certificates.TLSCertificatesRequiresV2.request_certificate_creation",  # noqa: E501
    )
    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.generate_csr")
    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    def test_given_private_key_exists_when_on_certificates_relation_joined_then_cert_is_requested(
        self,
        patch_exists,
        patch_pull,
        patch_generate_csr,
        patch_request_certificate_creation,
    ):
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        patch_pull.return_value = StringIO("private key content")
        patch_exists.return_value = True
        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)

        self.harness.charm._on_certificates_relation_joined(event=Mock)

        patch_request_certificate_creation.assert_called_with(certificate_signing_request=csr)

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    def test_given_csr_matches_stored_one_when_certificate_available_then_certificate_is_pushed(
        self,
        patch_push,
        patch_exists,
        patch_pull,
    ):
        csr = "Whatever CSR content"
        patch_pull.return_value = StringIO(csr)
        patch_exists.return_value = True
        certificate = "Whatever certificate content"
        event = Mock()
        event.certificate = certificate
        event.certificate_signing_request = csr
        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)

        self.harness.charm._on_certificate_available(event=event)

        patch_push.assert_called_with(path="/free5gc/support/TLS/nrf.pem", source=certificate)

    @patch("ops.model.Container.pull")
    @patch("ops.model.Container.exists")
    @patch("ops.model.Container.push")
    def test_given_csr_doesnt_match_stored_one_when_certificate_available_then_certificate_is_not_pushed(  # noqa: E501
        self,
        patch_push,
        patch_exists,
        patch_pull,
    ):
        patch_pull.return_value = StringIO("Stored CSR content")
        patch_exists.return_value = True
        certificate = "Whatever certificate content"
        event = Mock()
        event.certificate = certificate
        event.certificate_signing_request = "Relation CSR content (different from stored one)"
        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)

        self.harness.charm._on_certificate_available(event=event)

        patch_push.assert_not_called()

    @patch(
        "charms.tls_certificates_interface.v2.tls_certificates.TLSCertificatesRequiresV2.request_certificate_creation",  # noqa: E501
    )
    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.generate_csr")
    @patch("ops.model.Container.pull")
    def test_given_certificate_does_not_match_stored_one_when_certificate_expiring_then_certificate_is_not_requested(  # noqa: E501
        self, patch_pull, patch_generate_csr, patch_request_certificate_creation
    ):
        event = Mock()
        patch_pull.return_value = StringIO("Stored certificate content")
        event.certificate = "Relation certificate content (different from stored)"
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)

        self.harness.charm._on_certificate_expiring(event=event)

        patch_request_certificate_creation.assert_not_called()

    @patch(
        "charms.tls_certificates_interface.v2.tls_certificates.TLSCertificatesRequiresV2.request_certificate_creation",  # noqa: E501
    )
    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.generate_csr")
    @patch("ops.model.Container.pull")
    def test_given_certificate_matches_stored_one_when_certificate_expiring_then_certificate_is_requested(  # noqa: E501
        self, patch_pull, patch_generate_csr, patch_request_certificate_creation
    ):
        certificate = "whatever certificate content"
        event = Mock()
        event.certificate = certificate
        patch_pull.return_value = StringIO(certificate)
        csr = b"whatever csr content"
        patch_generate_csr.return_value = csr
        self.harness.set_can_connect(container="nrf", val=True)
        self.harness.set_leader(is_leader=True)

        self.harness.charm._on_certificate_expiring(event=event)

        patch_request_certificate_creation.assert_called_with(certificate_signing_request=csr)
