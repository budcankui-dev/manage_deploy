def test_mysql_engine_sets_session_time_zone(monkeypatch):
    import database

    monkeypatch.setattr(database.settings, "database_url", "mysql+aiomysql://u:p@db:3306/app")
    monkeypatch.setattr(database.settings, "database_session_time_zone", "+08:00")

    assert database._engine_connect_args() == {
        "init_command": "SET time_zone = '+08:00'",
    }


def test_sqlite_engine_does_not_use_mysql_time_zone_command(monkeypatch):
    import database

    monkeypatch.setattr(database.settings, "database_url", "sqlite+aiosqlite:///./task_manager.db")

    assert database._engine_connect_args() == {}
