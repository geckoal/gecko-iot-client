"""Tests for GeckoIotClient public diagnostics API (v1.1.0)."""

import pytest
from unittest.mock import MagicMock, patch

from gecko_iot_client import GeckoIotClient
from gecko_iot_client.models.zone_types import ZoneType


@pytest.fixture
def mock_transporter():
    """Create a mock transporter for testing."""
    transporter = MagicMock()
    transporter.on_connectivity_change = MagicMock()
    return transporter


@pytest.fixture
def client(mock_transporter):
    """Create a GeckoIotClient instance for testing."""
    return GeckoIotClient("test-device-001", mock_transporter)


class TestHasConfiguration:
    """Tests for the has_configuration property."""

    def test_false_when_no_configuration_loaded(self, client):
        """has_configuration is False before configuration is loaded."""
        assert client.has_configuration is False

    def test_true_when_configuration_loaded(self, client):
        """has_configuration is True after configuration is set."""
        client._configuration = {"zones": {}}
        assert client.has_configuration is True

    def test_false_when_configuration_explicitly_none(self, client):
        """has_configuration is False when configuration is explicitly None."""
        client._configuration = None
        assert client.has_configuration is False


class TestHasState:
    """Tests for the has_state property."""

    def test_false_when_no_state_loaded(self, client):
        """has_state is False before state is loaded."""
        assert client.has_state is False

    def test_true_when_state_loaded(self, client):
        """has_state is True after state data is set."""
        client._state = {"reported": {"zones": {}}}
        assert client.has_state is True

    def test_false_when_state_explicitly_none(self, client):
        """has_state is False when state is explicitly None."""
        client._state = None
        assert client.has_state is False


class TestZoneCounts:
    """Tests for the zone_counts property."""

    def test_empty_when_no_zones(self, client):
        """zone_counts returns empty dict when no zones exist."""
        assert client.zone_counts == {}

    def test_empty_when_zones_is_empty_dict(self, client):
        """zone_counts returns empty dict when zones dict is empty."""
        client._zones = {}
        assert client.zone_counts == {}

    def test_returns_counts_by_type(self, client):
        """zone_counts returns correct counts for each zone type."""
        mock_zone_1 = MagicMock()
        mock_zone_2 = MagicMock()
        mock_zone_3 = MagicMock()

        client._zones = {
            ZoneType.FLOW_ZONE: [mock_zone_1, mock_zone_2],
            ZoneType.LIGHTING_ZONE: [mock_zone_3],
        }

        counts = client.zone_counts
        assert counts[ZoneType.FLOW_ZONE.value] == 2
        assert counts[ZoneType.LIGHTING_ZONE.value] == 1

    def test_single_zone_type(self, client):
        """zone_counts works with a single zone type."""
        mock_zone = MagicMock()
        client._zones = {ZoneType.TEMPERATURE_CONTROL_ZONE: [mock_zone]}

        counts = client.zone_counts
        assert counts[ZoneType.TEMPERATURE_CONTROL_ZONE.value] == 1
        assert len(counts) == 1


class TestGetDiagnostics:
    """Tests for the get_diagnostics() method."""

    def test_basic_diagnostics_structure(self, client):
        """get_diagnostics returns all required base fields."""
        diag = client.get_diagnostics()

        assert "client_id" in diag
        assert "is_connected" in diag
        assert "has_configuration" in diag
        assert "has_state" in diag
        assert "zone_counts" in diag

    def test_client_id_matches(self, client):
        """get_diagnostics returns the correct client_id."""
        diag = client.get_diagnostics()
        assert diag["client_id"] == "test-device-001"

    def test_initial_state(self, client):
        """get_diagnostics returns correct values for freshly created client."""
        diag = client.get_diagnostics()

        assert diag["client_id"] == "test-device-001"
        assert diag["is_connected"] is False
        assert diag["has_configuration"] is False
        assert diag["has_state"] is False
        assert diag["zone_counts"] == {}

    def test_includes_connectivity_when_available(self, client):
        """get_diagnostics includes connectivity section."""
        # ConnectivityStatus is always initialized, so it should be present
        diag = client.get_diagnostics()

        assert "connectivity" in diag
        assert "transport_connected" in diag["connectivity"]
        assert "gateway_status" in diag["connectivity"]
        assert "vessel_status" in diag["connectivity"]
        assert "is_fully_connected" in diag["connectivity"]

    def test_includes_transporter_info(self, client):
        """get_diagnostics includes transporter section when transporter exists."""
        diag = client.get_diagnostics()

        assert "transporter" in diag
        assert "type" in diag["transporter"]
        assert diag["transporter"]["type"] == "MagicMock"

    def test_zone_counts_in_diagnostics(self, client):
        """get_diagnostics includes zone_counts from zones."""
        mock_zone = MagicMock()
        client._zones = {ZoneType.FLOW_ZONE: [mock_zone]}

        diag = client.get_diagnostics()
        assert diag["zone_counts"] == {ZoneType.FLOW_ZONE.value: 1}

    def test_has_configuration_reflected(self, client):
        """get_diagnostics reflects has_configuration correctly."""
        client._configuration = {"zones": {"flow": {}}}

        diag = client.get_diagnostics()
        assert diag["has_configuration"] is True

    def test_has_state_reflected(self, client):
        """get_diagnostics reflects has_state correctly."""
        client._state = {"reported": {}}

        diag = client.get_diagnostics()
        assert diag["has_state"] is True

    def test_transporter_monitor_id(self, client, mock_transporter):
        """get_diagnostics includes monitor_id from transporter if available."""
        mock_transporter.monitor_id = "monitor-abc-123"

        diag = client.get_diagnostics()
        assert diag["transporter"]["monitor_id"] == "monitor-abc-123"

    def test_transporter_without_monitor_id(self, mock_transporter):
        """get_diagnostics handles transporter without monitor_id attribute."""
        # Remove monitor_id attribute
        del mock_transporter.monitor_id
        client = GeckoIotClient("test-device", mock_transporter)

        diag = client.get_diagnostics()
        assert diag["transporter"]["monitor_id"] is None
