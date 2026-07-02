from typer.testing import CliRunner

import cyph3r.cli as cli
import cyph3r.graph as graph_mod

runner = CliRunner()


class OkClient:
    def __init__(self, **kwargs):
        pass

    def read(self, query, parameters=None):
        if "RETURN 1" in query:
            return [{"ok": 1}]
        if "components" in query:
            return [{"v": "2026.05.0"}]
        if "count(n)" in query:
            return [{"c": 3}]
        return []

    def close(self):
        pass


class RefusedClient(OkClient):
    def read(self, query, parameters=None):
        raise ConnectionError("Connection refused (is the server running?)")


class AuthFailClient(OkClient):
    def read(self, query, parameters=None):
        raise PermissionError("The client is unauthorized due to authentication failure.")


def test_check_success(monkeypatch):
    monkeypatch.setattr(graph_mod, "Neo4jClient", OkClient)
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 0
    assert "Connected" in result.output
    assert "2026.05.0" in result.output


def test_check_reports_stopped_dbms(monkeypatch):
    monkeypatch.setattr(graph_mod, "Neo4jClient", RefusedClient)
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 1
    assert "Is the DBMS running" in result.output


def test_check_reports_bad_credentials(monkeypatch):
    monkeypatch.setattr(graph_mod, "Neo4jClient", AuthFailClient)
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 1
    assert "NEO4J_USER / NEO4J_PASSWORD" in result.output
