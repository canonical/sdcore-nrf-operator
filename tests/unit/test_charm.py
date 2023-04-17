# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import Mock, patch

from ops import testing
from ops.model import ActiveStatus, WaitingStatus

from charm import NRFOperatorCharm


class TestCharm(unittest.TestCase):
    @patch(
        "charm.KubernetesServicePatch",
        lambda charm, ports: None,
    )
    def setUp(self):
        self.harness = testing.Harness(NRFOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @patch("ops.model.Container.push")
    def test_given_can_connect_to_workload_container_when_database_created_event_then_config_file_is_written(  # noqa: E501
        self,
        patch_push,
    ):
        uri_0 = "1.2.3.4:1234"
        uri_1 = "5.6.7.8:1111"

        self.harness.set_can_connect(container="nrf", val=True)
        event = Mock(uris="".join([uri_0, ",", uri_1]))

        self.harness.charm._on_database_created(event=event)
        patch_push.assert_called_with(
            path="/etc/nrf/nrfcfg.yaml",
            source=f'configuration:\n  DefaultPlmnId:\n    mcc: "208"\n    mnc: "93"\n  MongoDBName: free5gc\n  MongoDBUrl: { uri_0 }\n  mongoDBStreamEnable: true\n  mongodb:\n    name: free5gc\n    url: { uri_0 }\n  nfKeepAliveTime: 60\n  nfProfileExpiryEnable: true\n  sbi:\n    bindingIPv4: 0.0.0.0\n    port: 29510\n    registerIPv4: nrf\n    scheme: http\n  serviceNameList:\n  - nnrf-nfm\n  - nnrf-disc\ninfo:\n  description: NRF initial local configuration\n  version: 1.0.0\nlogger:\n  AMF:\n    ReportCaller: false\n    debugLevel: info\n  AUSF:\n    ReportCaller: false\n    debugLevel: info\n  Aper:\n    ReportCaller: false\n    debugLevel: info\n  CommonConsumerTest:\n    ReportCaller: false\n    debugLevel: info\n  FSM:\n    ReportCaller: false\n    debugLevel: info\n  MongoDBLibrary:\n    ReportCaller: false\n    debugLevel: info\n  N3IWF:\n    ReportCaller: false\n    debugLevel: info\n  NAS:\n    ReportCaller: false\n    debugLevel: info\n  NGAP:\n    ReportCaller: false\n    debugLevel: info\n  NRF:\n    ReportCaller: false\n    debugLevel: info\n  NamfComm:\n    ReportCaller: false\n    debugLevel: info\n  NamfEventExposure:\n    ReportCaller: false\n    debugLevel: info\n  NsmfPDUSession:\n    ReportCaller: false\n    debugLevel: info\n  NudrDataRepository:\n    ReportCaller: false\n    debugLevel: info\n  OpenApi:\n    ReportCaller: false\n    debugLevel: info\n  PCF:\n    ReportCaller: false\n    debugLevel: info\n  PFCP:\n    ReportCaller: false\n    debugLevel: info\n  PathUtil:\n    ReportCaller: false\n    debugLevel: info\n  SMF:\n    ReportCaller: false\n    debugLevel: info\n  UDM:\n    ReportCaller: false\n    debugLevel: info\n  UDR:\n    ReportCaller: false\n    debugLevel: info\n  WEBUI:\n    ReportCaller: false\n    debugLevel: info',  # noqa: E501
        )

    @patch("ops.model.Container.push")
    def test_given_cant_connect_to_workload_container_when_database_created_event_then_event_is_deferred(  # noqa: E501
        self,
        patch_push,
    ):
        self.harness.set_can_connect(container="nrf", val=False)
        event = Mock(uris="1.2.3.4:1234,5.6.7.8:1111")

        self.harness.charm._on_database_created(event=event)

        event.defer.assert_called()
        patch_push.not_called()

    @patch("ops.model.Container.exists")
    def test_given_config_file_is_written_when_pebble_ready_then_pebble_plan_is_applied(
        self, patch_exists
    ):
        patch_exists.return_value = True
        self.harness.add_relation(relation_name="database", remote_app="mongodb")

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

    @patch("ops.model.Container.exists")
    def test_given_config_file_is_not_written_when_pebble_ready_then_status_is_waiting(
        self, patch_exists
    ):
        patch_exists.return_value = False
        self.harness.add_relation(relation_name="database", remote_app="mongodb")

        self.harness.container_pebble_ready(container_name="nrf")

        self.assertEqual(
            self.harness.model.unit.status, WaitingStatus("Waiting for config file to be written")
        )

    @patch("ops.model.Container.exists")
    def test_given_database_relation_is_created_and_config_file_is_written_when_pebble_ready_then_status_is_active(  # noqa: E501
        self, patch_exists
    ):
        patch_exists.return_value = True
        self.harness.add_relation(relation_name="database", remote_app="mongodb")

        self.harness.container_pebble_ready("nrf")

        self.assertEqual(self.harness.model.unit.status, ActiveStatus())

    @patch("ops.model.Container.exists")
    def test_given_container_not_ready_when_database_relation_joins_then_status_is_waiting(
        self, patch_exists
    ):
        patch_exists.return_value = True
        relation_id = self.harness.add_relation(relation_name="database", remote_app="mongodb")
        self.harness.add_relation_unit(relation_id=relation_id, remote_unit_name="mongodb/0")

        self.harness.set_can_connect(container="nrf", val=False)

        self.assertEqual(
            self.harness.model.unit.status, WaitingStatus("Waiting for container to be ready")
        )
