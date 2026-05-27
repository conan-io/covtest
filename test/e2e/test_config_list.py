from covtest.cli import main


def test_config_list_basic(capsys, tmp_path):
    ret = main(["config", "list", str(tmp_path)])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Config file:" in out
    assert "Environment variables:" in out
    assert "Effective configuration:" in out
    assert "max_commits" in out
    assert "server_url" in out


def test_config_list_reads_ini(capsys, tmp_path):
    ini = tmp_path / "covtest.ini"
    ini.write_text("[covtest]\nserver_url = https://example.com\nmax_commits = 5\n")
    ret = main(["config", "list", str(tmp_path)])
    assert ret == 0
    out = capsys.readouterr().out
    assert str(ini) in out
    assert "https://example.com" in out
    assert "max_commits          = 5" in out


def test_config_list_redacts_sensitive(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("COVTEST_PASSWORD", "secret")
    monkeypatch.setenv("COVTEST_TOKEN", "tok123")
    ret = main(["config", "list", str(tmp_path)])
    assert ret == 0
    out = capsys.readouterr().out
    assert "secret" not in out
    assert "tok123" not in out
    assert "***" in out
